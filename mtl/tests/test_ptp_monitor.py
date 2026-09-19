import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from ptp_monitor import PtpMonitor, PtpSource


def fixed_clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_initial_lock_on_amber():
    mon = PtpMonitor(clock=fixed_clock)
    event = mon.update(amber_locked=True, blue_locked=False)
    assert mon.current_source == PtpSource.AMBER
    assert event is not None
    assert event.to_source == PtpSource.AMBER


def test_no_event_when_source_unchanged():
    mon = PtpMonitor(clock=fixed_clock)
    mon.update(amber_locked=True, blue_locked=False)
    event = mon.update(amber_locked=True, blue_locked=True)  # still prefers amber
    assert mon.current_source == PtpSource.AMBER
    assert event is None


def test_failover_to_blue_on_amber_loss():
    mon = PtpMonitor(clock=fixed_clock)
    mon.update(amber_locked=True, blue_locked=True)
    event = mon.update(amber_locked=False, blue_locked=True)
    assert mon.current_source == PtpSource.BLUE
    assert event.from_source == PtpSource.AMBER
    assert event.to_source == PtpSource.BLUE
    assert "フェイルオーバー" in event.reason


def test_recovers_to_amber_when_amber_relocks():
    mon = PtpMonitor(clock=fixed_clock)
    mon.update(amber_locked=True, blue_locked=True)
    mon.update(amber_locked=False, blue_locked=True)
    event = mon.update(amber_locked=True, blue_locked=True)
    assert mon.current_source == PtpSource.AMBER
    assert event.to_source == PtpSource.AMBER


def test_both_lost_goes_to_none():
    mon = PtpMonitor(clock=fixed_clock)
    mon.update(amber_locked=True, blue_locked=False)
    event = mon.update(amber_locked=False, blue_locked=False)
    assert mon.current_source == PtpSource.NONE
    assert event.to_source == PtpSource.NONE


def test_all_events_logged_in_order():
    mon = PtpMonitor(clock=fixed_clock)
    mon.update(amber_locked=True, blue_locked=False)
    mon.update(amber_locked=False, blue_locked=True)
    mon.update(amber_locked=True, blue_locked=True)
    assert len(mon.events) == 3
    assert [e.to_source for e in mon.events] == [
        PtpSource.AMBER,
        PtpSource.BLUE,
        PtpSource.AMBER,
    ]


def test_log_line_format_contains_key_fields():
    mon = PtpMonitor(clock=fixed_clock)
    event = mon.update(amber_locked=True, blue_locked=False)
    line = event.format_log_line()
    assert "[PTP]" in line
    assert "amber" in line
