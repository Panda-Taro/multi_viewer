#!/usr/bin/env bash
# mtl/scripts/ptp_status.sh
# 対応要件: ④-3 (PTP同期状態の取得、Amber/Blue切替のログ化)
#
# MTLはPTPクライアント状態をログ (journalctl -u multiviewer-mtl-rx) に
# 出力する。本スクリプトはそのログから直近のPTPロック状態/使用中ソース
# (Amber=NIC A / Blue=NIC B) を抽出し、JSON1行で標準出力する。
# WebGUIバックエンド (webgui/app/routers/dashboard.py) から定期的に呼ばれる想定。
#
# ログの実フォーマットはMTLバージョン依存のため、grep パターンは実機導入時に
# 調整が必要 (判断メモ: NOTES.md参照)。
set -euo pipefail

UNIT="${MTL_RX_UNIT:-multiviewer-mtl-rx.service}"
LOOKBACK="${PTP_LOOKBACK:-2 min ago}"

last_line=$(journalctl -u "${UNIT}" --since "${LOOKBACK}" 2>/dev/null | grep -i "ptp" | tail -n 1 || true)

if [[ -z "${last_line}" ]]; then
  echo '{"locked": false, "source": "unknown", "raw": ""}'
  exit 0
fi

source="unknown"
locked="false"

if echo "${last_line}" | grep -qi "amber"; then
  source="amber"
elif echo "${last_line}" | grep -qi "blue"; then
  source="blue"
fi

if echo "${last_line}" | grep -qi "lock"; then
  locked="true"
fi

printf '{"locked": %s, "source": "%s", "raw": %q}\n' "${locked}" "${source}" "${last_line}"
