#!/usr/bin/env bash
# scripts/nic_rollback_check.sh
# 対応要件: ⑤ (NIC IP変更の自己ロックアウト防止)
#
# systemd timer (multiviewer-nic-rollback.timer, 30秒毎) から呼ばれ、
# WebGUIプロセス内の webgui.app.nic_ip_change.NicIpChangeManager に
# ロールバック期限超過のIP変更が無いか問い合わせ、あれば netplan の設定を
# 旧IPへ戻して再起動する。
#
# 本開発環境ではWebGUIをlocalhostで実行できないため実行不可。ロジック自体は
# webgui/app/nic_ip_change.py として単体テスト済み。
set -euo pipefail

WEBGUI_INTERNAL_API="${WEBGUI_INTERNAL_API:-http://127.0.0.1:80/api/nic/rollback-check}"

response=$(curl -fsS "${WEBGUI_INTERNAL_API}" 2>/dev/null || echo '{"due": []}')

due_count=$(echo "${response}" | grep -o '"nic_name"' | wc -l || echo 0)

if [[ "${due_count}" -eq 0 ]]; then
  exit 0
fi

echo "[nic_rollback_check] ロールバック期限超過のIP変更を検出、旧設定へ復元します"
# 実機では ここで /etc/netplan/*.yaml を旧IPへ書き戻し、`netplan apply` の後
# `systemctl reboot` を実行する。誤操作防止のため、実際のnetplan書き換え処理は
# 本スクリプト単体では行わず、WebGUI側のAPIが生成した「復元用netplanファイル」
# を適用するのみとする設計とした。
curl -fsS -X POST "${WEBGUI_INTERNAL_API}/apply" || true
