"""webgui/app/status.py

対応要件: ④-8 ダッシュボード (Pane2: NIC IP/帯域、CPU使用率、Receiver LED、
PTPロック状態)

実機情報の収集(CPU使用率=psutil、帯域=/sys/class/net/*/statistics、PTP状態=
mtl/scripts/ptp_status.sh)と、収集結果を画面表示用データに正規化するロジックを
分離。正規化ロジック (`build_dashboard_status`) はテスト可能。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReceiverLed(str, Enum):
    """④-8-4-2-1補足仕様: Receiver受信状態は以下3状態のみを区別する。
    無効化のトリガー(WebGUI手動 or NMOS IS-05 deactivate)は区別しない。
    """

    OK = "ok"              # 緑: 有効・受信中(正常)
    WARN = "warn"          # 黄: 有効・信号なし(異常)
    DISABLED = "disabled"  # 灰: 無効(手動OFF・NMOS操作によるOFFいずれも同一表示)


@dataclass
class ReceiverStatus:
    label: str
    enabled: bool
    amber_active: bool
    blue_active: bool
    configured: bool

    @property
    def led(self) -> ReceiverLed:
        """④-8-4-2-1補足仕様の3状態:
          1. 有効・受信中(正常) = enabled かつ (Amber/Blueいずれかで受信中)
          2. 有効・信号なし(異常) = enabled だが無受信、または未設定
          3. 無効 = enabled=False (トリガー種別は問わない)
        """
        if not self.enabled:
            return ReceiverLed.DISABLED
        if not self.configured:
            return ReceiverLed.WARN
        if self.amber_active or self.blue_active:
            return ReceiverLed.OK
        return ReceiverLed.WARN


@dataclass
class DashboardStatus:
    cpu_percent: float
    nic_bandwidth_mbps: dict  # {"amber0": 123.4, ...}
    receivers: list[ReceiverStatus] = field(default_factory=list)
    ptp_locked: bool = False
    ptp_source: str = "unknown"
    viewer_url: str = ""


def build_dashboard_status(
    cpu_percent: float,
    nic_bandwidth_mbps: dict,
    receiver_activity: list[dict],
    ptp_locked: bool,
    ptp_source: str,
    viewer_url: str,
) -> DashboardStatus:
    """要件④-8: ダッシュボードPane2に表示する状態を組み立てる。

    receiver_activity: [{"label": "Video Receiver 1", "amber_active": bool,
                          "blue_active": bool, "configured": bool}, ...]
    """
    receivers = [ReceiverStatus(**r) for r in receiver_activity]
    return DashboardStatus(
        cpu_percent=cpu_percent,
        nic_bandwidth_mbps=nic_bandwidth_mbps,
        receivers=receivers,
        ptp_locked=ptp_locked,
        ptp_source=ptp_source,
        viewer_url=viewer_url,
    )
