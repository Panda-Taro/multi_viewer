import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def nmos_client(isolated_dirs):
    from app import config_store
    from app.nmos import connection_api, identity as identity_module

    connection_api.reset_staged_cache()
    identity = identity_module.load_identity()

    app = FastAPI()
    app.include_router(connection_api.router)
    client = TestClient(app)
    client.identity = identity
    client.video_id = identity["video_receiver_ids"][0]
    client.audio_id = identity["audio_receiver_ids"][0]
    client.config_store = config_store
    return client


def test_connection_index_lists_supported_versions(nmos_client):
    response = nmos_client.get("/x-nmos/connection/")
    assert response.status_code == 200
    assert response.json() == ["v1.0/", "v1.1/"]


def test_unsupported_version_returns_404(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v9.9/")
    assert response.status_code == 404


def test_list_receivers_returns_all_5(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v1.1/single/receivers/")
    assert response.status_code == 200
    ids = response.json()
    assert len(ids) == 5
    assert f"{nmos_client.video_id}/" in ids


def test_unknown_receiver_id_returns_404(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v1.1/single/receivers/not-a-real-id/staged/")
    assert response.status_code == 404


def test_get_constraints_is_unconstrained_2_legs(nmos_client):
    response = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/constraints/"
    )
    assert response.json() == [{}, {}]


def test_get_transport_type(nmos_client):
    response = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/transporttype/"
    )
    assert response.json() == "urn:x-nmos:transport:rtp.mcast"


def test_staged_initially_mirrors_active_config(nmos_client):
    response = nmos_client.get(f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/")
    staged = response.json()
    assert staged["master_enable"] is False
    assert len(staged["transport_params"]) == 2


def test_patch_staged_without_activation_does_not_touch_config(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200
    staged = response.json()
    assert staged["master_enable"] is True
    assert staged["transport_params"][0]["source_ip"] == "192.168.10.1"

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["video"][0]["enabled"] is False  # unchanged: not activated yet


def test_patch_staged_with_activate_immediate_applies_to_config(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200
    assert response.json()["activation"]["activation_time"] is not None

    config = nmos_client.config_store.load_config()
    receiver = config["receivers"]["video"][0]
    assert receiver["enabled"] is True
    assert receiver["amber"]["source_ip"] == "192.168.10.1"
    assert receiver["amber"]["group_ip"] == "239.1.1.1"
    assert receiver["amber"]["port"] == 5004
    assert receiver["blue"]["source_ip"] == "192.168.20.1"
    assert receiver["sdp_source"] == "nmos"

    active = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/active/"
    ).json()
    assert active["master_enable"] is True
    assert active["transport_params"][0]["source_ip"] == "192.168.10.1"


def test_patch_staged_with_transport_file_parses_sdp_and_activates(nmos_client):
    sdp_text = (
        "v=0\r\n"
        "o=- 1 1 IN IP4 192.168.10.1\r\n"
        "s=Video Sender\r\n"
        "t=0 0\r\n"
        "m=video 5004 RTP/AVP 96\r\n"
        "c=IN IP4 239.5.5.5/32\r\n"
        "a=source-filter: incl IN IP4 239.5.5.5 192.168.10.9\r\n"
    )
    patch = {
        "master_enable": True,
        "transport_file": {"data": sdp_text, "type": "application/sdp"},
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200

    config = nmos_client.config_store.load_config()
    receiver = config["receivers"]["video"][0]
    assert receiver["amber"]["group_ip"] == "239.5.5.5"
    assert receiver["amber"]["source_ip"] == "192.168.10.9"
    assert receiver["payload_id"] == 96
    assert receiver["nmos_sdp"] == sdp_text


def test_scheduled_activation_mode_is_rejected(nmos_client):
    patch = {"activation": {"mode": "activate_scheduled_absolute", "requested_time": "10:0"}}
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 400


def test_transport_params_must_have_two_legs(nmos_client):
    patch = {"transport_params": [{"source_ip": "1.2.3.4"}]}
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 400


def test_master_enable_false_disables_receiver_on_activation(nmos_client):
    enable_patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=enable_patch
    )

    disable_patch = {"master_enable": False, "activation": {"mode": "activate_immediate"}}
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=disable_patch
    )

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["video"][0]["enabled"] is False


def test_audio_receiver_activation(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "10.0.0.1", "multicast_ip": "239.9.9.9", "destination_port": 6000},
            {"source_ip": "10.0.1.1", "multicast_ip": "239.9.9.10", "destination_port": 6000},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.audio_id}/staged/", json=patch
    )
    assert response.status_code == 200

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["audio"][0]["enabled"] is True
    assert config["receivers"]["audio"][0]["amber"]["group_ip"] == "239.9.9.9"
