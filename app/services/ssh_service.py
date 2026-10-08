import paramiko
import os
import io
import time
from typing import Generator, Tuple, Optional

class SSHService:
    @staticmethod
    def _get_client(ip: str, port: int = 22, username: str = 'root', 
                    auth_type: str = 'key', ssh_key_path: Optional[str] = None, 
                    password: Optional[str] = None, timeout: int = 15) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        kwargs = {
            'hostname': ip,
            'port': port,
            'username': username,
            'timeout': timeout,
            'banner_timeout': timeout,
            'auth_timeout': timeout
        }
        
        if auth_type == 'key' and ssh_key_path and os.path.exists(ssh_key_path):
            kwargs['key_filename'] = ssh_key_path
        elif auth_type == 'password' and password:
            kwargs['password'] = password
        else:
            # Fallback attempt with default SSH keys (~/.ssh/id_rsa etc.)
            kwargs['look_for_keys'] = True
            kwargs['allow_agent'] = True
            if password:
                kwargs['password'] = password
                
        client.connect(**kwargs)
        return client

    @classmethod
    def test_connection(cls, ip: str, port: int = 22, username: str = 'root', 
                        auth_type: str = 'key', ssh_key_path: Optional[str] = None, 
                        password: Optional[str] = None) -> Tuple[bool, str]:
        """Test SSH connectivity and return (success, message)."""
        try:
            client = cls._get_client(ip, port, username, auth_type, ssh_key_path, password, timeout=10)
            stdin, stdout, stderr = client.exec_command('hostname', timeout=10)
            hostname = stdout.read().decode('utf-8', errors='replace').strip()
            client.close()
            return True, f"Successfully connected to host: {hostname or ip}"
        except Exception as e:
            return False, f"SSH connection failed: {str(e)}"

    @classmethod
    def execute_command(cls, ip: str, port: int = 22, username: str = 'root', 
                        auth_type: str = 'key', ssh_key_path: Optional[str] = None, 
                        password: Optional[str] = None, command: str = '', 
                        timeout: int = 300) -> Tuple[int, str, str]:
        """Execute a single command and return (exit_code, stdout, stderr)."""
        client = None
        try:
            client = cls._get_client(ip, port, username, auth_type, ssh_key_path, password, timeout=15)
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            out_str = stdout.read().decode('utf-8', errors='replace')
            err_str = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()
            return exit_code, out_str, err_str
        except Exception as e:
            return -1, '', str(e)
        finally:
            if client:
                client.close()

    @classmethod
    def upload_file(cls, ip: str, port: int, username: str, auth_type: str, 
                    ssh_key_path: Optional[str], password: Optional[str], 
                    local_path: str, remote_path: str) -> Tuple[bool, str]:
        """Upload local file to remote destination via SFTP."""
        client = None
        try:
            client = cls._get_client(ip, port, username, auth_type, ssh_key_path, password)
            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            return True, "File uploaded successfully"
        except Exception as e:
            return False, f"SFTP upload failed: {str(e)}"
        finally:
            if client:
                client.close()

    @classmethod
    def download_file(cls, ip: str, port: int, username: str, auth_type: str, 
                      ssh_key_path: Optional[str], password: Optional[str], 
                      remote_path: str, local_path: str) -> Tuple[bool, str]:
        """Download remote file to local destination via SFTP."""
        client = None
        try:
            client = cls._get_client(ip, port, username, auth_type, ssh_key_path, password)
            sftp = client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            return True, "File downloaded successfully"
        except Exception as e:
            return False, f"SFTP download failed: {str(e)}"
        finally:
            if client:
                client.close()
