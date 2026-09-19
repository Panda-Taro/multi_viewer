import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from rxctl import RxSystemConfig, ConfigValidationError


class FakeSdp:
    def __init__(self, **kwargs):
        self.source_ip = kwargs.get("source_ip", "192.168.1.100")
        self.multicast_group = kwargs.get("multicast_group", "239.1.1.10")
        self.port = kwargs.get("port", 20000)
        self.payload_type = kwargs.get("payload_type", 112)
        self.video_format = kwargs.get("video_format", "i1080p59")
        self.pg_format = kwargs.get("pg_format", "YUV_422_10bit")
        self.sample_rate = kwargs.get("sample_rate", 48000)
        self.packet_time_ms = kwargs.get("packet_time_ms", 1.0)


def test_requires_exactly_4_video_receivers():
    cfg = RxSystemConfig()
    assert len(cfg.videos) == 4


def test_apply_sdp_video_out_of_range():
    cfg = RxSystemConfig()
    with pytest.raises(ConfigValidationError):
        cfg.apply_sdp("video", 4, FakeSdp())


def test_apply_sdp_video_updates_target_receiver_only():
    cfg = RxSystemConfig()
    cfg.apply_sdp("video", 2, FakeSdp(multicast_group="239.9.9.9", port=30000))
    assert cfg.videos[2].multicast_group_amber == "239.9.9.9"
    assert cfg.videos[2].port == 30000
    # other receivers untouched
    assert cfg.videos[0].multicast_group_amber == ""


def test_format_uniformity_no_alarm_when_all_match():
    cfg = RxSystemConfig()
    for i in range(4):
        cfg.apply_sdp(
            "video", i, FakeSdp(multicast_group=f"239.1.1.{10+i}", port=20000 + i)
        )
    assert cfg.check_format_uniformity() is None


def test_format_uniformity_alarm_on_mismatch():
    cfg = RxSystemConfig()
    for i in range(4):
        cfg.apply_sdp(
            "video", i, FakeSdp(multicast_group=f"239.1.1.{10+i}", port=20000 + i)
        )
    # 4本目だけフォーマットを変える
    cfg.apply_sdp(
        "video",
        3,
        FakeSdp(multicast_group="239.1.1.13", port=20003, video_format="i2160p59"),
    )
    msg = cfg.check_format_uniformity()
    assert msg == "映像フォーマットが4系統で非統一です"


def test_audio_channels_fixed_to_2():
    cfg = RxSystemConfig()
    assert cfg.audio.channels == 2


def test_to_mtl_json_only_includes_configured_sessions():
    cfg = RxSystemConfig(amber_ip="10.0.0.1", blue_ip="10.0.1.1")
    cfg.apply_sdp("video", 0, FakeSdp())
    j = cfg.to_mtl_json()
    assert len(j["rx_sessions"]) == 1
    assert j["interfaces"][0]["ip"] == "10.0.0.1"
    assert j["ptp"]["domain"] == 24


def test_to_mtl_json_marks_redundant_when_blue_group_set():
    cfg = RxSystemConfig()
    cfg.apply_sdp("video", 0, FakeSdp())
    cfg.videos[0].multicast_group_blue = "239.2.1.10"
    j = cfg.to_mtl_json()
    assert j["rx_sessions"][0]["video"][0]["st2022_7_redundant"] is True


def test_audio_apply_sdp():
    cfg = RxSystemConfig()
    cfg.apply_sdp(
        "audio",
        0,
        FakeSdp(multicast_group="239.1.1.20", port=20100, sample_rate=48000),
    )
    assert cfg.audio.multicast_group_amber == "239.1.1.20"
    assert cfg.audio.channels == 2
