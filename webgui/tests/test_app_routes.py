import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_dir = tmp_path / "etc-multiviewer"
    log_dir = tmp_path / "var-log-multiviewer"
    netplan_dir = tmp_path / "etc-netplan"
    config_dir.mkdir()
    log_dir.mkdir()
    netplan_dir.mkdir()

    monkeypatch.setenv("MULTIVIEWER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MULTIVIEWER_LOG_DIR", str(log_dir))
    monkeypatch.setenv("MULTIVIEWER_NETPLAN_DIR", str(netplan_dir))

    # Ensure a completely fresh import graph so every module's path
    # constants are derived from the env vars set above, not from
    # whatever a previous test's import left cached.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_root_redirects_to_mgmt(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/mgmt/"


def test_dashboard_page_renders(client):
    response = client.get("/mgmt/")
    assert response.status_code == 200
    assert "ダッシュボード" in response.text


def test_dashboard_status_api(client):
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    body = response.json()
    assert len(body["video_receivers"]) == 4
    assert len(body["audio_receivers"]) == 1
    assert body["ptp_lock_state"] == "not_implemented"


def test_media_page_renders(client):
    response = client.get("/mgmt/media")
    assert response.status_code == 200
    assert "映像Receiver" in response.text


def test_update_video_receiver(client):
    payload = {
        "enabled": True,
        "payload_id": 96,
        "video_format": "59.94i",
        "color_format": "YCbCr4:2:2_10bit_SDR",
        "amber": {"source_ip": "10.0.0.1", "group_ip": "239.1.1.1", "port": 5000},
        "blue": {"source_ip": "10.0.1.1", "group_ip": "239.1.1.2", "port": 5000},
    }
    response = client.put("/api/media/video/1", json=payload)
    assert response.status_code == 200
    assert response.json()["receiver"]["enabled"] is True

    # Persisted: fetching the dashboard status reflects the change.
    status = client.get("/api/dashboard/status").json()
    assert status["video_receivers"][0]["enabled"] is True


def test_update_video_receiver_rejects_out_of_range_index(client):
    payload = {
        "enabled": True,
        "payload_id": 96,
        "video_format": "59.94i",
        "color_format": "YCbCr4:2:2_10bit_SDR",
        "amber": {"source_ip": "", "group_ip": "", "port": 0},
        "blue": {"source_ip": "", "group_ip": "", "port": 0},
    }
    response = client.put("/api/media/video/5", json=payload)
    assert response.status_code == 404


def test_update_video_receiver_rejects_invalid_video_format(client):
    payload = {
        "enabled": True,
        "payload_id": 96,
        "video_format": "not-a-real-format",
        "color_format": "YCbCr4:2:2_10bit_SDR",
        "amber": {"source_ip": "", "group_ip": "", "port": 0},
        "blue": {"source_ip": "", "group_ip": "", "port": 0},
    }
    response = client.put("/api/media/video/1", json=payload)
    assert response.status_code == 422


def test_update_ptp(client):
    response = client.put("/api/ptp", json={"domain": 5})
    assert response.status_code == 200
    assert response.json()["ptp"]["domain"] == 5


def test_ptp_nmos_page_renders(client):
    response = client.get("/mgmt/ptp-nmos")
    assert response.status_code == 200
    assert "NMOS登録・発見状態" in response.text


def test_nmos_status_endpoint_returns_defaults(client):
    response = client.get("/api/nmos/status")
    assert response.status_code == 200
    body = response.json()
    assert body["registration_status"] == "disabled"
    assert body["discovered_registries"] == []
    assert body["selected_registry"] is None


def test_display_mode_update(client):
    response = client.post("/api/display", json={"mode": "single", "single_source": 3})
    assert response.status_code == 200
    body = client.get("/api/dashboard/status").json()
    assert body["display_mode"] == "single"
    assert body["single_source"] == 3


def test_network_apply_requires_confirmed_risk_for_control(client):
    payload = {
        "target": "control",
        "interface": "eth0",
        "mode": "static",
        "address": "192.168.1.5",
        "prefix": 24,
        "confirmed_risk": False,
    }
    response = client.post("/api/network/apply", json=payload)
    assert response.status_code == 400


def test_network_apply_writes_config_and_reboots(client):
    payload = {
        "target": "media_amber",
        "interface": "eth1",
        "mode": "static",
        "address": "192.168.20.5",
        "prefix": 24,
    }
    response = client.post("/api/network/apply", json=payload)
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "rebooting"

    status = client.get("/api/dashboard/status").json()
    assert status["nics"]["media_amber"]["interface"] == "eth1"


def test_network_apply_can_be_called_again_immediately(client):
    payload = {
        "target": "media_amber",
        "interface": "eth1",
        "mode": "dhcp",
    }
    first = client.post("/api/network/apply", json=payload)
    assert first.status_code == 200

    # No pending/confirm state exists any more, so a second apply is not
    # blocked -- the operator is trusted to know what they changed.
    second = client.post("/api/network/apply", json=payload)
    assert second.status_code == 200


def test_logs_roundtrip(client):
    client.put("/api/ptp", json={"domain": 9})  # generates a log event
    response = client.get("/api/logs")
    assert response.status_code == 200
    events = response.json()["events"]
    assert any("PTP" in e["message"] for e in events)

    export_response = client.get("/api/logs/export")
    assert export_response.status_code == 200


def test_viewer_placeholder_page(client):
    response = client.get("/monitor01/")
    assert response.status_code == 200
    assert "視聴" in response.text
