#!/usr/bin/env bash
# mtl/scripts/start_rx.sh
# 対応要件: ④-1,④-2,④-3
#
# systemd (systemd/multiviewer-mtl-rx.service) から呼び出され、
# rxctl.py が生成した MTL RX 設定 JSON を用いて RxTxApp (MTLサンプルRXアプリ)
# を起動する。設定ファイルパスは環境変数 MTL_RX_CONFIG で上書き可能。
set -euo pipefail

MTL_RX_CONFIG="${MTL_RX_CONFIG:-/etc/multiviewer/mtl/rx_config.json}"
MTL_BIN="${MTL_BIN:-/opt/multiviewer/build/Media-Transport-Library/build/app/RxTxApp}"
PTP_DOMAIN="${PTP_DOMAIN:-24}"

if [[ ! -x "${MTL_BIN}" ]]; then
  echo "[start_rx] MTL RxTxApp が見つかりません: ${MTL_BIN}" >&2
  echo "[start_rx] mtl/scripts/build_mtl.sh を先に実行してください" >&2
  exit 1
fi

if [[ ! -f "${MTL_RX_CONFIG}" ]]; then
  echo "[start_rx] RX設定ファイルが見つかりません: ${MTL_RX_CONFIG}" >&2
  echo "[start_rx] webgui/bridge が初回起動時にデフォルト設定を生成する想定です" >&2
  exit 1
fi

echo "[start_rx] MTL RXを起動: config=${MTL_RX_CONFIG} ptp_domain=${PTP_DOMAIN}"
exec "${MTL_BIN}" \
  --config_file "${MTL_RX_CONFIG}" \
  --ptp_domain "${PTP_DOMAIN}" \
  --rx_only
