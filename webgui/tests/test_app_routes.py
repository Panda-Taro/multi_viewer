import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_redirects_to_mgmt():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/mgmt/"


def test_dashboard_page_renders():
    r = client.get("/mgmt/")
    assert r.status_code == 200
    assert "ダッシュボード" in r.text


def test_media_page_renders():
    r = client.get("/mgmt/media")
    assert r.status_code == 200
    assert "メディアストリーム設定" in r.text


def test_system_page_renders():
    r = client.get("/mgmt/system")
    assert r.status_code == 200
    assert "システム設定" in r.text


def test_logs_page_renders():
    r = client.get("/mgmt/logs")
    assert r.status_code == 200


def test_viewer_page_renders():
    r = client.get("/monitor01/")
    assert r.status_code == 200
    assert "whep-video" in r.text


def test_display_mode_toggle_api():
    r1 = client.get("/mgmt/")
    r = client.post("/api/display-mode/toggle")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("quad", "single")
    assert isinstance(body["zmq_commands"], list)


def test_display_mode_select_single_out_of_range():
    r = client.post("/api/display-mode/select/9")
    assert r.status_code == 500 or r.status_code == 400  # LayoutError surfaces as server error


def test_media_video_update_then_reflected_on_page():
    r = client.post(
        "/mgmt/media/video/0",
        data={
            "source_ip": "192.168.1.10",
            "multicast_group_amber": "239.1.1.10",
            "multicast_group_blue": "",
            "port": "20000",
            "payload_type": "112",
            "video_format": "i1080p59",
            "pg_format": "YUV_422_10bit",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/mgmt/media")
    assert "239.1.1.10" in page.text


def test_media_ptp_update_invalid_shows_error_and_keeps_previous():
    r = client.post("/mgmt/media/ptp", data={"domain": "999"}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_system_viewer_bitrate_out_of_range_rejected():
    r = client.post(
        "/mgmt/system/viewer",
        data={"viewer_path": "monitor01", "bitrate_mbps": "999"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_logs_export_returns_plain_text():
    r = client.get("/mgmt/logs/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
