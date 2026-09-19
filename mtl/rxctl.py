"""mtl/rxctl.py

対応要件: ④-1, ④-2, ④-7, ⑦

MTL RX 設定 (JSON) を組み立てる薄い制御層。実際の MTL プロセス起動は
`scripts/start_rx.sh` (systemd 経由) が担当し、本モジュールは:

  1. 4本の映像Receiver + 1本の音声Receiverの設定をPythonデータクラスで保持
  2. NMOS SDP (bridge/src/sdp.py が解析した結果) を各Receiverに適用
  3. 4映像ストリームのフォーマット統一性チェック (④-1「同一と仮定」の破れを検知)
  4. MTL RX設定JSONへのシリアライズ

を行う。ハードウェア/DPDK/AF_XDPには一切依存しないため、本開発環境でも
pytestで完全にテスト可能である。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


DEFAULT_VIDEO_FORMAT = "i1080p59"  # 1920x1080 59.94i 相当のMTL enum
DEFAULT_PG_FORMAT = "YUV_422_10bit"  # 4:2:2 10bit


class ConfigValidationError(ValueError):
    """RX設定の妥当性検証に失敗した場合に送出する。"""


@dataclass
class VideoReceiverConfig:
    """1系統分の映像Receiver設定 (④-1)。"""

    index: int  # 0-3
    source_ip: str = ""
    multicast_group_amber: str = ""
    multicast_group_blue: str = ""
    port: int = 0
    payload_type: int = 112
    video_format: str = DEFAULT_VIDEO_FORMAT
    pg_format: str = DEFAULT_PG_FORMAT

    def is_configured(self) -> bool:
        return bool(self.multicast_group_amber and self.port)


@dataclass
class AudioReceiverConfig:
    """音声Receiver設定 (④-2)。ch1/2のみ使用。"""

    source_ip: str = ""
    multicast_group_amber: str = ""
    multicast_group_blue: str = ""
    port: int = 0
    payload_type: int = 111
    sample_rate: int = 48000
    packet_time_ms: float = 1.0  # 1ms既定、SDPで125usが指定される場合あり
    channels: int = 2  # ch1/2固定。3以上が来ても常に2に丸める (要件④-2)

    def is_configured(self) -> bool:
        return bool(self.multicast_group_amber and self.port)


@dataclass
class PtpConfig:
    domain: int = 24  # 要件④-8: PTPドメイン番号はGUI設定可能


@dataclass
class RxSystemConfig:
    """4映像+1音声+PTPをまとめたシステム全体のRX設定 (④-1〜④-3)。"""

    amber_iface: str = "amber0"
    blue_iface: str = "blue0"
    amber_ip: str = ""
    blue_ip: str = ""
    ptp: PtpConfig = field(default_factory=PtpConfig)
    videos: list[VideoReceiverConfig] = field(
        default_factory=lambda: [VideoReceiverConfig(index=i) for i in range(4)]
    )
    audio: AudioReceiverConfig = field(default_factory=AudioReceiverConfig)

    def __post_init__(self):
        if len(self.videos) != 4:
            raise ConfigValidationError("映像Receiverは常に4系統でなければならない (④-1)")

    def configured_video_formats(self) -> list[tuple[str, str]]:
        """設定済みの映像Receiverの (video_format, pg_format) 一覧を返す。"""
        return [
            (v.video_format, v.pg_format) for v in self.videos if v.is_configured()
        ]

    def check_format_uniformity(self) -> Optional[str]:
        """④-1: 4系統のフォーマットが不統一なら警告メッセージを返す (Noneなら統一)。

        「善意の前提」に基づき自動補正はせず、アラームメッセージの生成のみ行う。
        実際にOSDへ焼き込むのは compositor 側の責務 (compositor/overlay.py)。
        """
        formats = self.configured_video_formats()
        if len(formats) <= 1:
            return None
        if len(set(formats)) > 1:
            return "映像フォーマットが4系統で非統一です"
        return None

    def to_mtl_json(self) -> dict:
        """MTL RX設定JSON (app/etc/*.json 準拠スキーマ) を生成する。"""
        rx_sessions = []
        for v in self.videos:
            if not v.is_configured():
                continue
            rx_sessions.append(
                {
                    "dip": [v.multicast_group_amber, v.multicast_group_blue],
                    "interface": [0, 1],
                    "video": [
                        {
                            "udp_port": v.port,
                            "payload_type": v.payload_type,
                            "video_format": v.video_format,
                            "pg_format": v.pg_format,
                            "st2022_7_redundant": bool(v.multicast_group_blue),
                        }
                    ],
                }
            )

        if self.audio.is_configured():
            rx_sessions.append(
                {
                    "dip": [
                        self.audio.multicast_group_amber,
                        self.audio.multicast_group_blue,
                    ],
                    "interface": [0, 1],
                    "audio": [
                        {
                            "udp_port": self.audio.port,
                            "payload_type": self.audio.payload_type,
                            "audio_format": "PCM24",
                            "audio_channel": ["U02"],
                            "audio_sampling": f"{self.audio.sample_rate // 1000}kHz",
                            "audio_ptime": f"{self.audio.packet_time_ms}ms",
                            "st2022_7_redundant": bool(self.audio.multicast_group_blue),
                        }
                    ],
                }
            )

        return {
            "interfaces": [
                {"name": self.amber_iface, "ip": self.amber_ip},
                {"name": self.blue_iface, "ip": self.blue_ip},
            ],
            "ptp": {"domain": self.ptp.domain, "priority_interface": 0},
            "rx_sessions": rx_sessions,
        }

    def apply_sdp(self, receiver_kind: str, index: int, sdp) -> None:
        """bridge から呼ばれる: NMOS SDPの内容をReceiver設定へ適用する (④-7)。

        `sdp` は bridge.src.sdp.ParsedSdp を想定 (循環import回避のためduck-typing)。
        """
        if receiver_kind == "video":
            if not (0 <= index < 4):
                raise ConfigValidationError(f"映像Receiver index範囲外: {index}")
            target = self.videos[index]
            target.source_ip = sdp.source_ip
            target.multicast_group_amber = sdp.multicast_group
            target.port = sdp.port
            target.payload_type = sdp.payload_type
            if sdp.video_format:
                target.video_format = sdp.video_format
            if sdp.pg_format:
                target.pg_format = sdp.pg_format
        elif receiver_kind == "audio":
            self.audio.source_ip = sdp.source_ip
            self.audio.multicast_group_amber = sdp.multicast_group
            self.audio.port = sdp.port
            self.audio.payload_type = sdp.payload_type
            if sdp.sample_rate:
                self.audio.sample_rate = sdp.sample_rate
            if sdp.packet_time_ms:
                self.audio.packet_time_ms = sdp.packet_time_ms
        else:
            raise ConfigValidationError(f"不明なreceiver_kind: {receiver_kind}")

    def as_dict(self) -> dict:
        return asdict(self)
