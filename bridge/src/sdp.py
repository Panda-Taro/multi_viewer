"""bridge/src/sdp.py

対応要件: ④-7, ⑥ (SDPからフォーマットを導出)

NMOS IS-05 activateで渡されるSender SDP (RFC4566 + RFC4175(ST2110-20) /
ST2110-30 拡張パラメータ) をパースし、MTL RX設定へ適用可能な構造体に変換する。
ネットワーク・MTLに一切依存しない純粋な文字列処理のため、pytestで完全に
テストできる。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class SdpParseError(ValueError):
    pass


@dataclass
class ParsedSdp:
    media_type: str  # "video" | "audio"
    source_ip: str = ""
    multicast_group: str = ""
    port: int = 0
    payload_type: int = 0
    # video専用
    video_format: Optional[str] = None   # MTL enum (例 "i1080p59")
    pg_format: Optional[str] = None       # 例 "YUV_422_10bit"
    width: Optional[int] = None
    height: Optional[int] = None
    interlaced: bool = False
    fps: Optional[float] = None
    depth: Optional[int] = None
    # audio専用
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    packet_time_ms: Optional[float] = None


_MTL_VIDEO_FORMAT_TABLE = {
    # (width, height, interlaced, round(fps,2)) -> MTLビデオフォーマットenum
    (1920, 1080, True, 59.94): "i1080p59",
    (1920, 1080, False, 59.94): "p1080p59",
    (1920, 1080, False, 50.0): "p1080p50",
    (3840, 2160, False, 59.94): "p2160p59",
    (1280, 720, False, 59.94): "p720p59",
}


def _to_mtl_video_format(width: int, height: int, interlaced: bool, fps: float) -> str:
    key = (width, height, interlaced, round(fps, 2))
    if key in _MTL_VIDEO_FORMAT_TABLE:
        return _MTL_VIDEO_FORMAT_TABLE[key]
    # テーブル未登録の組み合わせでも合成的にフォーマット名を生成しておく
    # (④-1: 「その他の解像度・走査方式もSDPで指定されれば許容する」要件に対応)
    scan = "i" if interlaced else "p"
    return f"{scan}{height}p{int(round(fps))}"


def _pg_format_from_sampling_depth(sampling: str, depth: int) -> str:
    sampling_norm = sampling.replace("YCbCr-", "").replace(":", "")
    return f"YUV_{sampling_norm}_{depth}bit"


def _parse_fmtp_params(fmtp_value: str) -> dict:
    params = {}
    for kv in fmtp_value.split(";"):
        kv = kv.strip()
        if not kv:
            continue
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k.strip()] = v.strip()
        else:
            # "interlace" のような値なしフラグ
            params[kv] = True
    return params


def _parse_exactframerate(value: str) -> float:
    if "/" in value:
        num, den = value.split("/")
        return float(num) / float(den)
    return float(value)


def parse_sdp(sdp_text: str) -> ParsedSdp:
    """SDPテキスト全体をパースし ParsedSdp を返す。

    対応する行:
      c=IN IP4 <group>/<ttl>          -> multicast_group
      o=- ... IN IP4 <source_ip>      -> source_ip (フォールバック)
      a=source-filter: incl IN IP4 <group> <source_ip> -> source_ip優先
      m=video <port> RTP/AVP <pt>     -> media_type=video, port, payload_type
      m=audio <port> RTP/AVP <pt>     -> media_type=audio, port, payload_type
      a=rtpmap:<pt> raw/90000         -> video (RFC4175)
      a=rtpmap:<pt> L24/<rate>/<ch>   -> audio (ST2110-30 PCM)
      a=fmtp:<pt> sampling=...;width=...;height=...;interlace;exactframerate=...;depth=...
      a=ptime:<ms>                    -> audio packet time
    """
    if not sdp_text or "m=" not in sdp_text:
        raise SdpParseError("SDPにメディア行(m=)が存在しません")

    lines = [ln.strip() for ln in sdp_text.strip().splitlines() if ln.strip()]

    media_type = None
    port = 0
    payload_type = 0
    multicast_group = ""
    source_ip = ""
    fmtp_params: dict = {}
    audio_rate = None
    audio_channels = None
    ptime = None

    for line in lines:
        if line.startswith("o="):
            parts = line.split()
            if len(parts) >= 6 and parts[4] == "IP4":
                source_ip = parts[5]
        elif line.startswith("c=IN IP4"):
            addr = line.split()[2]
            multicast_group = addr.split("/")[0]
        elif line.startswith("m=video") or line.startswith("m=audio"):
            parts = line.split()
            media_type = "video" if line.startswith("m=video") else "audio"
            port = int(parts[1])
            payload_type = int(parts[3])
        elif line.startswith("a=rtpmap:"):
            rest = line[len("a=rtpmap:"):]
            _, encoding = rest.split(" ", 1)
            if encoding.upper().startswith("L24") or encoding.upper().startswith("L16"):
                enc_parts = encoding.split("/")
                if len(enc_parts) >= 2:
                    audio_rate = int(enc_parts[1])
                if len(enc_parts) >= 3:
                    audio_channels = int(enc_parts[2])
        elif line.startswith("a=fmtp:"):
            _, value = line.split(" ", 1)
            fmtp_params = _parse_fmtp_params(value)
        elif line.startswith("a=ptime:"):
            ptime = float(line.split(":", 1)[1])
        elif line.startswith("a=source-filter:"):
            # 例: a=source-filter: incl IN IP4 239.1.1.10 192.168.1.10
            parts = line.split()
            if len(parts) >= 6:
                source_ip = parts[-1]

    if media_type is None:
        raise SdpParseError("m=video / m=audio 行が見つかりません")

    parsed = ParsedSdp(
        media_type=media_type,
        source_ip=source_ip,
        multicast_group=multicast_group,
        port=port,
        payload_type=payload_type,
    )

    if media_type == "video":
        width = int(fmtp_params.get("width", 1920))
        height = int(fmtp_params.get("height", 1080))
        interlaced = bool(fmtp_params.get("interlace", False))
        fps = 59.94
        if "exactframerate" in fmtp_params:
            fps = _parse_exactframerate(fmtp_params["exactframerate"])
        depth = int(fmtp_params.get("depth", 10))
        sampling = fmtp_params.get("sampling", "YCbCr-4:2:2")

        parsed.width = width
        parsed.height = height
        parsed.interlaced = interlaced
        parsed.fps = fps
        parsed.depth = depth
        parsed.video_format = _to_mtl_video_format(width, height, interlaced, fps)
        parsed.pg_format = _pg_format_from_sampling_depth(sampling, depth)
    else:
        parsed.sample_rate = audio_rate or 48000
        parsed.channels = audio_channels or 2
        parsed.packet_time_ms = ptime if ptime is not None else 1.0

    return parsed
