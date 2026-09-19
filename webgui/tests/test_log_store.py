import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from datetime import datetime, timezone
from app.log_store import LogStore, LogEntry


def fixed_clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_add_creates_entry_with_iso_timestamp():
    store = LogStore(clock=fixed_clock)
    entry = store.add("PTP", "INFO", "テストメッセージ")
    assert entry.timestamp == "2026-01-01T00:00:00+00:00"
    assert len(store.entries) == 1


def test_filter_by_component_and_level():
    store = LogStore(clock=fixed_clock)
    store.add("PTP", "INFO", "a")
    store.add("NMOS", "ERROR", "b")
    store.add("PTP", "ERROR", "c")
    assert len(store.filter(component="PTP")) == 2
    assert len(store.filter(level="ERROR")) == 2
    assert len(store.filter(component="PTP", level="ERROR")) == 1


def test_export_text_contains_all_lines():
    store = LogStore(clock=fixed_clock)
    store.add("PTP", "INFO", "a")
    store.add("NMOS", "WARN", "b")
    text = store.export_text()
    assert "[PTP] [INFO] a" in text
    assert "[NMOS] [WARN] b" in text


def test_max_entries_trims_oldest():
    store = LogStore(clock=fixed_clock, max_entries=3)
    for i in range(5):
        store.add("X", "INFO", str(i))
    assert len(store.entries) == 3
    assert [e.message for e in store.entries] == ["2", "3", "4"]


def test_parse_line_roundtrip():
    entry = LogEntry(timestamp="2026-01-01T00:00:00+00:00", component="PTP", level="INFO", message="hello world")
    line = entry.format_line()
    parsed = LogEntry.parse_line(line)
    assert parsed.component == "PTP"
    assert parsed.level == "INFO"
    assert parsed.message == "hello world"


def test_parse_line_returns_none_for_garbage():
    assert LogEntry.parse_line("this is not a log line") is None
