from app.nmos.sdp import parse_sdp

SINGLE_LEG_SDP = """v=0
o=- 123456 123456 IN IP4 192.168.10.1
s=Video Sender
t=0 0
m=video 5004 RTP/AVP 96
c=IN IP4 239.1.1.1/32
a=source-filter: incl IN IP4 239.1.1.1 192.168.10.1
a=rtpmap:96 raw/90000
a=fmtp:96 sampling=YCbCr-4:2:2; width=1920; height=1080
"""

DUAL_LEG_SDP = """v=0
o=- 123456 123456 IN IP4 192.168.10.1
s=Video Sender (redundant)
t=0 0
m=video 5004 RTP/AVP 96
c=IN IP4 239.1.1.1/32
a=source-filter: incl IN IP4 239.1.1.1 192.168.10.1
m=video 5004 RTP/AVP 96
c=IN IP4 239.1.2.1/32
a=source-filter: incl IN IP4 239.1.2.1 192.168.20.1
"""

AUDIO_SDP = """v=0
o=- 1 1 IN IP4 192.168.10.2
s=Audio Sender
t=0 0
m=audio 6000 RTP/AVP 97
c=IN IP4 239.1.1.2/32
a=source-filter: incl IN IP4 239.1.1.2 192.168.10.2
"""


def test_parse_single_leg_sdp():
    legs = parse_sdp(SINGLE_LEG_SDP)
    assert len(legs) == 1
    leg = legs[0]
    assert leg["media"] == "video"
    assert leg["port"] == 5004
    assert leg["payload_type"] == 96
    assert leg["group_ip"] == "239.1.1.1"
    assert leg["source_ip"] == "192.168.10.1"


def test_parse_dual_leg_sdp():
    legs = parse_sdp(DUAL_LEG_SDP)
    assert len(legs) == 2
    assert legs[0]["group_ip"] == "239.1.1.1"
    assert legs[0]["source_ip"] == "192.168.10.1"
    assert legs[1]["group_ip"] == "239.1.2.1"
    assert legs[1]["source_ip"] == "192.168.20.1"


def test_parse_audio_sdp():
    legs = parse_sdp(AUDIO_SDP)
    assert len(legs) == 1
    assert legs[0]["media"] == "audio"
    assert legs[0]["payload_type"] == 97


def test_parse_empty_sdp_returns_empty_list():
    assert parse_sdp("") == []


def test_parse_sdp_without_source_filter_leaves_source_ip_none():
    text = "m=video 5004 RTP/AVP 96\nc=IN IP4 239.1.1.1/32\n"
    legs = parse_sdp(text)
    assert legs[0]["source_ip"] is None
    assert legs[0]["group_ip"] == "239.1.1.1"
