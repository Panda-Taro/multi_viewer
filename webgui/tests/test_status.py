import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.status import ReceiverStatus, ReceiverLed, build_dashboard_status


def test_disabled_receiver_led_regardless_of_signal():
    """④-8-4-2-1補足仕様: 無効化中は受信状態に関わらず「無効」表示。"""
    r = ReceiverStatus(label="Video Receiver 1", enabled=False, amber_active=True, blue_active=True, configured=True)
    assert r.led == ReceiverLed.DISABLED


def test_enabled_and_receiving_is_ok():
    r = ReceiverStatus(label="Video Receiver 1", enabled=True, amber_active=True, blue_active=False, configured=True)
    assert r.led == ReceiverLed.OK


def test_enabled_but_no_signal_is_warn():
    r = ReceiverStatus(label="Video Receiver 1", enabled=True, amber_active=False, blue_active=False, configured=True)
    assert r.led == ReceiverLed.WARN


def test_enabled_but_unconfigured_is_warn_not_disabled():
    """未設定と無効化(disabled)は別概念であるため区別する。"""
    r = ReceiverStatus(label="Video Receiver 1", enabled=True, amber_active=False, blue_active=False, configured=False)
    assert r.led == ReceiverLed.WARN


def test_build_dashboard_status_passes_enabled_through():
    status = build_dashboard_status(
        cpu_percent=1.0,
        nic_bandwidth_mbps={},
        receiver_activity=[
            {"label": "Video Receiver 1", "enabled": False, "amber_active": False, "blue_active": False, "configured": True}
        ],
        ptp_locked=False,
        ptp_source="unknown",
        viewer_url="",
    )
    assert status.receivers[0].led == ReceiverLed.DISABLED
