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
# 各オプション名 (-p_port, -p_sip, -p_rx_ip, -udp_port, -payload_type 等) は
# MTL公式ドキュメント記載のffmpeg_pluginオプション名に基づくが、プラグインの
# バージョンによって異なる可能性があるため実機導入時に要確認 (NOTES.md参照)。
set -euo pipefail

RX_CONFIG="${MTL_RX_CONFIG:-/etc/multiviewer/mtl/rx_config.json}"
MEDIAMTX_RTSP_URL="${MEDIAMTX_RTSP_URL:-rtsp://127.0.0.1:8554/monitor01}"
FFMPEG_BIN="${FFMPEG_BIN:-ffmpeg}"
ZMQ_BIND="${ZMQ_BIND:-tcp://127.0.0.1:5555}"

if ! command -v "${FFMPEG_BIN}" >/dev/null 2>&1; then
  echo "[compose] ffmpeg が見つかりません。MTL同梱パッチ適用済みFFmpegをビルドしてください" >&2
  exit 1
fi

PYTHON_BIN="python3"
command -v python3 >/dev/null 2>&1 || PYTHON_BIN="python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FILTER_COMPLEX=$(MV_COMPOSITOR_DIR="${SCRIPT_DIR}" MV_ZMQ_BIND="${ZMQ_BIND}" "${PYTHON_BIN}" - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ["MV_COMPOSITOR_DIR"])
from layout import DisplayModeController
print(DisplayModeController().build_filter_complex(zmq_bind_addr=os.environ["MV_ZMQ_BIND"]))
PYEOF
)

echo "[compose] filter_complex を生成しました"

# NOTE: 実際の入力デマルチプレクサ指定はrxctl.pyが生成したRX_CONFIGの内容
# (source_ip/mcast/port/payload_type) を反映して動的に組み立てる必要があるが、
# ここでは4系統分のプレースホルダとして -i オプションの型のみ示す。
exec "${FFMPEG_BIN}" \
  -f mtl_st20p -p_port "0000:af:00.0" -p_sip "AMBER_IP" -p_rx_ip "VIDEO1_MCAST" -udp_port 20000 -payload_type 112 -i "video1" \
  -f mtl_st20p -p_port "0000:af:00.0" -p_sip "AMBER_IP" -p_rx_ip "VIDEO2_MCAST" -udp_port 20001 -payload_type 112 -i "video2" \
  -f mtl_st20p -p_port "0000:af:00.0" -p_sip "AMBER_IP" -p_rx_ip "VIDEO3_MCAST" -udp_port 20002 -payload_type 112 -i "video3" \
  -f mtl_st20p -p_port "0000:af:00.0" -p_sip "AMBER_IP" -p_rx_ip "VIDEO4_MCAST" -udp_port 20003 -payload_type 112 -i "video4" \
  -f mtl_st30p -p_port "0000:af:00.0" -p_sip "AMBER_IP" -p_rx_ip "AUDIO_MCAST" -udp_port 20100 -payload_type 111 -i "audio1" \
  -filter_complex "${FILTER_COMPLEX}" \
  -map "[vout]" -map 4:a \
  -c:v libx264 -preset veryfast -tune zerolatency -g 60 \
  -c:a libopus -ac 2 -ar 48000 \
  -f rtsp -rtsp_transport tcp \
  "${MEDIAMTX_RTSP_URL}"
