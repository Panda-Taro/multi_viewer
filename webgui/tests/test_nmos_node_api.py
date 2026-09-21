import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def node_client(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module, node_api

    identity = identity_module.load_identity()

    app = FastAPI()
    app.include_router(node_api.router)
    client = TestClient(app)
    client.identity = identity
    client.config_store = config_store
    return client


def test_node_index_lists_all_supported_versions(node_client):
    response = node_client.get("/x-nmos/node/")
    assert response.status_code == 200
    assert response.json() == ["v1.1/", "v1.2/", "v1.3/"]


def test_unsupported_version_is_404(node_client):
    response = node_client.get("/x-nmos/node/v9.9/")
    assert response.status_code == 404


def test_self_returns_node_resource(node_client):
    response = node_client.get("/x-nmos/node/v1.3/self")
    assert response.status_code == 200
    node = response.json()
    assert node["id"] == node_client.identity["node_id"]
    assert node["label"] == "MultiViewer"


def test_devices_lists_the_one_device(node_client):
    response = node_client.get("/x-nmos/node/v1.3/devices")
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["id"] == node_client.identity["device_id"]


def test_get_device_by_id(node_client):
    device_id = node_client.identity["device_id"]
    response = node_client.get(f"/x-nmos/node/v1.3/devices/{device_id}")
    assert response.status_code == 200
    assert response.json()["id"] == device_id


def test_get_device_unknown_id_is_404(node_client):
    response = node_client.get("/x-nmos/node/v1.3/devices/not-a-real-id")
    assert response.status_code == 404


def test_receivers_lists_all_5(node_client):
    response = node_client.get("/x-nmos/node/v1.3/receivers")
    assert response.status_code == 200
    receivers = response.json()
    assert len(receivers) == 5
    ids = {r["id"] for r in receivers}
    assert ids == set(node_client.identity["video_receiver_ids"]) | set(
        node_client.identity["audio_receiver_ids"]
    )


def test_get_receiver_by_id(node_client):
    receiver_id = node_client.identity["video_receiver_ids"][0]
    response = node_client.get(f"/x-nmos/node/v1.3/receivers/{receiver_id}")
    assert response.status_code == 200
    assert response.json()["id"] == receiver_id
    assert response.json()["format"] == "urn:x-nmos:format:video"


def test_senders_sources_flows_are_empty(node_client):
    for collection in ("senders", "sources", "flows"):
        response = node_client.get(f"/x-nmos/node/v1.3/{collection}")
        assert response.status_code == 200
        assert response.json() == []
