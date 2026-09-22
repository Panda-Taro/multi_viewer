from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.nmos import channelmapping_api, events_api


def test_service_root_lists_all_4_apis(isolated_dirs):
    from app.nmos import service

    app = service.create_app()
    with TestClient(app) as client:
        response = client.get("/x-nmos/")
    assert response.status_code == 200
    assert response.json() == ["channelmapping/", "connection/", "events/", "node/"]


def test_events_index_and_empty_collections():
    app = FastAPI()
    app.include_router(events_api.router)
    client = TestClient(app)

    assert client.get("/x-nmos/events/").json() == ["v1.0/"]
    assert client.get("/x-nmos/events/v1.0/").json() == ["sources/", "flows/"]
    assert client.get("/x-nmos/events/v1.0/sources").json() == []
    assert client.get("/x-nmos/events/v1.0/flows").json() == []
    assert client.get("/x-nmos/events/v9.9/").status_code == 404


def test_channelmapping_index_and_empty_io():
    app = FastAPI()
    app.include_router(channelmapping_api.router)
    client = TestClient(app)

    assert client.get("/x-nmos/channelmapping/").json() == ["v1.0/"]
    assert client.get("/x-nmos/channelmapping/v1.0/").json() == ["io/", "map/"]
    assert client.get("/x-nmos/channelmapping/v1.0/io").json() == {"ios": {}}
    assert client.get("/x-nmos/channelmapping/v1.0/map/activations").json() == []
    # Regression: "map" (no trailing slash) must be served directly too.
    r = client.get("/x-nmos/channelmapping/v1.0/map", follow_redirects=False)
    assert r.status_code == 200
    assert r.json() == ["activations/"]
    assert client.get("/x-nmos/channelmapping/v9.9/").status_code == 404
