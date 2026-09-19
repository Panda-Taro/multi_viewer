import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest
from sdp import parse_sdp, SdpParseError


VIDEO_SDP = """v=0
o=- 123456 789012 IN IP4 192.168.1.50
s=Camera1
c=IN IP4 239.1.1.10/32
t=0 0
m=video 20000 RTP/AVP 112
a=rtpmap:112 raw/90000
a=fmtp:112 sampling=YCbCr-4:2:2; width=1920; height=1080; interlace; exactframerate=60000/1001; depth=10; colorimetry=BT709
a=source-filter: incl IN IP4 239.1.1.10 192.168.1.50
"""

AUDIO_SDP = """v=0
o=- 123456 789012 IN IP4 192.168.1.51
s=Audio1
c=IN IP4 239.1.1.20/32
t=0 0
m=audio 20100 RTP/AVP 111
a=rtpmap:111 L24/48000/2
a=ptime:1
"""

PROGRESSIVE_SDP = """v=0
o=- 1 1 IN IP4 10.0.0.5
s=Cam2
c=IN IP4 239.5.5.5/32
t=0 0
m=video 20001 RTP/AVP 112
a=rtpmap:112 raw/90000
a=fmtp:112 sampling=YCbCr-4:2:2; width=3840; height=2160; exactframerate=60; depth=10
"""


def test_parse_video_sdp_basic_fields():
    p = parse_sdp(VIDEO_SDP)
    assert p.media_type == "video"
    assert p.multicast_group == "239.1.1.10"
    assert p.source_ip == "192.168.1.50"
    assert p.port == 20000
    assert p.payload_type == 112


def test_parse_video_sdp_derives_mtl_format():
    p = parse_sdp(VIDEO_SDP)
    assert p.width == 1920
    assert p.height == 1080
    assert p.interlaced is True
    assert abs(p.fps - 59.94) < 0.01
    assert p.video_format == "i1080p59"
    assert p.pg_format == "YUV_422_10bit"


def test_parse_progressive_uhd_sdp():
    p = parse_sdp(PROGRESSIVE_SDP)
    assert p.width == 3840
    assert p.height == 2160
    assert p.interlaced is False
    assert p.video_format == "p2160p60"


def test_parse_audio_sdp():
    p = parse_sdp(AUDIO_SDP)
    assert p.media_type == "audio"
    assert p.multicast_group == "239.1.1.20"
    assert p.sample_rate == 48000
    assert p.channels == 2
    assert p.packet_time_ms == 1.0


def test_parse_rejects_sdp_without_media_line():
    with pytest.raises(SdpParseError):
        parse_sdp("v=0\no=- 1 1 IN IP4 1.2.3.4\ns=x\nt=0 0\n")


def test_parse_rejects_empty_string():
    with pytest.raises(SdpParseError):
        parse_sdp("")


def test_source_filter_overrides_o_line_source_ip():
    sdp = VIDEO_SDP.replace("192.168.1.50", "10.10.10.10", 1)  # only o= line changes... but replace(1) hits first occurrence which is o=
    p = parse_sdp(sdp)
    # o= line now has 10.10.10.10 but source-filter still has 192.168.1.50 -> should win
    assert p.source_ip == "192.168.1.50"
