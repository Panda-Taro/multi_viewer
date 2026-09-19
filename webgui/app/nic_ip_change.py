"""webgui/app/nic_ip_change.py

対応要件: ④-8, ⑤ (「NIC IP変更は確認/ロールバック機構を持ち、自己ロックアウトを
防止する。反映にはフルリブートを要する」)

設計 (判断メモ):
  1. GUIでIP変更を保存すると「pending(保留中)」状態になり、即座には
     `/etc/netplan/` 等へ反映しない。GUI上に「再起動が必要です」の
     確認ダイアログ文言を表示する (テンプレート側)。
  2. 実際の適用は明示的な `confirm_and_apply()` 呼び出し (「再起動して適用」
     ボタン)で行い、変更前のIPを `previous` として保持したまま
     ネットワーク設定を書き換えて reboot する。
  3. 起動後、WebGUIプロセスは一定時間 (デフォルト5分) 以内に運用者から
     `confirm_after_reboot()` (「新しい設定に到達できています」の確認、
     GUI側は新IPで自分自身にアクセスできた時点で自動的にこれを呼ぶ設計)
     を受け取れなければ、`is_rollback_due()` がTrueを返し、systemdの
     タイマー (`multiviewer-nic-rollback.timer`, 別途systemd/に定義) が
     `rollback()` を実行して旧IPに戻し再度reboot する。
  4. これにより「新IPを設定したらSSH/GUIともに到達不能になった」という
     自己ロックアウトを、タイムアウト付きの自動ロールバックで防止する。

本モジュールは時計を注入可能にし、ファイルI/O・実際のreboot呼び出しを
伴わない状態機械としてテストする。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


class NicIpChangeError(RuntimeError):
    pass


@dataclass
class PendingNicChange:
    nic_name: str
    previous_ip_cidr: str
    new_ip_cidr: str
    requested_at: datetime
    confirm_deadline: datetime
    confirmed: bool = False
    rolled_back: bool = False


@dataclass
class NicIpChangeManager:
    confirm_timeout: timedelta = field(default=timedelta(minutes=5))
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    pending: dict[str, PendingNicChange] = field(default_factory=dict)

    def request_change(self, nic_name: str, previous_ip_cidr: str, new_ip_cidr: str) -> PendingNicChange:
        if not new_ip_cidr or "/" not in new_ip_cidr:
            raise NicIpChangeError(f"IPアドレス指定が不正です (CIDR形式が必要): {new_ip_cidr!r}")
        now = self.clock()
        change = PendingNicChange(
            nic_name=nic_name,
            previous_ip_cidr=previous_ip_cidr,
            new_ip_cidr=new_ip_cidr,
            requested_at=now,
            confirm_deadline=now + self.confirm_timeout,
        )
        self.pending[nic_name] = change
        return change

    def confirm_after_reboot(self, nic_name: str) -> None:
        """新IPでの到達性が確認できた時点で呼ばれ、pendingを解消する。"""
        change = self.pending.get(nic_name)
        if change is None:
            raise NicIpChangeError(f"保留中の変更がありません: {nic_name}")
        change.confirmed = True

    def is_rollback_due(self, nic_name: str) -> bool:
        change = self.pending.get(nic_name)
        if change is None or change.confirmed or change.rolled_back:
            return False
        return self.clock() >= change.confirm_deadline

    def rollback(self, nic_name: str) -> str:
        """タイムアウトによりロールバックし、復元すべきIPを返す。"""
        change = self.pending.get(nic_name)
        if change is None:
            raise NicIpChangeError(f"保留中の変更がありません: {nic_name}")
        if not self.is_rollback_due(nic_name):
            raise NicIpChangeError(f"まだロールバック期限に達していません: {nic_name}")
        change.rolled_back = True
        return change.previous_ip_cidr

    def active_pending(self) -> list[PendingNicChange]:
        return [
            c for c in self.pending.values() if not c.confirmed and not c.rolled_back
        ]
