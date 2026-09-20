#!/usr/bin/env bash
# mtl/scripts/start_rx.sh
# 対応要件: ④-1,④-2,④-3
#
# systemd (systemd/multiviewer-mtl-rx.service) から呼び出され、
# rxctl.py が生成した MTL RX 設定 JSON を用いて RxTxApp (MTLサンプルRXアプリ)
# を起動する。設定ファイルパスは環境変数 MTL_RX_CONFIG で上書き可能。
set -euo pipefail

MTL_RX_CONFIG="${MTL_RX_CONFIG:-/etc/multiviewer/mtl/rx_config.json}"
# RxTxAppはtests/tools/RxTxApp配下の独立したmesonプロジェクトとしてビルドされ、
# `ninja install`によりシステム全体(デフォルトprefix=/usr/local)へインストール
# される設計 (MTL本体のbuild.sh参照)。/opt/multiviewer/build/...配下には
# 残らないため、`which`でも見つかる/usr/local/bin/RxTxAppをデフォルトとする。
MTL_BIN="${MTL_BIN:-/usr/local/bin/RxTxApp}"
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

# 2026-09実機ビルドでの判明事項: RxTxApp (tests/tools/RxTxApp/src/args.c) には
# `--ptp_domain` および `--rx_only` というCLIオプションは存在しない
# (getopt_longの選択肢一覧に無く、渡すと起動直後にエラー終了する)。
# RxTxAppはRX/TX兼用ツールで、JSON設定内にtx_sessionsを含めなければRXのみ
# 動作する。PTPドメインの設定方法はソース上"domain"という文字列自体が
# tests/tools/RxTxApp配下に見当たらず未確認 (要実機検証、docs/verification.md参照)。
# PTP_DOMAIN環境変数は将来の拡張のためにrx_config.jsonの"ptp.domain"へ
# rxctl.py側で反映される設計だが、RxTxApp側で実際に読まれるかは未検証。
echo "[start_rx] MTL RXを起動: config=${MTL_RX_CONFIG} (ptp_domain=${PTP_DOMAIN}はrx_config.json内のptp.domainとして反映される想定、RxTxApp側での実際の読み取りは未検証)"
exec "${MTL_BIN}" \
  --config_file "${MTL_RX_CONFIG}"
