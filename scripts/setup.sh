#!/usr/bin/env bash
# scripts/setup.sh
# 対応要件: 配置要件(初回セットアップスクリプト), ⑦(異なるハードウェアへの
# 再展開はGUI設定のみで済むようにする)
#
# 依存パッケージ導入・全コンポーネントのビルド・hugepages設定・systemd
# ユニットの導入/有効化までを行う。Ubuntu Server 24.04.4を対象とする。
#
# 実行後は `/mgmt/` (http://<1G NIC IP>/mgmt/) にアクセスし、NIC IP・
# Receiver設定・NMOS設定等をGUIから行うことで異なるハードウェアへの
# 再展開が完結する設計 (本スクリプト自体はハードウェア差異を吸収しない)。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/multiviewer}"
CONFIG_DIR="/etc/multiviewer"
LOG_DIR="/var/log/multiviewer"
SERVICE_USER="${SERVICE_USER:-multiviewer}"

log() { echo "[setup] $*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "root権限で実行してください (sudo $0)" >&2
    exit 1
  fi
}

check_os() {
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
      log "警告: Ubuntu Server 24.04.4を対象としています (検出: ${PRETTY_NAME:-unknown})。続行しますが動作保証外です。"
    fi
  fi
}

create_service_user() {
  if ! id "${SERVICE_USER}" &>/dev/null; then
    log "サービス実行用ユーザ ${SERVICE_USER} を作成"
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
  fi
}

install_python_stack() {
  log "Pythonスタック (webgui/bridge) をセットアップ"
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip
  python3 -m venv "${INSTALL_DIR}/venv"
  "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
  "${INSTALL_DIR}/venv/bin/pip" install -r "${REPO_ROOT}/webgui/requirements.txt"
  "${INSTALL_DIR}/venv/bin/pip" install fastapi uvicorn pydantic
}

sync_repo() {
  log "リポジトリを ${INSTALL_DIR} へ配置"
  mkdir -p "${INSTALL_DIR}"
  rsync -a --exclude ".git" --exclude "**/__pycache__" --exclude "**/tests" \
    "${REPO_ROOT}/" "${INSTALL_DIR}/"
}

setup_directories() {
  log "設定/ログディレクトリを作成"
  mkdir -p "${CONFIG_DIR}/mtl" "${CONFIG_DIR}/mediamtx" "${CONFIG_DIR}/nmos" "${LOG_DIR}"
  [[ -f "${CONFIG_DIR}/mtl/rx_config.json" ]] || cp "${REPO_ROOT}/mtl/config/rx_config.template.json" "${CONFIG_DIR}/mtl/rx_config.json"
  cp "${REPO_ROOT}/mediamtx/mediamtx.yml" "${CONFIG_DIR}/mediamtx/mediamtx.yml"
  cp "${REPO_ROOT}/nmos/config/node_config.json" "${CONFIG_DIR}/nmos/node_config.json"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}"
}

build_components() {
  log "MTL/DPDKをビルド (時間がかかります)"
  bash "${REPO_ROOT}/mtl/scripts/build_mtl.sh"

  log "FFmpeg(MTL連携プラグイン組み込み)をビルド (時間がかかります)"
  bash "${REPO_ROOT}/mtl/scripts/build_ffmpeg.sh"

  log "nmos-cppをビルド"
  bash "${REPO_ROOT}/nmos/scripts/build_nmos_cpp.sh"

  log "MediaMTXをダウンロード"
  bash "${REPO_ROOT}/scripts/install_mediamtx.sh"

  log "hugepagesを設定"
  bash "${REPO_ROOT}/mtl/scripts/setup_hugepages.sh"
}

install_systemd_units() {
  log "systemdユニットを導入"
  for unit in "${REPO_ROOT}"/systemd/*.service "${REPO_ROOT}"/systemd/*.timer; do
    [[ -e "${unit}" ]] || continue
    cp "${unit}" "/etc/systemd/system/$(basename "${unit}")"
  done
  systemctl daemon-reload

  for svc in multiviewer-hugepages multiviewer-mtl-rx multiviewer-compositor \
             multiviewer-mediamtx multiviewer-nmos-node multiviewer-bridge \
             multiviewer-webgui; do
    systemctl enable --now "${svc}.service"
  done
  systemctl enable --now multiviewer-nic-rollback.timer
}

main() {
  require_root
  check_os
  create_service_user
  sync_repo
  install_python_stack
  setup_directories
  build_components
  install_systemd_units

  log "セットアップ完了。ブラウザで http://<1G NICのIP>/mgmt/ にアクセスして設定してください。"
}

main "$@"
