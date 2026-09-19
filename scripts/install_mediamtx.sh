#!/usr/bin/env bash
# scripts/install_mediamtx.sh
# 対応要件: ④-6, 配置要件(初回セットアップ)
#
# MediaMTX (Go製シングルバイナリ) の最新安定版をダウンロードしてインストールする。
set -euo pipefail

MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-v1.9.3}"
INSTALL_DIR="${INSTALL_DIR:-/opt/multiviewer}"
ARCH="$(uname -m)"

case "${ARCH}" in
  x86_64) MTX_ARCH="amd64" ;;
  aarch64) MTX_ARCH="arm64" ;;
  *) echo "未対応アーキテクチャ: ${ARCH}" >&2; exit 1 ;;
esac

log() { echo "[install_mediamtx] $*"; }

mkdir -p "${INSTALL_DIR}/mediamtx"
cd "${INSTALL_DIR}/mediamtx"

URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${MTX_ARCH}.tar.gz"
log "ダウンロード: ${URL}"
wget -q -O mediamtx.tar.gz "${URL}"
tar xzf mediamtx.tar.gz
chmod +x mediamtx
rm -f mediamtx.tar.gz

log "インストール完了: ${INSTALL_DIR}/mediamtx/mediamtx (${MEDIAMTX_VERSION})"
