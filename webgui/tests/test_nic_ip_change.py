import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from datetime import datetime, timedelta, timezone
import pytest
from app.nic_ip_change import NicIpChangeManager, NicIpChangeError


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, delta):
        self.now += delta


def test_request_change_creates_pending():
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    mgr = NicIpChangeManager(clock=clock)
    change = mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    assert change.nic_name == "amber0"
    assert not change.confirmed
    assert len(mgr.active_pending()) == 1


def test_request_change_rejects_bad_cidr():
    mgr = NicIpChangeManager()
    with pytest.raises(NicIpChangeError):
        mgr.request_change("amber0", "192.168.100.1/24", "not-an-ip")


def test_confirm_after_reboot_clears_pending():
    mgr = NicIpChangeManager()
    mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    mgr.confirm_after_reboot("amber0")
    assert mgr.active_pending() == []


def test_rollback_due_after_timeout():
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    mgr = NicIpChangeManager(clock=clock, confirm_timeout=timedelta(minutes=5))
    mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    assert mgr.is_rollback_due("amber0") is False
    clock.advance(timedelta(minutes=6))
    assert mgr.is_rollback_due("amber0") is True


def test_rollback_returns_previous_ip_and_prevents_double_rollback():
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    mgr = NicIpChangeManager(clock=clock, confirm_timeout=timedelta(minutes=5))
    mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    clock.advance(timedelta(minutes=6))
    prev = mgr.rollback("amber0")
    assert prev == "192.168.100.1/24"
    assert mgr.active_pending() == []
    with pytest.raises(NicIpChangeError):
        mgr.rollback("amber0")  # already rolled back / not due again


def test_rollback_before_deadline_raises():
    mgr = NicIpChangeManager(confirm_timeout=timedelta(minutes=5))
    mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    with pytest.raises(NicIpChangeError):
        mgr.rollback("amber0")


def test_confirmed_change_never_rolls_back_even_after_deadline():
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    mgr = NicIpChangeManager(clock=clock, confirm_timeout=timedelta(minutes=5))
    mgr.request_change("amber0", "192.168.100.1/24", "192.168.200.1/24")
    mgr.confirm_after_reboot("amber0")
    clock.advance(timedelta(minutes=10))
    assert mgr.is_rollback_due("amber0") is False
