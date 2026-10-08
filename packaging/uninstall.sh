#!/usr/bin/env bash
# ============================================================
# uninstall.sh  —  Removes QC Portal (direct-install version)
#
# Usage:
#   sudo ./packaging/uninstall.sh
# ============================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run as root (or sudo)."
    exit 1
fi

echo "================================================================"
echo " QC Portal — Uninstaller"
echo "================================================================"

echo "[1/4] Stopping and disabling service..."
systemctl stop    qc-portal.service 2>/dev/null || true
systemctl disable qc-portal.service 2>/dev/null || true

echo "[2/4] Removing service file..."
rm -f /etc/systemd/system/qc-portal.service
systemctl daemon-reload

echo "[3/4] Removing application files..."
rm -rf /opt/qc-portal

echo "[4/4] Removing log directory..."
rm -rf /var/log/qc-portal

echo ""
echo "Note: /etc/qc-portal/qc-portal.env kept for manual cleanup."
echo "      Remove with: rm -rf /etc/qc-portal"
echo ""
echo "================================================================"
echo " ✅  QC Portal has been removed."
echo "================================================================"
