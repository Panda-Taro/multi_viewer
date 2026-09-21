#!/usr/bin/env bash
# First-time setup for MultiViewer step 1 (WebGUI + NIC network config) on
# Ubuntu Server 24.04.4. Idempotent: safe to re-run.
#
# What this does:
#   1. Installs OS packages needed by step 1 (python3, netplan, iproute2).
#   2. Creates a Python venv under /opt/multiviewer/venv and installs the
#      WebGUI's dependencies into it.
#   3. Creates /etc/multiviewer (config store) and /var/log/multiviewer
#      (event log).
#   4. Installs and enables the WebGUI systemd unit.
#
# It does NOT touch any NIC's IP configuration -- that only happens when
# an operator explicitly applies a change from the WebGUI (which reboots
# the server immediately; there is no automatic rollback -- see README.md).
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
mkdir -p /etc/multiviewer
mkdir -p /var/log/multiviewer

echo "==> Installing systemd unit"
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-webgui.service" /etc/systemd/system/

systemctl daemon-reload

echo "==> Enabling service"
systemctl enable --now multiviewer-webgui.service

echo "==> Done."
echo "WebGUI should now be reachable at http://<1G NIC IP>/mgmt/"
echo "See README.md before changing any NIC's IP address from the WebGUI:"
echo "applying a change reboots the server immediately with no automatic rollback."
