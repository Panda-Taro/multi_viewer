import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from generate_config import (
    ViewerSettings,
    MediaMtxConfigError,
    build_config_dict,
    viewer_url,
)


def test_default_viewer_path_is_monitor01():
    s = ViewerSettings()
    assert s.viewer_path == "monitor01"


def test_bitrate_out_of_range_rejected_low():
    s = ViewerSettings(bitrate_mbps=5)
    with pytest.raises(MediaMtxConfigError):
        s.validate()


def test_bitrate_out_of_range_rejected_high():
    s = ViewerSettings(bitrate_mbps=51)
    with pytest.raises(MediaMtxConfigError):
        s.validate()


def test_bitrate_boundaries_accepted():
    ViewerSettings(bitrate_mbps=10).validate()
    ViewerSettings(bitrate_mbps=50).validate()


def test_viewer_path_rejects_slash():
    s = ViewerSettings(viewer_path="foo/bar")
    with pytest.raises(MediaMtxConfigError):
        s.validate()


def test_build_config_dict_uses_custom_path():
    s = ViewerSettings(viewer_path="monitor02")
    cfg = build_config_dict(s)
    assert "monitor02" in cfg["paths"]
    assert cfg["webrtc"] is True


def test_viewer_url_default_format():
    s = ViewerSettings(control_nic_ip="192.168.10.5")
    assert viewer_url(s) == "http://192.168.10.5/monitor01/"


def test_viewer_url_override_ip():
    s = ViewerSettings(control_nic_ip="192.168.10.5")
    assert viewer_url(s, control_nic_ip="10.0.0.9") == "http://10.0.0.9/monitor01/"
