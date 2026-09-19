"""webgui/app/log_store.py

対応要件: ⑤ (PTP切替/NMOS接続断/Receiver状態変化のログ記録、WebGUIでの
閲覧・エクスポート)

ログフォーマット (判断メモ、NOTES.md参照):
  "<ISO8601> [<コンポーネント>] [<レベル>] <メッセージ>" のプレーンテキスト1行。
  実機では各コンポーネントのsystemdサービスがjournalおよび/またはこの形式で
  `/var/log/multiviewer/*.log` に書き込む。WebGUIは複数ログファイルを
  マージして時系列表示し、そのままダウンロード可能にする。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


@dataclass
class LogEntry:
    timestamp: str
    component: str
    level: str
    message: str

    def format_line(self) -> str:
        return f"{self.timestamp} [{self.component}] [{self.level}] {self.message}"

    @staticmethod
    def parse_line(line: str) -> "LogEntry | None":
        # "<ts> [<component>] [<level>] <message>"
        try:
            ts, rest = line.split(" [", 1)
            component, rest = rest.split("] [", 1)
            level, message = rest.split("] ", 1)
            return LogEntry(timestamp=ts, component=component, level=level.strip("]"), message=message.rstrip("\n"))
        except ValueError:
            return None


@dataclass
class LogStore:
    """インメモリのログバッファ(実機では複数ログファイルの集約に置き換え)。"""

    entries: list[LogEntry] = field(default_factory=list)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    max_entries: int = 10000

    def add(self, component: str, level: str, message: str) -> LogEntry:
        entry = LogEntry(
            timestamp=self.clock().isoformat(), component=component, level=level, message=message
        )
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
        return entry

    def filter(self, component: str | None = None, level: str | None = None) -> list[LogEntry]:
        result = self.entries
        if component:
            result = [e for e in result if e.component == component]
        if level:
            result = [e for e in result if e.level == level]
        return result

    def export_text(self) -> str:
        return "\n".join(e.format_line() for e in self.entries) + ("\n" if self.entries else "")

    def load_from_file(self, path: Path) -> int:
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            entry = LogEntry.parse_line(line)
            if entry:
                self.entries.append(entry)
                count += 1
        return count


# アプリ全体で共有するログストア
log_store = LogStore()
