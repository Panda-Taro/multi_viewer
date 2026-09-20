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

# 要件④-8-4-2-1-1-1: 映像フォーマットは「SDP or 59i or 59p」の3択。
# 「SDP」選択時はNMOS SDPが指定する値をそのまま使う(apply_sdpが上書きする)。
# 「59i」「59p」選択時は手動固定であり、以後SDPが来ても上書きされない。
# 未指定(=SDPかつSDPからの指定なし)時のデフォルトは「59i・YCbCr4:2:2 10bit SDR」
# (④-8-4-2-1-1-1-1) であり、これはDEFAULT_VIDEO_FORMAT/DEFAULT_PG_FORMATの
# 初期値と一致する。
VIDEO_FORMAT_MODES = ("sdp", "59i", "59p")
_VIDEO_FORMAT_MODE_TO_MTL = {
    "59i": (DEFAULT_VIDEO_FORMAT, DEFAULT_PG_FORMAT),
    "59p": ("p1080p59", DEFAULT_PG_FORMAT),
}

# 要件④-8-4-2-1-2-1: 音声サンプリングは「SDP or 48kHz」、パケットインターバルは
# 「SDP or 1ms or 0.125ms」の選択式。
AUDIO_SAMPLING_MODES = ("sdp", "48khz")
AUDIO_PTIME_MODES = ("sdp", "1ms", "0.125ms")
_AUDIO_PTIME_MODE_TO_MS = {"1ms": 1.0, "0.125ms": 0.125}


class ConfigValidationError(ValueError):
    """RX設定の妥当性検証に失敗した場合に送出する。"""


@dataclass
class VideoReceiverConfig:
    """1系統分の映像Receiver設定 (④-1、④-8-4-2-1-1-1の有効/無効トグルを含む)。"""

    index: int  # 0-3
    enabled: bool = True  # WebGUIトグル / IS-05 master_enable と一本化される内部状態
    source_ip: str = ""
    multicast_group_amber: str = ""
    multicast_group_blue: str = ""
    port: int = 0
    payload_type: int = 112
    video_format_mode: str = "sdp"  # "sdp" | "59i" | "59p" (④-8-4-2-1-1-1)
    video_format: str = DEFAULT_VIDEO_FORMAT
    pg_format: str = DEFAULT_PG_FORMAT

    def is_configured(self) -> bool:
        return bool(self.multicast_group_amber and self.port)

    def is_active(self) -> bool:
        """無効化中はソースIP等の設定値を保持したままRxセッションには含めない。"""
        return self.enabled and self.is_configured()

    def apply_format_mode(self) -> None:
        """video_format_modeが"59i"/"59p"(手動固定)の場合、実際にMTLへ渡す
        video_format/pg_formatをそのモードの固定値へ揃える。"""
        if self.video_format_mode in _VIDEO_FORMAT_MODE_TO_MTL:
            self.video_format, self.pg_format = _VIDEO_FORMAT_MODE_TO_MTL[self.video_format_mode]


