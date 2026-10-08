from flask import Blueprint, render_template, request, jsonify, Response, redirect, url_for, flash, current_app
from app.db import get_db
from app.services.ssh_service import SSHService
from app.services.qc_runner import QCRunner
import json
import csv
import io
import os
import sqlite3

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    
    search_query = request.args.get('q', '').strip()

    if search_query:
        cursor.execute('''
            SELECT h.*, 
                   r.id as last_run_id, r.score, r.pass_count, r.fail_count, r.warn_count, 
                   r.na_count, r.info_count, r.finished_at, r.status as last_run_status
            FROM hosts h
            LEFT JOIN qc_runs r ON r.id = (
                SELECT id FROM qc_runs WHERE host_id = h.id ORDER BY started_at DESC LIMIT 1
            )
            WHERE h.name LIKE ? OR h.ip LIKE ? OR h.serial_number LIKE ?
            ORDER BY h.name ASC
        ''', (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        cursor.execute('''
            SELECT h.*, 
                   r.id as last_run_id, r.score, r.pass_count, r.fail_count, r.warn_count, 
                   r.na_count, r.info_count, r.finished_at, r.status as last_run_status
            FROM hosts h
            LEFT JOIN qc_runs r ON r.id = (
                SELECT id FROM qc_runs WHERE host_id = h.id ORDER BY started_at DESC LIMIT 1
            )
            ORDER BY h.name ASC
        ''')
    hosts = cursor.fetchall()
    
    # Calculate global stats
    cursor.execute('SELECT COUNT(*) FROM hosts')
    total_hosts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM qc_runs WHERE status = 'completed'")
    total_runs = cursor.fetchone()[0]

    cursor.execute('''
        SELECT SUM(pass_count), SUM(fail_count), SUM(warn_count) 
        FROM qc_runs 
        WHERE status = 'completed'
    ''')
    row = cursor.fetchone()
    sum_pass = row[0] or 0
    sum_fail = row[1] or 0
    sum_warn = row[2] or 0

    # Recent runs table
    if search_query:
        cursor.execute('''
            SELECT r.*, h.name as host_name, h.ip as host_ip
            FROM qc_runs r
            JOIN hosts h ON r.host_id = h.id
            WHERE h.name LIKE ? OR h.ip LIKE ? OR r.serial_number LIKE ?
            ORDER BY r.started_at DESC LIMIT 20
        ''', (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        cursor.execute('''
            SELECT r.*, h.name as host_name, h.ip as host_ip
            FROM qc_runs r
            JOIN hosts h ON r.host_id = h.id
            ORDER BY r.started_at DESC LIMIT 20
        ''')
    recent_runs = cursor.fetchall()

    return render_template('dashboard.html', 
                           hosts=hosts, 
                           total_hosts=total_hosts,
                           total_runs=total_runs,
                           sum_pass=sum_pass,
                           sum_fail=sum_fail,
                           sum_warn=sum_warn,
                           recent_runs=recent_runs,
                           search_query=search_query)


@main_bp.route('/hosts', methods=['GET'])
def hosts_list():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts ORDER BY name ASC')
    hosts = cursor.fetchall()

    cursor.execute('''
        SELECT r.*, h.name as host_name, h.ip as host_ip
        FROM remediation_log r
        JOIN hosts h ON r.host_id = h.id
        ORDER BY r.performed_at DESC LIMIT 15
    ''')
    remediations = cursor.fetchall()

    return render_template('hosts.html', hosts=hosts, remediations=remediations)


@main_bp.route('/api/hosts/add', methods=['POST'])
def add_host():
    name = request.form.get('name', '').strip()
    ip = request.form.get('ip', '').strip()
    port = int(request.form.get('port', 22))
    username = request.form.get('username', 'root').strip()
    auth_type = request.form.get('auth_type', 'key')
    ssh_key_path = request.form.get('ssh_key_path', '').strip()
    password_enc = request.form.get('password', '').strip()

    if not name or not ip:
        flash('Host name and IP address are required.', 'danger')
        return redirect(url_for('main.dashboard'))

    db = get_db()
    try:
        db.execute('''
            INSERT INTO hosts (name, ip, port, username, auth_type, ssh_key_path, password_enc)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, ip, port, username, auth_type, ssh_key_path, password_enc))
        db.commit()
        flash(f'Host "{name}" ({ip}) added successfully.', 'success')
    except Exception as e:
        flash(f'Failed to add host: {str(e)}', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/api/hosts/edit/<int:host_id>', methods=['POST'])
def edit_host(host_id):
    name = request.form.get('name', '').strip()
    ip = request.form.get('ip', '').strip()
    port = int(request.form.get('port', 22))
    username = request.form.get('username', 'root').strip()
    auth_type = request.form.get('auth_type', 'key')
    ssh_key_path = request.form.get('ssh_key_path', '').strip()
    password_enc = request.form.get('password', '').strip()

    db = get_db()
    try:
        db.execute('''
            UPDATE hosts SET name = ?, ip = ?, port = ?, username = ?, auth_type = ?, ssh_key_path = ?, password_enc = ?
            WHERE id = ?
        ''', (name, ip, port, username, auth_type, ssh_key_path, password_enc, host_id))
        db.commit()
        flash(f'Host "{name}" updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating host: {str(e)}', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/api/hosts/delete/<int:host_id>', methods=['POST'])
def delete_host(host_id):
    db = get_db()
    try:
        db.execute('DELETE FROM hosts WHERE id = ?', (host_id,))
        db.commit()
        flash('Host deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting host: {str(e)}', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/api/hosts/test-connection/<int:host_id>', methods=['POST'])
def test_host_connection(host_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        return jsonify({'success': False, 'message': 'Host not found'}), 404

    success, message = SSHService.test_connection(
        ip=host['ip'],
        port=host['port'],
        username=host['username'],
        auth_type=host['auth_type'],
        ssh_key_path=host['ssh_key_path'],
        password=host['password_enc']
    )

    return jsonify({'success': success, 'message': message})


@main_bp.route('/run-qc/<int:host_id>')
def run_qc_page(host_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        flash('Host not found.', 'danger')
        return redirect(url_for('main.dashboard'))

    return render_template('run_qc.html', host=host)


@main_bp.route('/api/stream-qc/<int:host_id>')
def stream_qc(host_id):
    db_path = current_app.config['DATABASE']
    scripts_dir = current_app.config['SCRIPTS_DIR']

    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        conn.close()
        return Response("data: [FAIL] Host not found\n\n", mimetype='text/event-stream')

    cursor.execute('''
        INSERT INTO qc_runs (host_id, serial_number, status)
        VALUES (?, ?, 'running')
    ''', (host_id, host['serial_number'] or 'N/A'))
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()

    host_dict = dict(host)
    if host_dict.get('password_enc'):
        host_dict['password'] = host_dict['password_enc']

    def event_generator():
        for line in QCRunner.execute_qc(db_path, host_id, run_id, host_dict, scripts_dir):
            yield line

    return Response(event_generator(), mimetype='text/event-stream')


@main_bp.route('/api/reports/latest/<int:host_id>')
def get_latest_report(host_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT id FROM qc_runs WHERE host_id = ? ORDER BY started_at DESC LIMIT 1', (host_id,))
    row = cursor.fetchone()

    if row:
        return redirect(url_for('main.report_detail', run_id=row['id']))
    return redirect(url_for('main.dashboard'))


@main_bp.route('/reports/<int:run_id>')
def report_detail(run_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT r.*, h.name as host_name, h.ip as host_ip, h.username as host_user, h.serial_number as host_serial
        FROM qc_runs r
        JOIN hosts h ON r.host_id = h.id
        WHERE r.id = ?
    ''', (run_id,))
    run = cursor.fetchone()

    if not run:
        flash('Report not found.', 'danger')
        return redirect(url_for('main.dashboard'))

    cursor.execute('SELECT * FROM qc_checks WHERE run_id = ? ORDER BY section ASC, sno ASC', (run_id,))
    checks = cursor.fetchall()

    sections = sorted(list(set(c['section'] for c in checks)))

    return render_template('report.html', run=run, checks=checks, sections=sections)


@main_bp.route('/api/reports/<int:run_id>/csv')
def download_report_csv(run_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT r.*, h.name as host_name, h.ip as host_ip
        FROM qc_runs r
        JOIN hosts h ON r.host_id = h.id
        WHERE r.id = ?
    ''', (run_id,))
    run = cursor.fetchone()

    if not run:
        return "Report not found", 404

    cursor.execute('SELECT * FROM qc_checks WHERE run_id = ? ORDER BY section ASC, sno ASC', (run_id,))
    checks = cursor.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)

    cw.writerow(['Section', 'S.No', 'Check Item', 'Command Used', 'Expected Result', 'Actual Result', 'Status', 'Notes / Action'])
    for c in checks:
        cw.writerow([c['section'], c['sno'], c['check_item'], c['command_used'], c['expected'], c['actual'], c['status'], c['notes']])

    cw.writerow([])
    cw.writerow(['Physical Server QC Check Report'])
    cw.writerow(['Hostname', run['host_ip']])
    cw.writerow(['Serial Tag', run['serial_number'] or 'N/A'])
    cw.writerow(['Report Date', str(run['finished_at'] or run['started_at'])])
    cw.writerow(['Checked By', 'QC Portal'])
    cw.writerow(['Total Checks', run['total_checks']])
    cw.writerow(['PASS', run['pass_count']])
    cw.writerow(['FAIL', run['fail_count']])
    cw.writerow(['WARNING', run['warn_count']])
    cw.writerow(['N/A', run['na_count']])
    cw.writerow(['INFO', run['info_count']])
    cw.writerow(['Pass Rate', run['score']])

    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)

    filename = f"qc_report_{run['host_name']}_{run['serial_number'] or 'serial'}_{run_id}.csv"
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

# ============================================================
# NEW FEATURE: Delete Single History Run or Clear All History
# ============================================================
@main_bp.route('/api/history/delete/<int:run_id>', methods=['POST'])
def delete_history_run(run_id):
    db = get_db()
    try:
        db.execute('DELETE FROM qc_runs WHERE id = ?', (run_id,))
        db.commit()
        flash(f'QC Run #{run_id} deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting run history: {str(e)}', 'danger')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/api/history/clear-all', methods=['POST'])
def clear_all_history():
    db = get_db()
    try:
        db.execute('DELETE FROM qc_runs')
        db.execute('DELETE FROM qc_checks')
        db.commit()
        flash('All QC history cleared successfully.', 'success')
    except Exception as e:
        flash(f'Error clearing history: {str(e)}', 'danger')
    return redirect(url_for('main.dashboard'))

# ============================================================
# NEW FEATURE: List iLO Users before changing iLO Password
# ============================================================
@main_bp.route('/api/hosts/ilo-users/<int:host_id>', methods=['GET'])
def list_ilo_users(host_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        return jsonify({'success': False, 'message': 'Host not found'}), 404

    host_dict = dict(host)
    if host_dict.get('password_enc'):
        host_dict['password'] = host_dict['password_enc']

    # Run ipmitool user list 1 via SSH
    exit_code, stdout, stderr = SSHService.execute_command(
        host_dict['ip'], host_dict['port'], host_dict['username'],
        host_dict['auth_type'], host_dict['ssh_key_path'], host_dict.get('password'),
        "ipmitool user list 1 2>/dev/null"
    )

    if exit_code != 0 or not stdout.strip():
        return jsonify({
            'success': False,
            'message': f'ipmitool failed or unavailable: {stderr or stdout or "No output"}'
        })

    # Parse ipmitool user list output:
    # ID  Name             Callin  Link Auth  IPMI Msg   Channel Priv Limit
    # 2   root             true    true       true       ADMINISTRATOR
    users = []
    lines = stdout.strip().splitlines()
    for line in lines[1:]: # Skip header
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            user_id = parts[0]
            user_name = parts[1]
            priv = parts[-1] if len(parts) > 2 else 'USER'
            users.append({'id': user_id, 'name': user_name, 'priv': priv})

    return jsonify({'success': True, 'users': users, 'raw': stdout})

# ============================================================
# NEW FEATURE: Add Custom QC Check (Appends to QC.sh)
# ============================================================
@main_bp.route('/api/custom-check/add', methods=['POST'])
def add_custom_qc_check():
    item_name = request.form.get('item_name', '').strip()
    command_str = request.form.get('command', '').strip()
    section = request.form.get('section', 'Operating System').strip()
    expected = request.form.get('expected', 'Command output verified').strip()

    if not item_name or not command_str:
        flash('Check Name and Command are required.', 'danger')
        return redirect(url_for('main.dashboard'))

    qc_script_path = os.path.join(current_app.config['SCRIPTS_DIR'], 'QC.sh')

    # Construct bash check snippet
    bash_snippet = f"""
    # Custom Check: {item_name}
    sno=$((sno+1)); cmd="{command_str}"; out="$(run 15 "$cmd")"
    actual="${{out:-Unable to retrieve}}"
    status=$([ -n "$out" ] && echo "$STATUS_PASS" || echo "$STATUS_WARN")
    record_check "{section}" "$sno" "{item_name}" "$cmd" "{expected}" "$actual" "$status" "Custom check added via QC Portal"
"""

    try:
        with open(qc_script_path, 'r', encoding='utf-8') as f:
            script_text = f.read()

        # Insert custom check right before write_summary in main() function
        if 'write_summary' in script_text:
            updated_text = script_text.replace('write_summary', f"{bash_snippet}\n    write_summary", 1)
        else:
            updated_text = script_text + f"\n{bash_snippet}\n"

        with open(qc_script_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(updated_text)

        flash(f'Custom check "{item_name}" added to script successfully!', 'success')
    except Exception as e:
        flash(f'Error updating script: {str(e)}', 'danger')

    return redirect(url_for('main.dashboard'))

# ============================================================
# NEW FEATURE: Ad-Hoc SSH Command Console
# ============================================================
@main_bp.route('/api/adhoc-command', methods=['POST'])
def run_adhoc_command():
    host_id = request.json.get('host_id') if request.is_json else request.form.get('host_id')
    command = (request.json.get('command') if request.is_json else request.form.get('command')) or ''
    command = command.strip()

    if not host_id or not command:
        return jsonify({'success': False, 'output': 'Host and command are required.'}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        return jsonify({'success': False, 'output': 'Host not found'}), 404

    host_dict = dict(host)
    if host_dict.get('password_enc'):
        host_dict['password'] = host_dict['password_enc']

    # Execute ad-hoc read-only command via SSH
    exit_code, stdout, stderr = SSHService.execute_command(
        host_dict['ip'], host_dict['port'], host_dict['username'],
        host_dict['auth_type'], host_dict['ssh_key_path'], host_dict.get('password'),
        command, timeout=30
    )

    output = stdout if stdout else stderr
    return jsonify({
        'success': exit_code == 0,
        'exit_code': exit_code,
        'output': output or '(No output returned)'
    })


@main_bp.route('/api/remediate/<int:host_id>', methods=['POST'])
def perform_remediation(host_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM hosts WHERE id = ?', (host_id,))
    host = cursor.fetchone()

    if not host:
        return jsonify({'success': False, 'message': 'Host not found'}), 404

    host_dict = dict(host)
    if host_dict.get('password_enc'):
        host_dict['password'] = host_dict['password_enc']

    action = request.json.get('action') if request.is_json else request.form.get('action')

    if action == 'create_user':
        user_pass = (request.json or request.form).get('user_pass', 'F11st6J6b@12#$4')
        res = QCRunner.remediate_create_user(db, host_id, host_dict, user_pass)
        return jsonify(res)

    elif action == 'change_root_pass':
        new_pass = (request.json or request.form).get('new_pass')
        if not new_pass:
            return jsonify({'success': False, 'message': 'New password is required'}), 400
        res = QCRunner.remediate_root_password(db, host_id, host_dict, new_pass)
        return jsonify(res)

    elif action == 'change_ilo_pass':
        user_id = (request.json or request.form).get('user_id', '2')
        new_pass = (request.json or request.form).get('new_pass')
        if not new_pass:
            return jsonify({'success': False, 'message': 'New iLO password is required'}), 400
        res = QCRunner.remediate_ilo_password(db, host_id, host_dict, user_id, new_pass)
        return jsonify(res)

    return jsonify({'success': False, 'message': f'Unknown action: {action}'}), 400
