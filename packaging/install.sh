#!/usr/bin/env bash
# ============================================================
# install.sh  —  Installer for QC Portal
#
# Usage (run as root or with sudo from the project root):
#   chmod +x packaging/install.sh
#   sudo ./packaging/install.sh
# ============================================================
set -euo pipefail

INSTALL_DIR="/opt/qc-portal"
LOG_DIR="/var/log/qc-portal"
SVC_USER="qcportal"
SVC_GROUP="qcportal"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================================"
echo " QC Portal — Direct Installer"
echo " Installing from : $PROJECT_ROOT"
echo " Installing to   : $INSTALL_DIR"
echo "================================================================"

# Require root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (or with sudo)."
    exit 1
fi

# ------------------------------------------------------------
# 1. Install system dependencies
# ------------------------------------------------------------
echo "[1/7] Installing system dependencies..."
if command -v zypper &>/dev/null; then
    zypper install -y --no-confirm python3 python3-pip 2>/dev/null || true
elif command -v dnf &>/dev/null; then
    dnf install -y python3 python3-pip 2>/dev/null || true
elif command -v yum &>/dev/null; then
    yum install -y python3 python3-pip 2>/dev/null || true
else
    echo "[WARN] Cannot detect package manager. Ensure python3 and pip are installed."
fi

# ------------------------------------------------------------
# 2. Create service user/group
# ------------------------------------------------------------
echo "[2/7] Creating system user '$SVC_USER'..."
getent group  "$SVC_GROUP" >/dev/null 2>&1 || groupadd --system "$SVC_GROUP"
getent passwd "$SVC_USER"  >/dev/null 2>&1 || \
    useradd --system --gid "$SVC_GROUP" --no-create-home \
            --home-dir "$INSTALL_DIR" --shell /sbin/nologin \
            --comment "QC Portal service account" "$SVC_USER"

# ------------------------------------------------------------
# 3. Copy application files
# ------------------------------------------------------------
echo "[3/7] Copying application files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rsync -a --exclude '__pycache__' --exclude '*.pyc' \
    "$PROJECT_ROOT/app"             "$INSTALL_DIR/"
cp   "$PROJECT_ROOT/run.py"         "$INSTALL_DIR/run.py"
cp   "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/requirements.txt"

mkdir -p "$INSTALL_DIR/instance"
mkdir -p "$LOG_DIR"

# ------------------------------------------------------------
# 4. Create Python virtual environment & install dependencies
# ------------------------------------------------------------
echo "[4/7] Setting up Python virtual environment..."
VENV="$INSTALL_DIR/venv"
WHEELS_DIR="$SCRIPT_DIR/wheels"

if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
fi

# Upgrade pip first (no-index from venv's bundled pip, no network needed)
"$VENV/bin/pip" install --quiet --upgrade pip --no-index 2>/dev/null || \
    "$VENV/bin/pip" install --quiet --upgrade pip

if [[ -d "$WHEELS_DIR" ]] && ls "$WHEELS_DIR"/*.whl &>/dev/null; then
    echo "    Found local wheels directory — installing offline (no internet needed)..."
    # Install from local wheels; --no-index means pip will NOT hit PyPI
    "$VENV/bin/pip" install --quiet \
        --no-index \
        --find-links "$WHEELS_DIR" \
        -r "$INSTALL_DIR/requirements.txt"
else
    echo "    No local wheels found — installing from PyPI (internet required)..."
    "$VENV/bin/pip" install --quiet \
        --retries 5 \
        --timeout 60 \
        -r "$INSTALL_DIR/requirements.txt"
fi
echo "    Python dependencies installed."

# ------------------------------------------------------------
# 5. Install environment config
# ------------------------------------------------------------
echo "[5/7] Installing environment config..."
mkdir -p /etc/qc-portal
if [[ ! -f /etc/qc-portal/qc-portal.env ]]; then
    cp "$SCRIPT_DIR/qc-portal.env" /etc/qc-portal/qc-portal.env
    chmod 640 /etc/qc-portal/qc-portal.env
    echo "    Config written to /etc/qc-portal/qc-portal.env"
    echo "    ⚠  Edit SECRET_KEY in /etc/qc-portal/qc-portal.env before production use!"
else
    echo "    Existing config preserved at /etc/qc-portal/qc-portal.env"
fi

# ------------------------------------------------------------
# 6. Install & enable systemd service
# ------------------------------------------------------------
echo "[6/7] Installing systemd service..."
cp "$SCRIPT_DIR/qc-portal.service" /etc/systemd/system/qc-portal.service
chmod 644 /etc/systemd/system/qc-portal.service

# Fix ownership
chown -R "$SVC_USER:$SVC_GROUP" "$INSTALL_DIR"
chown -R "$SVC_USER:$SVC_GROUP" "$LOG_DIR"
chmod 750 "$INSTALL_DIR/instance"

systemctl daemon-reload
systemctl enable  qc-portal.service
systemctl restart qc-portal.service

# ------------------------------------------------------------
# 7. Verify
# ------------------------------------------------------------
echo "[7/7] Verifying service status..."
sleep 2
if systemctl is-active --quiet qc-portal.service; then
    HOST_IP=$(hostname -I | awk '{print $1}')
    echo ""
    echo "================================================================"
    echo " ✅  QC Portal is RUNNING!"
    echo "    URL   : http://${HOST_IP}:5000"
    echo "    Logs  : journalctl -u qc-portal -f"
    echo "    Stop  : systemctl stop qc-portal"
    echo "    Status: systemctl status qc-portal"
    echo "================================================================"
else
    echo ""
    echo "❌  Service failed to start. Check logs:"
    echo "    journalctl -u qc-portal -n 50 --no-pager"
    exit 1
fi
