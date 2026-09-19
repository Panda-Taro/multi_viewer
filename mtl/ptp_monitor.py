"""mtl/ptp_monitor.py

対応要件: ④-3 (PTP同期、Amber優先・Blue自動フェイルオーバー、切替イベントのログ)

実機ではMTL/カーネルのPTPクライアント状態を `scripts/ptp_status.sh` (journalctl
パース) から取得するが、その「Amber優先・障害時Blue自動切替・全switch事象を
ログに残す」という状態遷移ロジック自体は、ハードウェアなしでも純粋な状態機械
としてテスト可能なため、ここに分離して実装する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Callable, Optional


class PtpSource(str, Enum):
    AMBER = "amber"
    BLUE = "blue"
    NONE = "none"


@dataclass
class PtpEvent:
    timestamp: str
    from_source: PtpSource
    to_source: PtpSource
    reason: str

    def format_log_line(self) -> str:
        return (
            f"{self.timestamp} [PTP] [INFO] "
            f"PTPソース切替: {self.from_source.value} -> {self.to_source.value} "
            f"理由={self.reason}"
        )


@dataclass
class PtpMonitor:
    """Amber優先・Blue自動フェイルオーバーの状態機械 (④-3)。

    - Amberがロックしている間は常にAmberを使用する (Amber優先)。
    - Amberがロック喪失した場合、Blueがロックしていれば即座にBlueへ切替。
    - Amberのロックが復帰した場合、自動的にAmberへ戻る (優先順位に基づく復帰)。
    - すべての切替は PtpEvent として記録され、`events` に蓄積される
      (WebGUIのログビューアが参照する想定)。
    """

    current_source: PtpSource = PtpSource.NONE
    amber_locked: bool = False
    blue_locked: bool = False
    events: list[PtpEvent] = field(default_factory=list)
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(timezone.utc)
    )

    def _now_iso(self) -> str:
        return self.clock().isoformat()

    def _switch_to(self, new_source: PtpSource, reason: str) -> None:
        if new_source == self.current_source:
            return
        event = PtpEvent(
            timestamp=self._now_iso(),
            from_source=self.current_source,
            to_source=new_source,
            reason=reason,
        )
        self.events.append(event)
        self.current_source = new_source

    def update(self, amber_locked: bool, blue_locked: bool) -> Optional[PtpEvent]:
        """最新のAmber/Blueロック状態を反映し、必要なら切替を行う。

        戻り値: 切替が発生した場合はそのPtpEvent、なければNone。
        """
        self.amber_locked = amber_locked
        self.blue_locked = blue_locked
        before = self.current_source

        if amber_locked:
            self._switch_to(PtpSource.AMBER, "Amberロック検出(優先ソース)")
        elif blue_locked:
            self._switch_to(PtpSource.BLUE, "Amber障害検出、Blueへフェイルオーバー")
        else:
            self._switch_to(PtpSource.NONE, "Amber/Blueともにロック喪失")

        if self.current_source != before:
            return self.events[-1]
        return None
