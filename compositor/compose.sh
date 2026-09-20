#!/usr/bin/env bash
# compositor/compose.sh
# 対応要件: ④-4, ④-5, ④-1
#
# MTLのFFmpeg連携プラグイン (mtl_st20p: 映像デマルチプレクサ, mtl_st30p: 音声
# デマルチプレクサ。https://github.com/OpenVisualCloud/Media-Transport-Library
# ecosystem/ffmpeg_plugin/ を参照) を用いてMTLがST2022-7冗長マージ済みの4映像
# +1音声を取り込み、2x2合成/シングル切替可能なfilter_complexを適用して
# MediaMTXへRTSPでpushする。
#
# 【2026-09 実機ビルドで判明した修正】実際のffmpeg起動引数の組み立て
# (RX設定JSONからの実IPアドレス反映、filter_complex生成)はcompose.pyに
# 委譲した(bashでの複雑な配列/クォート処理を避けるため)。
set -euo pipefail

FFMPEG_BIN="${FFMPEG_BIN:-ffmpeg}"

if ! command -v "${FFMPEG_BIN}" >/dev/null 2>&1; then
  echo "[compose] ffmpeg が見つかりません。mtl/scripts/build_ffmpeg.sh をビルドしてください" >&2
  exit 1
fi

PYTHON_BIN="python3"
command -v python3 >/dev/null 2>&1 || PYTHON_BIN="python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/compose.py"
