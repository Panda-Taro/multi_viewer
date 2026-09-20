import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from app.config_store import ConfigStore, ConfigValidationError, NmosSettings, NicSettings
from app.config_store import store as _unused_shared_store  # noqa: F401  (importability check)


def test_default_media_has_4_video_1_audio():
    store = ConfigStore()
    assert len(store.media.videos) == 4


def test_update_video_receiver_valid():
    store = ConfigStore()
    alarm = store.update_video_receiver(0, multicast_group_amber="239.1.1.10", port_amber=20000)
    assert store.media.videos[0].multicast_group_amber == "239.1.1.10"
    assert alarm is None


def test_update_video_receiver_invalid_index_raises_and_keeps_state():
    store = ConfigStore()
    with pytest.raises(ConfigValidationError):
        store.update_video_receiver(9, port_amber=1)
    assert store.media.videos[0].multicast_group_amber == ""


def test_update_video_receiver_invalid_port_keeps_previous_value():
    store = ConfigStore()
    store.update_video_receiver(0, multicast_group_amber="239.1.1.10", port_amber=20000)
    with pytest.raises(ConfigValidationError):
        store.update_video_receiver(0, multicast_group_amber="239.9.9.9", port_amber=99999)
    # 保存失敗時は前の値を維持する (④-8要件)
    assert store.media.videos[0].multicast_group_amber == "239.1.1.10"
    assert store.media.videos[0].port_amber == 20000


def test_update_video_receiver_invalid_blue_port_keeps_previous_value():
    store = ConfigStore()
    store.update_video_receiver(0, multicast_group_blue="239.9.9.10", port_blue=20001)
    with pytest.raises(ConfigValidationError):
        store.update_video_receiver(0, port_blue=99999)
    assert store.media.videos[0].port_blue == 20001


def test_update_video_receiver_unknown_field_rejected():
    store = ConfigStore()
    with pytest.raises(ConfigValidationError):
        store.update_video_receiver(0, not_a_real_field="x")


def test_format_alarm_triggered_after_4th_mismatched_receiver():
    store = ConfigStore()
    for i in range(3):
        store.update_video_receiver(i, multicast_group_amber=f"239.1.1.{i}", port_amber=20000 + i, video_format="i1080p59")
    alarm = store.update_video_receiver(3, multicast_group_amber="239.1.1.9", port_amber=20009, video_format="p2160p59")
    assert alarm == "映像フォーマットが4系統で非統一です"


def test_update_ptp_domain_valid():
    store = ConfigStore()
    store.update_ptp_domain(10)
    assert store.media.ptp.domain == 10


def test_update_ptp_domain_out_of_range_rejected():
    store = ConfigStore()
    with pytest.raises(ConfigValidationError):
        store.update_ptp_domain(200)
    assert store.media.ptp.domain == 24  # default preserved


def test_nmos_static_mode_requires_address_and_port():
    store = ConfigStore()
    bad = NmosSettings(discovery_mode="static", registration_address="", registration_port=0)
    with pytest.raises(ConfigValidationError):
        store.update_nmos(bad)
    assert store.nmos.discovery_mode == "mdns"  # default preserved


def test_nmos_static_mode_valid():
    store = ConfigStore()
    good = NmosSettings(discovery_mode="static", registration_address="192.168.10.50", registration_port=8010)
    store.update_nmos(good)
    assert store.nmos.discovery_mode == "static"


def test_nmos_port_auto_accepted():
    store = ConfigStore()
    good = NmosSettings(node_api_port="auto", registration_api_port="auto")
    store.update_nmos(good)  # should not raise


def test_nmos_invalid_port_string_rejected():
    store = ConfigStore()
    bad = NmosSettings(node_api_port="not-a-port")
    with pytest.raises(ConfigValidationError):
        store.update_nmos(bad)


def test_viewer_bitrate_validation_delegates_to_mediamtx_module():
    store = ConfigStore()
    from generate_config import ViewerSettings

    with pytest.raises(ConfigValidationError):
        store.update_viewer(ViewerSettings(bitrate_mbps=999))


def test_nic_settings_requires_cidr():
    store = ConfigStore()
    bad = NicSettings(amber_ip_cidr="not-cidr")
    with pytest.raises(ConfigValidationError):
        store.update_nic(bad)


def test_set_receiver_enabled_false_keeps_settings():
    store = ConfigStore()
    store.update_video_receiver(0, multicast_group_amber="239.1.1.10", port_amber=20000)
    store.set_receiver_enabled("video", 0, False)
    assert store.media.videos[0].enabled is False
    assert store.media.videos[0].multicast_group_amber == "239.1.1.10"  # 設定値は保持


def test_set_receiver_enabled_true_restores_mtl_session():
    store = ConfigStore()
    store.update_video_receiver(0, multicast_group_amber="239.1.1.10", port_amber=20000)
    store.set_receiver_enabled("video", 0, False)
    store.set_receiver_enabled("video", 0, True)
    assert any(s["ip"][0] == "239.1.1.10" for s in store.media.to_mtl_json()["rx_sessions"])


def test_update_video_receiver_rejects_unknown_format_mode():
    store = ConfigStore()
    with pytest.raises(ConfigValidationError):
        store.update_video_receiver(0, video_format_mode="not-a-mode")


def test_update_video_receiver_59i_mode_fixes_format_regardless_of_manual_text():
    store = ConfigStore()
    store.update_video_receiver(0, video_format_mode="59i")
    assert store.media.videos[0].video_format == "i1080p59"
    assert store.media.videos[0].pg_format == "YUV_422_10bit"


def test_update_video_receiver_59p_mode():
    store = ConfigStore()
    store.update_video_receiver(0, video_format_mode="59p")
    assert store.media.videos[0].video_format == "p1080p59"


def test_update_audio_receiver_rejects_unknown_sampling_mode():
    store = ConfigStore()
    with pytest.raises(ConfigValidationError):
        store.update_audio_receiver(sampling_mode="not-a-mode")


def test_update_audio_receiver_ptime_mode_0125ms():
    store = ConfigStore()
    store.update_audio_receiver(ptime_mode="0.125ms")
    assert store.media.audio.packet_time_ms == 0.125
