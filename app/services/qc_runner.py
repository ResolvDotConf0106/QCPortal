import os
import time
import sqlite3
import tempfile
from typing import Generator, Dict, Any
from app.services.ssh_service import SSHService
from app.services.parser import QCParser
from flask import current_app

class QCRunner:
    @staticmethod
    def execute_qc(db_path: str, host_id: int, run_id: int, host_dict: Dict[str, Any], scripts_dir: str) -> Generator[str, None, None]:
        """
        Executes read-only QC script on target host over SSH.
        Yields log output lines for SSE streaming.
        Saves final CSV results to database upon completion.
        """
        db_conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        db_conn.row_factory = sqlite3.Row

        ip = host_dict['ip']
        port = host_dict['port']
        username = host_dict['username']
        auth_type = host_dict['auth_type']
        ssh_key_path = host_dict['ssh_key_path']
        password = host_dict.get('password')

        local_script_path = os.path.join(scripts_dir, 'QC.sh')
        remote_script_path = '/tmp/server_qc_check.sh'
        
        yield f"data: [INFO] Connecting to target KVM Host {ip}:{port} as {username}...\n\n"
        time.sleep(0.3)

        # Convert line endings to Unix (\n) before SFTP upload
        temp_unix_script = None
        upload_path = local_script_path
        try:
            with open(local_script_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            unix_content = content.replace('\r\n', '\n').replace('\r', '\n')
            
            tf = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sh', newline='\n')
            tf.write(unix_content)
            tf.close()
            temp_unix_script = tf.name
            upload_path = temp_unix_script
        except Exception as ex:
            yield f"data: [WARN] Notice preparing script: {str(ex)}\n\n"

        # 1. Upload QC script to remote /tmp
        success, msg = SSHService.upload_file(
            ip, port, username, auth_type, ssh_key_path, password,
            upload_path, remote_script_path
        )

        if temp_unix_script and os.path.exists(temp_unix_script):
            try:
                os.remove(temp_unix_script)
            except Exception:
                pass

        if not success:
            error_msg = f"Failed to upload QC script to {ip}: {msg}"
            yield f"data: [FAIL] {error_msg}\n\n"
            db_conn.execute("UPDATE qc_runs SET status = 'failed', raw_log = ? WHERE id = ?", (error_msg, run_id))
            db_conn.commit()
            db_conn.close()
            return

        yield f"data: [INFO] QC script uploaded to {remote_script_path}. Normalizing line endings & granting permissions...\n\n"
        
        # 2. chmod +x & dos2unix fix
        SSHService.execute_command(
            ip, port, username, auth_type, ssh_key_path, password,
            f"sed -i 's/\\r$//' {remote_script_path} && chmod +x {remote_script_path}"
        )

        # 3. Execute script (Read-Only mode, no --fix)
        yield f"data: [INFO] Starting Physical Server QC Check (Read-Only Mode)...\n\n"
        
        ssh_client = None
        log_lines = []
        remote_csv_name = ""

        try:
            ssh_client = SSHService._get_client(ip, port, username, auth_type, ssh_key_path, password)
            channel = ssh_client.get_transport().open_session()
            channel.get_pty()
            channel.exec_command(f"cd /tmp && bash {remote_script_path}")

            # Stream output line-by-line
            while not channel.exit_status_ready():
                if channel.recv_ready():
                    data = channel.recv(2048).decode('utf-8', errors='replace')
                    for line in data.splitlines():
                        clean_line = line.rstrip()
                        if clean_line:
                            log_lines.append(clean_line)
                            yield f"data: {clean_line}\n\n"
                            if "CSV report:" in clean_line:
                                remote_csv_name = clean_line.split("CSV report:")[1].strip()
                time.sleep(0.1)

            # Capture any remaining buffer
            while channel.recv_ready():
                data = channel.recv(2048).decode('utf-8', errors='replace')
                for line in data.splitlines():
                    clean_line = line.rstrip()
                    if clean_line:
                        log_lines.append(clean_line)
                        yield f"data: {clean_line}\n\n"
                        if "CSV report:" in clean_line:
                            remote_csv_name = clean_line.split("CSV report:")[1].strip()

            exit_code = channel.recv_exit_status()
            yield f"data: [INFO] QC Execution completed with exit code: {exit_code}\n\n"

        except Exception as e:
            err_line = f"[FAIL] Error during SSH execution: {str(e)}"
            log_lines.append(err_line)
            yield f"data: {err_line}\n\n"
            db_conn.execute("UPDATE qc_runs SET status = 'failed', raw_log = ? WHERE id = ?", ("\n".join(log_lines), run_id))
            db_conn.commit()
            db_conn.close()
            return
        finally:
            if ssh_client:
                ssh_client.close()

        # 4. If remote CSV filename wasn't extracted from stdout, find latest server_qc_*.csv in /tmp
        if not remote_csv_name:
            _, csv_ls, _ = SSHService.execute_command(
                ip, port, username, auth_type, ssh_key_path, password,
                "ls -t /tmp/server_qc_*.csv 2>/dev/null | head -1"
            )
            remote_csv_name = csv_ls.strip()
        else:
            if not remote_csv_name.startswith('/'):
                remote_csv_name = f"/tmp/{remote_csv_name}"

        if not remote_csv_name:
            yield f"data: [WARN] CSV report file was not detected on remote host.\n\n"
            db_conn.execute("UPDATE qc_runs SET status = 'completed_no_report', raw_log = ? WHERE id = ?", ("\n".join(log_lines), run_id))
            db_conn.commit()
            db_conn.close()
            return

        yield f"data: [INFO] Downloading CSV report file: {remote_csv_name}...\n\n"


        # 5. Download remote CSV to local temp file
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp_file:
            local_csv_path = tmp_file.name

        try:
            dl_success, dl_msg = SSHService.download_file(
                ip, port, username, auth_type, ssh_key_path, password,
                remote_csv_name, local_csv_path
            )

            if dl_success:
                parsed = QCParser.parse_csv_report(local_csv_path)
                summary = parsed['summary']
                checks = parsed['checks']

                # Extract Serial Tag / Service Tag from check items if present
                detected_serial = 'N/A'
                for c in checks:
                    if 'Serial' in c.get('check_item', '') or 'Service Tag' in c.get('check_item', ''):
                        if c.get('actual') and c['actual'] != 'Unable to retrieve':
                            detected_serial = c['actual']
                            break

                # Update qc_runs table with Serial Tag & Stats
                db_conn.execute('''
                    UPDATE qc_runs SET 
                        finished_at = CURRENT_TIMESTAMP,
                        serial_number = ?,
                        total_checks = ?,
                        pass_count = ?,
                        fail_count = ?,
                        warn_count = ?,
                        na_count = ?,
                        info_count = ?,
                        score = ?,
                        status = 'completed',
                        raw_log = ?
                    WHERE id = ?
                ''', (
                    detected_serial,
                    summary['total'], summary['pass'], summary['fail'],
                    summary['warn'], summary['na'], summary['info'],
                    summary['score'], "\n".join(log_lines), run_id
                ))

                # Also update host serial_number
                if detected_serial != 'N/A':
                    db_conn.execute("UPDATE hosts SET serial_number = ? WHERE id = ?", (detected_serial, host_id))

                # Insert individual checks into qc_checks table
                for c in checks:
                    db_conn.execute('''
                        INSERT INTO qc_checks (run_id, section, sno, check_item, command_used, expected, actual, status, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        run_id, c['section'], c['sno'], c['check_item'],
                        c['command_used'], c['expected'], c['actual'], c['status'], c['notes']
                    ))

                db_conn.commit()
                yield f"data: [SUCCESS] QC Results stored. Serial Tag: {detected_serial} | Score: {summary['score']} (PASS: {summary['pass']}, FAIL: {summary['fail']})\n\n"
            else:
                yield f"data: [WARN] Failed to download CSV report: {dl_msg}\n\n"
                db_conn.execute("UPDATE qc_runs SET status = 'completed_download_failed', raw_log = ? WHERE id = ?", ("\n".join(log_lines), run_id))
                db_conn.commit()
        finally:
            if os.path.exists(local_csv_path):
                os.remove(local_csv_path)
            db_conn.close()

        yield "data: [COMPLETE] QC Run Finished.\n\n"

    @staticmethod
    def remediate_create_user(db_conn: sqlite3.Connection, host_id: int, host_dict: Dict[str, Any], user_pass: str = 'F11st6J6b@12#$4') -> Dict[str, Any]:
        """
        Remediation 1: Create local user unx61234, set password, set max age to -1 (never expires).
        """
        ip = host_dict['ip']
        port = host_dict['port']
        username = host_dict['username']
        auth_type = host_dict['auth_type']
        ssh_key_path = host_dict['ssh_key_path']
        password = host_dict.get('password')

        target_user = "unx61234"
        cmd = f"id {target_user} >/dev/null 2>&1 || useradd -m {target_user} && echo '{target_user}:{user_pass}' | chpasswd && chage -M -1 {target_user}"
        
        exit_code, stdout, stderr = SSHService.execute_command(
            ip, port, username, auth_type, ssh_key_path, password, cmd
        )

        status = 'success' if exit_code == 0 else 'failed'
        details = f"Created user {target_user}, set password and never-expires age." if exit_code == 0 else f"Error: {stderr or stdout}"

        db_conn.execute('''
            INSERT INTO remediation_log (host_id, action, performed_by, status, details)
            VALUES (?, 'create_user_unx61234', 'Operator', ?, ?)
        ''', (host_id, status, details))
        db_conn.commit()

        return {'success': exit_code == 0, 'status': status, 'details': details}

    @staticmethod
    def remediate_root_password(db_conn: sqlite3.Connection, host_id: int, host_dict: Dict[str, Any], new_root_pass: str) -> Dict[str, Any]:
        """
        Remediation 2: Change root user password.
        """
        ip = host_dict['ip']
        port = host_dict['port']
        username = host_dict['username']
        auth_type = host_dict['auth_type']
        ssh_key_path = host_dict['ssh_key_path']
        password = host_dict.get('password')

        cmd = f"echo 'root:{new_root_pass}' | chpasswd"
        
        exit_code, stdout, stderr = SSHService.execute_command(
            ip, port, username, auth_type, ssh_key_path, password, cmd
        )

        status = 'success' if exit_code == 0 else 'failed'
        details = "Root password updated successfully." if exit_code == 0 else f"Error changing root password: {stderr or stdout}"

        db_conn.execute('''
            INSERT INTO remediation_log (host_id, action, performed_by, status, details)
            VALUES (?, 'change_root_password', 'Operator', ?, ?)
        ''', (host_id, status, details))
        db_conn.commit()

        return {'success': exit_code == 0, 'status': status, 'details': details}

    @staticmethod
    def remediate_ilo_password(db_conn: sqlite3.Connection, host_id: int, host_dict: Dict[str, Any], user_id: str, new_ilo_pass: str) -> Dict[str, Any]:
        """
        Remediation 3: Change iLO/BMC user password via ipmitool.
        """
        ip = host_dict['ip']
        port = host_dict['port']
        username = host_dict['username']
        auth_type = host_dict['auth_type']
        ssh_key_path = host_dict['ssh_key_path']
        password = host_dict.get('password')

        cmd = f"ipmitool user set password {user_id} '{new_ilo_pass}'"
        
        exit_code, stdout, stderr = SSHService.execute_command(
            ip, port, username, auth_type, ssh_key_path, password, cmd
        )

        status = 'success' if exit_code == 0 else 'failed'
        details = f"iLO user ID {user_id} password updated." if exit_code == 0 else f"Error updating iLO password: {stderr or stdout}"

        db_conn.execute('''
            INSERT INTO remediation_log (host_id, action, performed_by, status, details)
            VALUES (?, 'change_ilo_password', 'Operator', ?, ?)
        ''', (host_id, status, details))
        db_conn.commit()

        return {'success': exit_code == 0, 'status': status, 'details': details}
