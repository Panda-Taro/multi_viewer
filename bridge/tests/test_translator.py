import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mtl"))

import pytest
from translator import (
    apply_activate_request,
    apply_deactivate_request,
    apply_enable_request,
    receiver_kind_and_index,
    ActivateTranslationError,
)
from rxctl import RxSystemConfig


VIDEO_SDP_TMPL = """v=0
o=- 1 1 IN IP4 192.168.1.{last}
s=Cam
c=IN IP4 239.1.1.{last}/32
t=0 0
m=video {port} RTP/AVP 112
a=rtpmap:112 raw/90000
a=fmtp:112 sampling=YCbCr-4:2:2; width=1920; height=1080; interlace; exactframerate=60000/1001; depth=10
"""


def _video_sdp(last: int) -> str:
    return VIDEO_SDP_TMPL.format(last=last, port=20000 + last)

AUDIO_SDP = """v=0
o=- 1 1 IN IP4 192.168.1.99
s=Aud
c=IN IP4 239.1.1.99/32
t=0 0
m=audio 20100 RTP/AVP 111
a=rtpmap:111 L24/48000/2
a=ptime:1
"""


def test_receiver_kind_and_index_video():
    kind, idx = receiver_kind_and_index("video-receiver-3")
    assert kind == "video"
    assert idx == 2


def test_receiver_kind_and_index_audio():
    kind, idx = receiver_kind_and_index("audio-receiver-1")
    assert kind == "audio"
    assert idx == 0


def test_receiver_kind_and_index_rejects_unknown():
    with pytest.raises(ActivateTranslationError):
        receiver_kind_and_index("sender-1")


def test_apply_activate_updates_correct_video_receiver():
    cfg = RxSystemConfig()
    cfg, joins, alarm = apply_activate_request(
        cfg, "video-receiver-1", _video_sdp(10)
    )
    assert cfg.videos[0].multicast_group_amber == "239.1.1.10"
    assert cfg.videos[0].port == 20010
    assert alarm is None  # only 1 configured, no mismatch yet
    assert len(joins) == 1
    assert joins[0].multicast_group == "239.1.1.10"


def test_apply_activate_kind_mismatch_raises():
    cfg = RxSystemConfig()
    with pytest.raises(ActivateTranslationError):
        apply_activate_request(cfg, "audio-receiver-1", _video_sdp(11))


def test_apply_activate_all_four_video_matching_no_alarm():
    cfg = RxSystemConfig()
    for i in range(4):
        cfg, _, alarm = apply_activate_request(
            cfg, f"video-receiver-{i+1}", _video_sdp(10 + i)
        )
    assert alarm is None


def test_apply_activate_mismatched_format_raises_alarm():
    cfg = RxSystemConfig()
    for i in range(3):
        cfg, _, alarm = apply_activate_request(
            cfg, f"video-receiver-{i+1}", _video_sdp(10 + i)
        )
    uhd_sdp = """v=0
o=- 1 1 IN IP4 192.168.1.13
s=Cam4
c=IN IP4 239.1.1.13/32
t=0 0
m=video 20013 RTP/AVP 112
a=rtpmap:112 raw/90000
a=fmtp:112 sampling=YCbCr-4:2:2; width=3840; height=2160; exactframerate=60; depth=10
"""
    cfg, _, alarm = apply_activate_request(cfg, "video-receiver-4", uhd_sdp)
    assert alarm == "映像フォーマットが4系統で非統一です"


def test_apply_activate_audio_receiver():
    cfg = RxSystemConfig()
    cfg, joins, alarm = apply_activate_request(cfg, "audio-receiver-1", AUDIO_SDP)
    assert cfg.audio.multicast_group_amber == "239.1.1.99"
    assert cfg.audio.channels == 2
    assert alarm is None


def test_apply_deactivate_disables_but_keeps_settings():
    """④-8-4-2-1補足仕様: 無効化してもRX設定値(JSON)は保持する。"""
    cfg = RxSystemConfig()
    cfg, _, _ = apply_activate_request(cfg, "video-receiver-1", _video_sdp(10))

    cfg, leave_request = apply_deactivate_request(cfg, "video-receiver-1")

    assert cfg.videos[0].enabled is False
    assert cfg.videos[0].multicast_group_amber == "239.1.1.10"  # 設定値は保持
    assert cfg.videos[0].port == 20010
    assert leave_request.multicast_group == "239.1.1.10"


def test_apply_deactivate_excludes_receiver_from_mtl_json():
    cfg = RxSystemConfig()
    cfg, _, _ = apply_activate_request(cfg, "video-receiver-1", _video_sdp(10))
    cfg, _ = apply_deactivate_request(cfg, "video-receiver-1")

    rx_sessions = cfg.to_mtl_json()["rx_sessions"]
    assert all(s["ip"][0] != "239.1.1.10" for s in rx_sessions)


def test_apply_enable_reissues_join_from_retained_settings_without_new_sdp():
    """補足仕様: 再有効化時はSDPを取得し直さず保持済み設定値でJoinし直す。"""
    cfg = RxSystemConfig()
    cfg, _, _ = apply_activate_request(cfg, "video-receiver-1", _video_sdp(10))
    cfg, _ = apply_deactivate_request(cfg, "video-receiver-1")

    cfg, join_request = apply_enable_request(cfg, "video-receiver-1")

    assert cfg.videos[0].enabled is True
    assert join_request.multicast_group == "239.1.1.10"
    rx_sessions = cfg.to_mtl_json()["rx_sessions"]
    assert any(s["ip"][0] == "239.1.1.10" for s in rx_sessions)
