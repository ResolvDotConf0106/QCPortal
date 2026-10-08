# QC Portal — Packaging Guide

This directory contains everything needed to install the
**QC Portal** application on a SUSE / RHEL / CentOS Linux host.

---

## 📦 Package Contents

```
packaging/
├── qc-portal.service      ← systemd unit file
├── qc-portal.env          ← Environment / config file
├── install.sh             ← Installer
├── uninstall.sh           ← Uninstaller
└── README.md              ← This file
```

---

## 🚀 Install

No build tools needed. Copies files, creates a Python venv,
installs Gunicorn, and registers a systemd service.

**Step 1:** Copy the entire QC project directory to the target server:
```bash
scp -r ./QC root@<server-ip>:/tmp/qc-portal-src
```

**Step 2:** SSH into the server and run the installer:
```bash
ssh root@<server-ip>
cd /tmp/qc-portal-src
chmod +x packaging/install.sh
sudo ./packaging/install.sh
```

**Step 3:** Access the portal:
```
http://<server-ip>:5000
```

---

## ⚙️ Post-Install Configuration

Edit the environment file to set a strong secret key:
```bash
sudo vi /etc/qc-portal/qc-portal.env
```

Change `SECRET_KEY` to a random string:
```
SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
```

Restart the service to apply:
```bash
sudo systemctl restart qc-portal
```

---

## 🔧 Service Management

| Action | Command |
|--------|---------|
| Status | `systemctl status qc-portal` |
| Start  | `sudo systemctl start qc-portal` |
| Stop   | `sudo systemctl stop qc-portal` |
| Restart| `sudo systemctl restart qc-portal` |
| Logs   | `journalctl -u qc-portal -f` |
| Access logs | `tail -f /var/log/qc-portal/access.log` |
| Error logs  | `tail -f /var/log/qc-portal/error.log` |

---

## 🔄 Upgrade

Re-run the installer — it will rsync new files and restart the service:
```bash
sudo ./packaging/install.sh
```

---

## 🗑️ Uninstall

```bash
sudo ./packaging/uninstall.sh
```

---

## 📁 Install Locations

| Path | Purpose |
|------|---------|
| `/opt/qc-portal/` | Application files & Python venv |
| `/opt/qc-portal/instance/qc_portal.db` | SQLite database (hosts, runs, history) |
| `/opt/qc-portal/app/scripts/QC.sh` | QC bash script (uploaded to remote nodes) |
| `/etc/qc-portal/qc-portal.env` | Environment / config (SECRET_KEY, etc.) |
| `/etc/systemd/system/qc-portal.service` | systemd service unit |
| `/var/log/qc-portal/access.log` | Gunicorn access log |
| `/var/log/qc-portal/error.log` | Gunicorn error log |

---

## 🔐 Security Notes

- The `qcportal` system user runs with minimal privileges (`NoNewPrivileges`, `PrivateTmp`).
- SSH passwords stored in the SQLite DB are **plain-text** — run the portal on a trusted internal network only.
- Change `SECRET_KEY` before production use.
- Consider adding a firewall rule to restrict port 5000 to management VLANs.
