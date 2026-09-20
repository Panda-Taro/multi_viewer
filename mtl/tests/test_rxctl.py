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


def test_to_mtl_json_uses_real_rxtxapp_field_names():
    # 実際のMTL RxTxApp (tests/tools/RxTxApp/src/parse_json.c) のスキーマに
    # 合わせたフィールド名であることを確認する (2026-09の実機ビルドで判明した
    # 誤り: 'dip'ではなく'ip'、'udp_port'ではなく'start_port'、'type'必須)。
    cfg = RxSystemConfig()
    cfg.apply_sdp("video", 0, FakeSdp())
    cfg.videos[0].multicast_group_blue = "239.2.1.10"
    j = cfg.to_mtl_json()
    session = j["rx_sessions"][0]
    assert "ip" in session and "dip" not in session
    assert session["ip"] == [cfg.videos[0].multicast_group_amber, "239.2.1.10"]
    video = session["video"][0]
    assert video["type"] == "frame"
    assert "start_port" in video and "udp_port" not in video


def test_audio_apply_sdp():
    cfg = RxSystemConfig()
    cfg.apply_sdp(
        "audio",
        0,
        FakeSdp(multicast_group="239.1.1.20", port=20100, sample_rate=48000),
    )
    assert cfg.audio.multicast_group_amber == "239.1.1.20"
    assert cfg.audio.channels == 2


def test_video_receiver_enabled_by_default():
    cfg = RxSystemConfig()
    assert cfg.videos[0].enabled is True
    assert cfg.audio.enabled is True


def test_set_enabled_false_excludes_from_mtl_json_but_keeps_settings():
    """④-8-4-2-1補足仕様: 無効化中もRX設定値(JSON)自体は保持する。"""
    cfg = RxSystemConfig()
    cfg.apply_sdp("video", 0, FakeSdp(multicast_group="239.1.1.10", port=20000))

    cfg.set_enabled("video", 0, False)

    assert cfg.videos[0].enabled is False
    assert cfg.videos[0].multicast_group_amber == "239.1.1.10"
    assert cfg.videos[0].port == 20000
    assert cfg.to_mtl_json()["rx_sessions"] == []


def test_set_enabled_true_restores_session_from_retained_settings():
    cfg = RxSystemConfig()
    cfg.apply_sdp("video", 0, FakeSdp(multicast_group="239.1.1.10", port=20000))
    cfg.set_enabled("video", 0, False)

    cfg.set_enabled("video", 0, True)

    assert len(cfg.to_mtl_json()["rx_sessions"]) == 1


def test_disabled_receiver_excluded_from_format_uniformity_check():
    cfg = RxSystemConfig()
    for i in range(3):
        cfg.apply_sdp(
            "video", i, FakeSdp(multicast_group=f"239.1.1.{10+i}", port=20000 + i)
        )
    cfg.apply_sdp(
        "video",
        3,
        FakeSdp(multicast_group="239.1.1.13", port=20003, video_format="i2160p59"),
    )
    assert cfg.check_format_uniformity() == "映像フォーマットが4系統で非統一です"

    cfg.set_enabled("video", 3, False)
    assert cfg.check_format_uniformity() is None


def test_audio_disabled_excluded_from_mtl_json():
    cfg = RxSystemConfig()
    cfg.apply_sdp(
        "audio", 0, FakeSdp(multicast_group="239.1.1.20", port=20100)
    )
    cfg.set_enabled("audio", 0, False)
    assert cfg.to_mtl_json()["rx_sessions"] == []


def test_video_format_mode_defaults_to_sdp_and_sdp_overwrites():
    cfg = RxSystemConfig()
    assert cfg.videos[0].video_format_mode == "sdp"
    cfg.apply_sdp("video", 0, FakeSdp(video_format="p1080p50"))
    assert cfg.videos[0].video_format == "p1080p50"


def test_video_format_mode_manual_59i_not_overwritten_by_sdp():
    """④-8-4-2-1-1-1: 59i/59p固定時はSDPが来ても上書きしない。"""
    cfg = RxSystemConfig()
    cfg.videos[0].video_format_mode = "59i"
    cfg.apply_sdp("video", 0, FakeSdp(video_format="p2160p59"))
    assert cfg.videos[0].video_format == "i1080p59"


def test_video_format_mode_manual_59p():
    cfg = RxSystemConfig()
    cfg.videos[0].video_format_mode = "59p"
    cfg.apply_sdp("video", 0, FakeSdp(video_format="i1080p59"))
    assert cfg.videos[0].video_format == "p1080p59"


def test_audio_sampling_and_ptime_mode_manual_not_overwritten_by_sdp():
    cfg = RxSystemConfig()
    cfg.audio.sampling_mode = "48khz"
    cfg.audio.ptime_mode = "0.125ms"
    cfg.apply_sdp("audio", 0, FakeSdp(sample_rate=96000, packet_time_ms=1.0))
    assert cfg.audio.sample_rate == 48000
    assert cfg.audio.packet_time_ms == 0.125
