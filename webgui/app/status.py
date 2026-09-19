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
    OK = "ok"        # 緑: 正常受信中
    WARN = "warn"    # 黄: 一部冗長経路のみ受信 (Amber/Blue片系)
    ERROR = "error"  # 赤: 受信なし/未設定


@dataclass
class ReceiverStatus:
    label: str
    amber_active: bool
    blue_active: bool
    configured: bool

    @property
    def led(self) -> ReceiverLed:
        if not self.configured:
            return ReceiverLed.ERROR
        if self.amber_active and self.blue_active:
            return ReceiverLed.OK
        if self.amber_active or self.blue_active:
            return ReceiverLed.WARN
        return ReceiverLed.ERROR


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
