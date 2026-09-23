#!/usr/bin/env bash
# First-time setup for MultiViewer step 1 + 2a + 3a (WebGUI, OS network
# config, the NMOS service, and PTP monitoring) on Ubuntu Server 24.04.4.
# Idempotent: safe to re-run.
#
# What this does:
#   1. Installs OS packages (python3, netplan, iproute2, linuxptp, ethtool).
#   2. Creates a Python venv under /opt/multiviewer/venv and installs the
#      WebGUI's dependencies into it (shared by all services below).
#   3. Creates /etc/multiviewer (config store) and /var/log/multiviewer
#      (event log).
#   4. Installs and enables three systemd units:
#        - multiviewer-webgui.service: the WebGUI (port 80)
#        - multiviewer-nmos.service:   IS-04 registration client + IS-05
#                                       Connection API (port from
#                                       nmos.common_port, set via WebGUI)
#        - multiviewer-ptp.service:    ptp4l (Amber NIC, step 3a stage 1
#                                       only -- monitoring only, does NOT
#                                       touch the OS system clock yet; see
#                                       README.md "ステップ3aのスコープ")
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
  python3 python3-venv python3-pip netplan.io iproute2 linuxptp ethtool

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

echo "==> Installing systemd units"
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-webgui.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-nmos.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/systemd/multiviewer-ptp.service" /etc/systemd/system/

systemctl daemon-reload

echo "==> Enabling services"
systemctl enable --now multiviewer-webgui.service
# multiviewer-nmos.service reads nmos.common_port from config.json at its
# own startup; if it is 0 (unset) the service logs an error and exits, and
# systemd's Restart=on-failure retries it every 10s harmlessly until the
# operator sets a port from the WebGUI's "PTP・NMOS設定" screen and
# restarts it (or the retry loop picks it up on its own).
systemctl enable --now multiviewer-nmos.service
# multiviewer-ptp.service reads network.media_amber.interface from
# config.json at its own startup; same graceful-retry behavior as above if
# it is unset. Step 3a stage 1: this only monitors PTP status, it does not
# start phc2sys or touch the OS system clock (see README.md).
systemctl enable --now multiviewer-ptp.service

echo "==> Done."
echo "WebGUI should now be reachable at http://<1G NIC IP>/mgmt/"
echo "See README.md before changing any NIC's IP address from the WebGUI:"
echo "applying a change reboots the server immediately with no automatic rollback."
