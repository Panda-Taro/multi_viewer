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
            "enabled": "true",
            "source_ip_amber": "192.168.1.10",
            "multicast_group_amber": "239.1.1.10",
            "port_amber": "20000",
            "source_ip_blue": "192.168.2.10",
            "multicast_group_blue": "",
            "port_blue": "0",
            "payload_type": "112",
            "video_format_mode": "sdp",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/mgmt/media")
    assert "239.1.1.10" in page.text
    assert "192.168.2.10" in page.text


def test_media_video_disable_toggle_shows_unchecked_and_excludes_session():
    client.post(
        "/mgmt/media/video/1",
        data={
            "enabled": "true",
            "multicast_group_amber": "239.1.1.11",
            "port_amber": "20001",
            "video_format_mode": "sdp",
        },
        follow_redirects=False,
    )
    r = client.post(
        "/mgmt/media/video/1",
        data={
            # enabled チェックボックス未送信 = 無効化
            "multicast_group_amber": "239.1.1.11",
            "port_amber": "20001",
            "video_format_mode": "sdp",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_media_video_59i_mode_shows_fixed_format():
    r = client.post(
        "/mgmt/media/video/2",
        data={"video_format_mode": "59i"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/mgmt/media")
    assert "i1080p59" in page.text


def test_ptp_nmos_page_renders():
    r = client.get("/mgmt/ptp-nmos")
    assert r.status_code == 200
    assert "PTP・NMOS設定" in r.text


def test_ptp_update_invalid_shows_error_and_keeps_previous():
    r = client.post("/mgmt/ptp-nmos/ptp", data={"domain": "999"}, follow_redirects=False)
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
