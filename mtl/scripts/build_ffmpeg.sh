#!/usr/bin/env bash
# mtl/scripts/build_ffmpeg.sh
# 対応要件: ④-4,④-5,⑥-4-3,⑥-4-4, 配置要件(初回セットアップ)
#
# FFmpeg に MTL 連携プラグイン (mtl_st20p: 映像, mtl_st30p: 音声。
# https://github.com/OpenVisualCloud/Media-Transport-Library
# ecosystem/ffmpeg_plugin/ 参照) を組み込んでビルドする。
#
# 【2026-09 追記】実機セットアップで判明: setup.sh の build_components() には
# 元々このFFmpegビルド手順が欠落しており、multiviewer-compositor.service が
# 「ffmpeg が見つかりません」で起動に失敗していた。本スクリプトはMTL公式の
# ecosystem/ffmpeg_plugin/build.sh のロジック(openh264ビルド → FFmpeg取得 →
# mtl_*.cをlibavdevice/へコピー → バージョン別パッチ適用 → --enable-mtl で
# configure)を土台にしつつ、本システムの要件⑥-4-3(映像コーデックH.264)・
# ⑥-4-4(音声コーデックOpus)を満たすため --enable-gpl --enable-libx264
# --enable-libopus を追加で有効化した独自ラッパーである
# (公式スクリプトは--enable-libopenh264のみを想定しており、libx264/libopusの
# 有効化オプションを持たないため、直接流用せず本スクリプトとして書き起こした)。
set -euo pipefail

BUILD_DIR="${BUILD_DIR:-/opt/multiviewer/build}"
MTL_SRC_DIR="${MTL_SRC_DIR:-${BUILD_DIR}/Media-Transport-Library}"
PREFIX="${PREFIX:-/usr/local}"

log() { echo "[build_ffmpeg] $*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "root権限で実行してください (sudo $0)" >&2
    exit 1
  fi
}

require_mtl_source() {
  if [[ ! -d "${MTL_SRC_DIR}/ecosystem/ffmpeg_plugin" ]]; then
    echo "[build_ffmpeg] ${MTL_SRC_DIR} が見つかりません。先に mtl/scripts/build_mtl.sh を実行してください" >&2
    exit 1
  fi
}

install_deps() {
  log "依存パッケージをインストール (FFmpeg本体 + libx264/libopus)"
  apt-get update -y
  apt-get install -y \
    wget unzip patch pkg-config \
    nasm yasm \
    libx264-dev libopus-dev libzmq3-dev \
    libfreetype6-dev libfontconfig1-dev libharfbuzz-dev \
    build-essential
}

read_ffmpeg_version() {
  # MTL本体同梱のversions.envに記載されたFFmpegバージョン(推奨組み合わせ)を使う。
  if [[ -f "${MTL_SRC_DIR}/versions.env" ]]; then
    # shellcheck disable=SC1090
    . "${MTL_SRC_DIR}/versions.env"
  fi
  echo "${FFMPEG_VERSION:-7.0}"
}

build_openh264() {
  if pkg-config --exists openh264 2>/dev/null; then
    log "openh264は導入済み。スキップ"
    return
  fi
  cd "${BUILD_DIR}"
  rm -rf openh264-openh264v2.4.0
  wget -q https://github.com/cisco/openh264/archive/refs/heads/openh264v2.4.0.zip
  unzip -q openh264v2.4.0.zip && rm -f openh264v2.4.0.zip
  cd openh264-openh264v2.4.0
  make -j"$(nproc)"
  make install
  ldconfig
}

build_ffmpeg() {
  local ffmpeg_version
  ffmpeg_version="$(read_ffmpeg_version)"
  local plugin_dir="${MTL_SRC_DIR}/ecosystem/ffmpeg_plugin"

  log "FFmpeg ${ffmpeg_version} を取得しMTLプラグインを組み込みビルド"
  cd "${BUILD_DIR}"
  rm -rf "FFmpeg-release-${ffmpeg_version}"
  wget -q "https://github.com/FFmpeg/FFmpeg/archive/refs/heads/release/${ffmpeg_version}.zip" -O "${ffmpeg_version}.zip"
  unzip -q "${ffmpeg_version}.zip" && rm -f "${ffmpeg_version}.zip"

  cd "FFmpeg-release-${ffmpeg_version}"
  cp -f "${plugin_dir}"/mtl_* ./libavdevice/

  if [[ -d "${plugin_dir}/${ffmpeg_version}" ]]; then
    for patch_file in "${plugin_dir}/${ffmpeg_version}"/*.patch; do
      [[ -e "${patch_file}" ]] || continue
      log "パッチ適用: $(basename "${patch_file}")"
      patch -p1 < "${patch_file}"
    done
  fi

  # --enable-gpl --enable-libx264: 要件⑥-4-3 (WebRTC映像コーデックH.264固定)。
  # --enable-libopus: 要件⑥-4-4 (WebRTC音声コーデックOpus)。
  # --enable-libzmq: compositor/layout.pyが埋め込むzmqフィルタ(④-4、表示モード
  # 切替を1秒以内にFFmpeg再起動無しで反映するための仕組み)に必要。
  # --enable-libfreetype(+fontconfig/harfbuzz): drawtextフィルタ(④-1の
  # フォーマット不統一アラームをOSD焼き込みで表示するために使用)に必要。
  # 実機で `[AVFilterGraph] No such filter: 'drawtext'` により起動失敗する
  # ことを確認して追加した(デフォルトではdrawtextは無効化されている)。
  # --enable-mtl: MTLパッチ適用により追加されるlibavdeviceの入力デバイス
  # (mtl_st20p/mtl_st30p) を有効化する configure フラグ。
  ./configure \
    --prefix="${PREFIX}" \
    --enable-shared --disable-static --enable-pic \
    --enable-gpl \
    --enable-libopenh264 --enable-encoder=libopenh264 \
    --enable-libx264 \
    --enable-libopus \
    --enable-libzmq \
    --enable-libfreetype \
    --enable-libfontconfig \
    --enable-libharfbuzz \
    --enable-mtl
  make -j"$(nproc)"
  make install
  ldconfig
}

main() {
  require_root
  require_mtl_source
  install_deps
  build_openh264
  build_ffmpeg
  log "FFmpegビルド完了 (MTLプラグイン + libx264/libopus組み込み)。'ffmpeg -devices' で mtl_st20p/mtl_st30p が一覧に出ることを確認してください (要実機検証)"
}

main "$@"
