import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mtl"))

import tempfile

os.environ["MTL_RX_CONFIG"] = os.path.join(tempfile.gettempdir(), "mv_test_rx_config.json")
os.environ["MULTIVIEWER_LOG"] = os.path.join(tempfile.gettempdir(), "mv_test_bridge.log")

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

VIDEO_SDP = """v=0
o=- 1 1 IN IP4 192.168.1.10
s=Cam
c=IN IP4 239.1.1.10/32
t=0 0
m=video 20000 RTP/AVP 112
a=rtpmap:112 raw/90000
a=fmtp:112 sampling=YCbCr-4:2:2; width=1920; height=1080; interlace; exactframerate=60000/1001; depth=10
"""


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_activate_video_receiver_success():
    r = client.post(
        "/nmos/activate",
        json={"receiver_role": "video-receiver-1", "sdp": VIDEO_SDP},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["receiver_role"] == "video-receiver-1"
    assert len(body["igmp_joins"]) == 2


def test_activate_rejects_bad_sdp():
    r = client.post(
        "/nmos/activate",
        json={"receiver_role": "video-receiver-2", "sdp": "not an sdp"},
    )
    assert r.status_code == 400


def test_activate_rejects_kind_mismatch():
    r = client.post(
        "/nmos/activate",
        json={"receiver_role": "audio-receiver-1", "sdp": VIDEO_SDP},
    )
    assert r.status_code == 400


def test_state_endpoint_reflects_activation():
    client.post(
        "/nmos/activate",
        json={"receiver_role": "video-receiver-3", "sdp": VIDEO_SDP.replace("20000", "20002").replace("239.1.1.10", "239.1.1.12")},
    )
    r = client.get("/state")
    assert r.status_code == 200
    sessions = r.json()["rx_sessions"]
    assert any("239.1.1.12" in s["dip"] for s in sessions)
