"""webgui/app/config_store.py

対応要件: ④-8 (WebGUI全設定の一元管理)、「保存失敗時はエラー表示し前の値を保持」

Receiver/PTP/NMOS/視聴配信の設定を保持し、更新時はまずバリデーションを行い、
失敗すれば例外を送出して**内部状態を一切変更しない** (呼び出し元=ルータが
これを捕捉してエラー表示し、画面には保存前の値が残る)。

mtl.rxctl / mediamtx.generate_config を再利用し、二重定義を避けている。
"""
from __future__ import annotations

import os
import sys
import copy
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mtl"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mediamtx"))

from rxctl import (  # noqa: E402
    RxSystemConfig,
    ConfigValidationError as RxCtlValidationError,
    VIDEO_FORMAT_MODES,
    AUDIO_SAMPLING_MODES,
    AUDIO_PTIME_MODES,
)
from generate_config import ViewerSettings, MediaMtxConfigError  # noqa: E402


class ConfigValidationError(ValueError):
    """④-8: 設定保存失敗時にこの例外を送出し、呼び出し側は前の値を維持する。"""


NMOS_DISCOVERY_MODES = ("mdns", "static", "p2p")
IS04_VERSIONS = ("v1.1", "v1.2", "v1.3")
IS05_VERSIONS = ("v1.0", "v1.1")


@dataclass
class NmosSettings:
    """④-8 メディアストリーム設定 > NMOS設定。"""

    discovery_mode: str = "mdns"  # "mdns" | "static" | "p2p"(RDS無し時のフォールバック)
    registration_address: str = ""
    registration_port: int = 0
    is04_version: str = "v1.3"
    is05_version: str = "v1.1"
    # 「auto」= バックエンドがエフェメラルポートを選択 (要件⑥)
    node_api_port: str = "auto"
    registration_api_port: str = "auto"

    def validate(self) -> None:
        if self.discovery_mode not in NMOS_DISCOVERY_MODES:
            raise ConfigValidationError(f"不明なNMOS discovery_mode: {self.discovery_mode}")
        if self.discovery_mode == "static":
            if not self.registration_address:
                raise ConfigValidationError("静的モードではregistration_addressが必須です")
            if not (0 < self.registration_port < 65536):
                raise ConfigValidationError(
                    f"registration_portは1-65535の範囲でなければならない: {self.registration_port}"
                )
        if self.is04_version not in IS04_VERSIONS:
            raise ConfigValidationError(f"サポート外のIS-04バージョン: {self.is04_version}")
        if self.is05_version not in IS05_VERSIONS:
            raise ConfigValidationError(f"サポート外のIS-05バージョン: {self.is05_version}")
        for label, value in (("node_api_port", self.node_api_port), ("registration_api_port", self.registration_api_port)):
            if value != "auto":
                try:
                    port = int(value)
                except (TypeError, ValueError):
                    raise ConfigValidationError(f"{label}は'auto'か整数でなければならない: {value!r}")
                if not (0 < port < 65536):
                    raise ConfigValidationError(f"{label}は1-65535の範囲でなければならない: {port}")


@dataclass
class NicSettings:
    """④-8 システム設定 > NIC設定 (10G x2, 1G x1)。"""

    amber_name: str = "amber0"
    amber_ip_cidr: str = "192.168.100.1/24"
    blue_name: str = "blue0"
    blue_ip_cidr: str = "192.168.101.1/24"
    control_name: str = "eth0"
    control_ip_cidr: str = "192.168.10.10/24"


