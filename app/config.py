import os

# When installed as an RPM/systemd service, the app lives at /opt/qc-portal.
# BASE_DIR is computed relative to this file so it works both in dev and production.
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

_DEFAULT_INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
_DEFAULT_SCRIPTS_DIR  = os.path.join(BASE_DIR, 'app', 'scripts')

class Config:
    SECRET_KEY  = os.environ.get('SECRET_KEY',   'kvm-qc-portal-change-me-in-production')
    DATABASE    = os.environ.get('DATABASE',      os.path.join(_DEFAULT_INSTANCE_DIR, 'qc_portal.db'))
    SCRIPTS_DIR = os.environ.get('SCRIPTS_DIR',   _DEFAULT_SCRIPTS_DIR)
    INSTANCE_DIR = os.path.dirname(
        os.environ.get('DATABASE', os.path.join(_DEFAULT_INSTANCE_DIR, 'qc_portal.db'))
    )