@dataclass
class AudioReceiverConfig:
    """音声Receiver設定 (④-2)。ch1/2のみ使用。"""

    enabled: bool = True  # WebGUIトグル / IS-05 master_enable と一本化される内部状態
    source_ip: str = ""
    multicast_group_amber: str = ""
    multicast_group_blue: str = ""
    port: int = 0
    payload_type: int = 111
    sampling_mode: str = "sdp"  # "sdp" | "48khz" (④-8-4-2-1-2-1)
    sample_rate: int = 48000
    ptime_mode: str = "sdp"  # "sdp" | "1ms" | "0.125ms" (④-8-4-2-1-2-1)
    packet_time_ms: float = 1.0  # 1ms既定、SDPで125usが指定される場合あり
    channels: int = 2  # ch1/2固定。3以上が来ても常に2に丸める (要件④-2)

    def is_configured(self) -> bool:
        return bool(self.multicast_group_amber and self.port)

    def is_active(self) -> bool:
        """無効化中はソースIP等の設定値を保持したままRxセッションには含めない。"""
        return self.enabled and self.is_configured()

    def apply_format_mode(self) -> None:
        """sampling_mode/ptime_modeが手動固定の場合、実際にMTLへ渡す値を揃える。"""
        if self.sampling_mode == "48khz":
            self.sample_rate = 48000
        if self.ptime_mode in _AUDIO_PTIME_MODE_TO_MS:
            self.packet_time_ms = _AUDIO_PTIME_MODE_TO_MS[self.ptime_mode]


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
        """有効かつ設定済みの映像Receiverの (video_format, pg_format) 一覧を返す。

        無効化中のReceiverはRxセッションに含まれないため、フォーマット不統一
        判定の対象からも除外する (④-8-4-2-1: 無効化されたReceiverは受信していない)。
        """
        return [
            (v.video_format, v.pg_format) for v in self.videos if v.is_active()
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
        """MTL RxTxApp設定JSONを生成する。

        フィールド名は実際にMTL本体(tests/tools/RxTxApp)をソースから確認し、
        以下の点を実機ビルドで判明した誤りから修正した (2026-09):
          - rx_sessionsの受信マルチキャストアドレスは"dip"ではなく"ip"
            ("dip"はtx_sessions専用。RxTxApp tests/tools/RxTxApp/src/parse_json.c
            および script/loop_json/multicast_redundant_1v_1a_1anc.json 参照)
          - ポート番号フィールドは"udp_port"ではなく"start_port"
          - video/audioセッションオブジェクトには必須で"type": "frame"が必要
            (parse_json.cはtypeフィールドをNULLチェックなしでstrcmp()に渡すため、
            欠落しているとRxTxAppがクラッシュする)
        なお、RxTxAppのCLI/JSONスキーマにはPTPドメインを指定する項目が
        ソース上見当たらず(tests/tools/RxTxApp配下に"domain"文字列が一切ない)、
        ここでの"ptp"ブロックは実際には読まれない可能性が高い。実機でのPTP
        ドメイン設定方法は要調査 (docs/verification.md参照)。
        """
        rx_sessions = []
        for v in self.videos:
            if not v.is_active():
                continue
            rx_sessions.append(
                {
                    "ip": [v.multicast_group_amber, v.multicast_group_blue],
                    "interface": [0, 1],
                    "video": [
                        {
                            "type": "frame",
                            "start_port": v.port,
                            "payload_type": v.payload_type,
                            "video_format": v.video_format,
                            "pg_format": v.pg_format,
                        }
                    ],
                }
            )

        if self.audio.is_active():
            rx_sessions.append(
                {
                    "ip": [
                        self.audio.multicast_group_amber,
                        self.audio.multicast_group_blue,
                    ],
                    "interface": [0, 1],
                    "audio": [
                        {
                            "type": "frame",
                            "start_port": self.audio.port,
                            "payload_type": self.audio.payload_type,
                            "audio_format": "PCM24",
                            "audio_channel": ["U02"],
                            "audio_sampling": f"{self.audio.sample_rate // 1000}kHz",
                            "audio_ptime": f"{self.audio.packet_time_ms}ms",
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
            target.enabled = True  # activate(master_enable=true)によるSDP適用は有効化を意味する
            target.source_ip = sdp.source_ip
            target.multicast_group_amber = sdp.multicast_group
            target.port = sdp.port
            target.payload_type = sdp.payload_type
            # ④-8-4-2-1-1-1: video_format_modeが"59i"/"59p"の手動固定時は、
            # SDPが指定する値で上書きしない。
            if target.video_format_mode == "sdp":
                if sdp.video_format:
                    target.video_format = sdp.video_format
                if sdp.pg_format:
                    target.pg_format = sdp.pg_format
            else:
                target.apply_format_mode()
        elif receiver_kind == "audio":
            self.audio.enabled = True  # activate(master_enable=true)によるSDP適用は有効化を意味する
            self.audio.source_ip = sdp.source_ip
            self.audio.multicast_group_amber = sdp.multicast_group
            self.audio.port = sdp.port
            self.audio.payload_type = sdp.payload_type
            # ④-8-4-2-1-2-1: sampling_mode/ptime_modeが手動固定時はSDPで上書きしない。
            if self.audio.sampling_mode == "sdp" and sdp.sample_rate:
                self.audio.sample_rate = sdp.sample_rate
            if self.audio.ptime_mode == "sdp" and sdp.packet_time_ms:
                self.audio.packet_time_ms = sdp.packet_time_ms
            self.audio.apply_format_mode()
        else:
            raise ConfigValidationError(f"不明なreceiver_kind: {receiver_kind}")

    def receiver_by_kind(self, receiver_kind: str, index: int = 0):
        """kind/indexからVideoReceiverConfig/AudioReceiverConfigを取得する。"""
        if receiver_kind == "video":
            if not (0 <= index < 4):
                raise ConfigValidationError(f"映像Receiver index範囲外: {index}")
            return self.videos[index]
        if receiver_kind == "audio":
            return self.audio
        raise ConfigValidationError(f"不明なreceiver_kind: {receiver_kind}")

    def set_enabled(self, receiver_kind: str, index: int, enabled: bool) -> None:
        """④-8-4-2-1の有効/無効トグル。ソースIP・マルチキャストアドレス・ポート・
        ペイロードID等の設定値(JSON)は無効化中も変更しない(補足仕様: 再有効化時に
        NMOSから再度SDPを取得し直さず、保持済みの設定値でIGMP Joinし直す)。
        """
        self.receiver_by_kind(receiver_kind, index).enabled = enabled

    def as_dict(self) -> dict:
        return asdict(self)
