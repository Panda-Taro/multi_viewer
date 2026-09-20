#!/usr/bin/env bash
# mtl/scripts/setup_hugepages.sh
# 対応要件: ⑦(AF_XDP/DPDK基盤), 配置要件(初回セットアップスクリプト)
#
# DPDK/AF_XDP が要求する hugepages を設定する。MTLはRXバッファに2MB hugepages を
# 使用する運用が一般的なため、デフォルトで2MBページを4GB分確保する。
# 実機のRAM容量に応じて HUGEPAGES_2MB を調整すること。
set -euo pipefail

HUGEPAGES_2MB="${HUGEPAGES_2MB:-2048}"   # 2048 x 2MB = 4GB
HUGE_MOUNT="${HUGE_MOUNT:-/mnt/huge}"

log() { echo "[setup_hugepages] $*"; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "root権限で実行してください (sudo $0)" >&2
  exit 1
fi

log "2MB hugepages を ${HUGEPAGES_2MB} ページ確保"
echo "${HUGEPAGES_2MB}" > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

mkdir -p "${HUGE_MOUNT}"
if ! mountpoint -q "${HUGE_MOUNT}"; then
  mount -t hugetlbfs nodev "${HUGE_MOUNT}"
fi

# 再起動後も設定が残るよう /etc/sysctl.d と /etc/fstab に恒久化する。
cat > /etc/sysctl.d/99-multiviewer-hugepages.conf <<EOF
vm.nr_hugepages=${HUGEPAGES_2MB}
EOF

if ! grep -q "${HUGE_MOUNT}" /etc/fstab; then
  echo "nodev ${HUGE_MOUNT} hugetlbfs defaults 0 0" >> /etc/fstab
fi

log "現在のhugepages状態:"
grep -i huge /proc/meminfo || true
