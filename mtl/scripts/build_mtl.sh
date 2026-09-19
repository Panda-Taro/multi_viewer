#!/usr/bin/env bash
# mtl/scripts/build_mtl.sh
# 対応要件: ④-1,④-2,④-3,⑦, 配置要件(初回セットアップ)
#
# Media Transport Library (MTL) を DPDK とともにソースからビルドし、
# RxTxApp サンプルアプリと各種ライブラリ/CLIをインストールする。
# Ubuntu Server 24.04.4 を対象とする。実機以外(本開発サンドボックス等)では
# hugepages/カーネルモジュールの制約により実行できないため、CI的には
# `bash -n` (構文チェック) のみ確認している。
set -euo pipefail

DPDK_VERSION="${DPDK_VERSION:-25.03}"
MTL_VERSION="${MTL_VERSION:-main}"   # 実運用ではタグ (例: v24.09) にピン留め推奨
# 2026-09時点: MTL の main ブランチが要求する libdpdk が >=25.03 に上がったため、
# DPDK_VERSION のデフォルトを 23.11 から 25.03 へ変更した (実機導入時に
# `libdpdk found: NO ... need '>=25.03'` で build.sh が失敗したことに対する修正)。
# MTL は main を追従する floating pin のため、上流の要求バージョンは今後も
# 変わり得る。ビルド失敗時は build/Media-Transport-Library/build/meson-logs/
# meson-log.txt の `Dependency libdpdk found` 行を確認し、必要な DPDK_VERSION を
# 環境変数で上書きすること (例: `sudo DPDK_VERSION=25.07 ./scripts/setup.sh`)。
# より再現性を求める場合は MTL_VERSION を具体的なタグに固定することを推奨する。
PREFIX="${PREFIX:-/usr/local}"
BUILD_DIR="${BUILD_DIR:-/opt/multiviewer/build}"

log() { echo "[build_mtl] $*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "root権限で実行してください (sudo $0)" >&2
    exit 1
  fi
}

install_deps() {
  log "依存パッケージをインストール"
  apt-get update -y
  apt-get install -y \
    build-essential meson ninja-build pkg-config cmake \
    libnuma-dev python3-pyelftools python3-pip \
    libjson-c-dev libpcap-dev libssl-dev \
    libsdl2-dev libsdl2-ttf-dev \
    systemtap-sdt-dev libgtest-dev libgmock-dev \
    git wget ca-certificates
}

build_dpdk() {
  log "DPDK ${DPDK_VERSION} を取得・ビルド"
  mkdir -p "${BUILD_DIR}"
  cd "${BUILD_DIR}"
  if [[ ! -d dpdk ]]; then
    git clone --branch "v${DPDK_VERSION}" --depth 1 https://github.com/DPDK/dpdk.git
  fi
  cd dpdk
  # 既存クローンが要求バージョンと異なる場合(DPDK_VERSION変更による再実行等)は
  # 対象タグへ切り替える。浅いclone(--depth 1)のため一旦フェッチし直す。
  current_tag="$(git describe --tags --exact-match 2>/dev/null || true)"
  if [[ "${current_tag}" != "v${DPDK_VERSION}" ]]; then
    log "既存のdpdkクローン(${current_tag:-unknown})がv${DPDK_VERSION}と異なるため取得し直します"
    git fetch --depth 1 origin "tag" "v${DPDK_VERSION}"
    git checkout "v${DPDK_VERSION}"
    git clean -fdx
  fi
  # MTLが要求するDPDKパッチ (MTLリポジトリ patches/dpdk/ 配下) を適用する。
  if [[ -d "${BUILD_DIR}/Media-Transport-Library/patches/dpdk/${DPDK_VERSION}" ]]; then
    for p in "${BUILD_DIR}/Media-Transport-Library/patches/dpdk/${DPDK_VERSION}"/*.patch; do
      [[ -e "$p" ]] || continue
      git apply "$p" || log "パッチ適用スキップ(既に適用済みの可能性): $p"
    done
  fi
  meson setup build --prefix="${PREFIX}"
  ninja -C build
  ninja -C build install
  ldconfig
}

build_mtl() {
  log "Media Transport Library (${MTL_VERSION}) を取得・ビルド"
  cd "${BUILD_DIR}"
  if [[ ! -d Media-Transport-Library ]]; then
    git clone https://github.com/OpenVisualCloud/Media-Transport-Library.git
  fi
  cd Media-Transport-Library
  git fetch --all --tags
  git checkout "${MTL_VERSION}"
  ./build.sh
  meson install -C build || true
  ldconfig
}

install_af_xdp_tools() {
  log "AF_XDP (libxdp/libbpf) 関連ツールを確認"
  apt-get install -y libxdp-dev libbpf-dev linux-tools-common linux-tools-generic || true
}

main() {
  require_root
  install_deps
  install_af_xdp_tools
  build_dpdk
  build_mtl
  log "MTLビルド完了。RxTxAppは ${BUILD_DIR}/Media-Transport-Library/build/app/RxTxApp"
  log "systemdユニットからは mtl/scripts/start_rx.sh 経由で起動される"
}

main "$@"
