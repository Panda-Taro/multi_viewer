"""compositor/compose.py

対応要件: ④-1,④-2,④-4,④-5, ⑤-2-1(ST2022-7冗長)

compose.sh から呼び出され、rxctl.py が生成した実際のRX設定JSON
(MTL_RX_CONFIG) を読み込んで、MTLのFFmpeg連携プラグイン(mtl_st20p/
mtl_st30p)への実際の接続パラメータ(p_port/p_sip/p_rx_ip/r_port/r_sip/
r_rx_ip/udp_port/payload_type)を組み立て、FFmpegプロセスをexecする。

【2026-09 実機ビルドで判明した修正】当初のcompose.shは
`-p_sip "AMBER_IP" -p_rx_ip "VIDEO1_MCAST"` のような文字列そのものの
プレースホルダをFFmpegへ渡していたため、
`mtl_parse_rx_port, 0 sip VIDEO1_MCAST is not valid ip address` で
起動に失敗していた。実際のRX設定JSON(mtl/rxctl.pyのRxSystemConfig.to_mtl_json()
が生成する構造。フィールド名は "interfaces": [{name, ip}, ...],
"rx_sessions": [{ "ip": [amber_mcast, blue_mcast], "interface": [0, 1],
"video"/"audio": [{ "type": "frame", "start_port": ..., "payload_type": ... }]
}] )を読み込んで実際の値を渡すよう書き直した。

各オプション名(p_port/r_port/p_sip/r_sip/p_rx_ip/r_rx_ip/udp_port/
payload_type)は、MTL公式リポジトリ(OpenVisualCloud/Media-Transport-Library)
の ecosystem/ffmpeg_plugin/mtl_common.h を実際に確認して得たものである
(実機ビルド時にMTLのバージョンが変わっている場合は突き合わせて確認すること)。

video_size/pix_fmt/fpsオプションはMTL公式プラグインのデフォルト値
(1920x1080 / yuv422p10le / 59.94fps。mtl_st20p_rx.c参照)が本システムの
要件⑥のデフォルトフォーマットと一致するため、デフォルト値と異なる
フォーマットがNMOS SDPで指定された場合の動的マッピングは未実装
(要実装、docs/verification.md参照)。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def load_rx_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_video_audio_args(config: dict) -> tuple[list[str], list[str], int]:
    """RX設定JSONから、video1..4/audio1のFFmpeg入力引数を組み立てる。

    戻り値: (ffmpeg入力引数の flat list, 生成されたセッション種別のリスト
    ("video"|"audio"), 音声入力のindex(-map指定用))
    """
    interfaces = config.get("interfaces", [])
    if len(interfaces) < 2:
        raise ValueError("interfacesにAmber/Blueの2エントリが必要です")
    amber, blue = interfaces[0], interfaces[1]

    args: list[str] = []
    kinds: list[str] = []
    video_index = 0
    audio_index = None
    input_index = 0

    for session in config.get("rx_sessions", []):
        mcast = session.get("ip", ["", ""])
        amber_mcast = mcast[0] if len(mcast) > 0 else ""
        blue_mcast = mcast[1] if len(mcast) > 1 else ""

        if "video" in session and session["video"]:
            v = session["video"][0]
            args += [
                "-f", "mtl_st20p",
                "-p_port", amber.get("name", ""),
                "-p_sip", amber.get("ip", ""),
                "-p_rx_ip", amber_mcast,
                "-r_port", blue.get("name", ""),
                "-r_sip", blue.get("ip", ""),
                "-r_rx_ip", blue_mcast,
                "-udp_port", str(v.get("start_port", 0)),
                "-payload_type", str(v.get("payload_type", 112)),
                "-i", f"video{video_index + 1}",
            ]
            kinds.append("video")
            video_index += 1
            input_index += 1
        elif "audio" in session and session["audio"]:
            a = session["audio"][0]
            args += [
                "-f", "mtl_st30p",
                "-p_port", amber.get("name", ""),
                "-p_sip", amber.get("ip", ""),
                "-p_rx_ip", amber_mcast,
                "-r_port", blue.get("name", ""),
                "-r_sip", blue.get("ip", ""),
                "-r_rx_ip", blue_mcast,
                "-udp_port", str(a.get("start_port", 0)),
                "-payload_type", str(a.get("payload_type", 111)),
                "-i", "audio1",
            ]
            kinds.append("audio")
            audio_index = input_index
            input_index += 1

    if kinds.count("video") != 4:
        raise ValueError(f"映像Receiverは4系統必要ですが{kinds.count('video')}系統しか設定されていません (要WebGUI/NMOS設定)")
    if audio_index is None:
        raise ValueError("音声Receiverが設定されていません (要WebGUI/NMOS設定)")

    return args, kinds, audio_index


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from layout import DisplayModeController  # noqa: E402

    rx_config_path = os.environ.get("MTL_RX_CONFIG", "/etc/multiviewer/mtl/rx_config.json")
    mediamtx_url = os.environ.get("MEDIAMTX_RTSP_URL", "rtsp://127.0.0.1:8554/monitor01")
    ffmpeg_bin = os.environ.get("FFMPEG_BIN", "ffmpeg")

    config = load_rx_config(rx_config_path)
    input_args, kinds, audio_index = build_video_audio_args(config)
    filter_complex = DisplayModeController().build_filter_complex()

    argv = [ffmpeg_bin]
    argv += input_args
    argv += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", f"{audio_index}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-g", "60",
        "-c:a", "libopus", "-ac", "2", "-ar", "48000",
        "-f", "rtsp", "-rtsp_transport", "tcp",
        mediamtx_url,
    ]

    print(f"[compose.py] exec: {' '.join(argv)}", file=sys.stderr)
    os.execvp(ffmpeg_bin, argv)
    return 1  # execvpが成功すれば到達しない


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"[compose.py] エラー: {e}", file=sys.stderr)
        sys.exit(1)
