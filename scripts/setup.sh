#!/usr/bin/env bash
# First-time setup for MultiViewer step 1 (WebGUI + network safety
# mechanism) on Ubuntu Server 24.04.4. Idempotent: safe to re-run.
#
# What this does:
#   1. Installs OS packages needed by step 1 (python3, netplan, iproute2).
#   2. Creates a Python venv under /opt/multiviewer/venv and installs the
#      WebGUI's dependencies into it.
#   3. Creates /etc/multiviewer (config store + netplan backups) and
#      /var/log/multiviewer (event log).
#   4. Installs and enables the systemd units (webgui service, and the
#      always-on NIC-rollback safety timer).
#
# It does NOT touch any NIC's IP configuration -- that only happens when
# an operator explicitly applies a change from the WebGUI.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/multiviewer"
VENV_DIR="${INSTALL_DIR}/venv"

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

echo "==> Installing OS packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip netplan.io iproute2

echo "==> Setting up install directory (${INSTALL_DIR})"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete --exclude '.git' --exclude '__pycache__' "${REPO_ROOT}/webgui/" "${INSTALL_DIR}/webgui/"

echo "==> Creating Python virtualenv"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${INSTALL_DIR}/webgui/requirements.txt"

echo "==> Creating config/log directories"
mkdir -p /etc/multiviewer/netplan-backups
mkdir -p /var/log/multiviewer

echo "==> Installing rollback check script"
install -m 0755 "${REPO_ROOT}/scripts/nic_rollback_check.py" "${INSTALL_DIR}/nic_rollback_check.py"
# The check script imports webgui/app as a package relative to its own
# location, so it needs a copy of the webgui tree next to it too.
rsync -a --delete --exclude '.git' --exclude '__pycache__' "${REPO_ROOT}/webgui/" "${INSTALL_DIR}/webgui/"

echo "==> Installing systemd units"
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-webgui.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-nic-rollback.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-nic-rollback.timer" /etc/systemd/system/

systemctl daemon-reload

echo "==> Enabling services"
systemctl enable --now multiviewer-webgui.service
# The rollback timer is always enabled, independent of whether a NIC
# change is currently pending -- it is a cheap periodic no-op check when
# nothing is pending, and is the safety net that must survive across
# reboots and WebGUI crashes.
systemctl enable --now multiviewer-nic-rollback.timer

echo "==> Done."
echo "WebGUI should now be reachable at http://<1G NIC IP>/mgmt/"
echo "See README.md before changing any NIC's IP address from the WebGUI."
