import sqlite3
import os
from datetime import datetime
from flask import g, current_app

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db(app):
    os.makedirs(app.config['INSTANCE_DIR'], exist_ok=True)
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        # Hosts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hosts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL UNIQUE,
                port INTEGER DEFAULT 22,
                username TEXT DEFAULT 'root',
                auth_type TEXT DEFAULT 'key',
                ssh_key_path TEXT,
                password_enc TEXT,
                serial_number TEXT DEFAULT 'N/A',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # QC Runs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS qc_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                serial_number TEXT DEFAULT 'N/A',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                total_checks INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                warn_count INTEGER DEFAULT 0,
                na_count INTEGER DEFAULT 0,
                info_count INTEGER DEFAULT 0,
                score TEXT DEFAULT '0%',
                status TEXT DEFAULT 'running',
                raw_log TEXT DEFAULT '',
                FOREIGN KEY (host_id) REFERENCES hosts (id) ON DELETE CASCADE
            )
        ''')

        # QC Checks detail table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS qc_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                section TEXT,
                sno INTEGER,
                check_item TEXT,
                command_used TEXT,
                expected TEXT,
                actual TEXT,
                status TEXT,
                notes TEXT,
                FOREIGN KEY (run_id) REFERENCES qc_runs (id) ON DELETE CASCADE
            )
        ''')

        # Remediation log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS remediation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                performed_by TEXT DEFAULT 'Operator',
                performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY (host_id) REFERENCES hosts (id) ON DELETE CASCADE
            )
        ''')

        # Pre-seed default target KVM host if table is empty
        cursor.execute('SELECT COUNT(*) FROM hosts')
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute('''
                INSERT INTO hosts (name, ip, port, username, auth_type, serial_number, created_at)
                VALUES ('KVM-Node-01', '192.168.209.137', 22, 'root', 'key', 'CN78912345', CURRENT_TIMESTAMP)
            ''')

        # Migration check: Ensure serial_number columns exist in existing DB
        try:
            cursor.execute("ALTER TABLE hosts ADD COLUMN serial_number TEXT DEFAULT 'N/A'")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE qc_runs ADD COLUMN serial_number TEXT DEFAULT 'N/A'")
        except Exception:
            pass

        db.commit()