class ConfigStore:
    """WebGUIが保持する設定全体のシングルトン相当。"""

    def __init__(self) -> None:
        self._media = RxSystemConfig()
        self._nmos = NmosSettings()
        self._nic = NicSettings()
        self._viewer = ViewerSettings()

    # --- 読み取り ---
    @property
    def media(self) -> RxSystemConfig:
        return self._media

    @property
    def nmos(self) -> NmosSettings:
        return self._nmos

    @property
    def nic(self) -> NicSettings:
        return self._nic

    @property
    def viewer(self) -> ViewerSettings:
        return self._viewer

    # --- 更新 (バリデーション失敗時は例外、状態は変更しない) ---
    def update_nmos(self, candidate: NmosSettings) -> None:
        candidate.validate()
        self._nmos = candidate

    def update_viewer(self, candidate: ViewerSettings) -> None:
        try:
            candidate.validate()
        except MediaMtxConfigError as e:
            raise ConfigValidationError(str(e)) from e
        self._viewer = candidate

    def update_video_receiver(self, index: int, **fields) -> Optional[str]:
        """映像Receiver1系統分を更新する。戻り値はフォーマット不統一アラーム
        メッセージ (なければNone)。バリデーション失敗時は元の状態を保持する。
        """
        if not (0 <= index < 4):
            raise ConfigValidationError(f"Receiver indexは0-3でなければならない: {index}")

        working_copy = copy.deepcopy(self._media)
        target = working_copy.videos[index]
        for key, value in fields.items():
            if not hasattr(target, key):
                raise ConfigValidationError(f"不明な映像Receiverフィールド: {key}")
            setattr(target, key, value)

        if target.video_format_mode not in VIDEO_FORMAT_MODES:
            raise ConfigValidationError(f"不明な映像フォーマットモード: {target.video_format_mode}")
        for label, port in (("port_amber", target.port_amber), ("port_blue", target.port_blue)):
            if port and not (0 < port < 65536):
                raise ConfigValidationError(f"{label}は1-65535の範囲でなければならない: {port}")

        target.apply_format_mode()
        self._media = working_copy
        return self._media.check_format_uniformity()

    def update_audio_receiver(self, **fields) -> None:
        working_copy = copy.deepcopy(self._media)
        target = working_copy.audio
        for key, value in fields.items():
            if not hasattr(target, key):
                raise ConfigValidationError(f"不明な音声Receiverフィールド: {key}")
            setattr(target, key, value)

        if target.sampling_mode not in AUDIO_SAMPLING_MODES:
            raise ConfigValidationError(f"不明な音声サンプリングモード: {target.sampling_mode}")
        if target.ptime_mode not in AUDIO_PTIME_MODES:
            raise ConfigValidationError(f"不明なパケットインターバルモード: {target.ptime_mode}")
        for label, port in (("port_amber", target.port_amber), ("port_blue", target.port_blue)):
            if port and not (0 < port < 65536):
                raise ConfigValidationError(f"{label}は1-65535の範囲でなければならない: {port}")

        target.apply_format_mode()
        self._media = working_copy

    def set_receiver_enabled(self, receiver_kind: str, index: int, enabled: bool) -> None:
        """④-8-4-2-1補足仕様: WebGUIトグル操作。IS-05側との同期はルータ層
        (webgui/app/routers/media.py)がbridgeの`/webgui/receiver-toggle`を
        呼び出すことで行う。"""
        working_copy = copy.deepcopy(self._media)
        working_copy.set_enabled(receiver_kind, index, enabled)
        self._media = working_copy

    def update_ptp_domain(self, domain: int) -> None:
        if not (0 <= domain <= 127):
            raise ConfigValidationError(f"PTPドメイン番号は0-127でなければならない: {domain}")
        working_copy = copy.deepcopy(self._media)
        working_copy.ptp.domain = domain
        self._media = working_copy

    def update_nic(self, candidate: NicSettings) -> None:
        for label, cidr in (
            ("amber_ip_cidr", candidate.amber_ip_cidr),
            ("blue_ip_cidr", candidate.blue_ip_cidr),
            ("control_ip_cidr", candidate.control_ip_cidr),
        ):
            if "/" not in cidr:
                raise ConfigValidationError(f"{label}はCIDR形式でなければならない: {cidr!r}")
        self._nic = candidate


# アプリ全体で共有する単一インスタンス (webgui/app/routers/*.py から参照)
store = ConfigStore()
