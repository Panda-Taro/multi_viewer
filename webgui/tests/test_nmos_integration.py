"""Integration test: our registration client against a locally-run mock
RDS (see mock_rds.py for what it is and is not -- notably, NOT the
official AMWA nmos-cpp Registry). Talks to it via httpx.ASGITransport
(in-process ASGI call, no real socket/port), which exercises the exact
same request/response cycle our registration client would make over a
real network, just without needing an actually-bound TCP port.

This is the "結合テスト" requested for step 2a. See README.md for what it
covers and what remains unverified against a real/official registry.
"""
from __future__ import annotations

import httpx
import pytest

from mock_rds import create_mock_rds

BASE_URL = "http://mock-rds.test/x-nmos/registration/v1.3/"


def _client_for(mock_app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://mock-rds.test")


@pytest.mark.asyncio
async def test_node_device_and_5_receivers_are_visible_via_query_api(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import registration_client

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    mock_app = create_mock_rds()
    async with _client_for(mock_app) as client:
        await registration_client.register_all(client, BASE_URL, config, identity)

        nodes = (await client.get("/x-nmos/query/v1.3/nodes")).json()
        devices = (await client.get("/x-nmos/query/v1.3/devices")).json()
        receivers = (await client.get("/x-nmos/query/v1.3/receivers")).json()

    assert len(nodes) == 1
    assert nodes[0]["id"] == identity["node_id"]

    assert len(devices) == 1
    assert devices[0]["id"] == identity["device_id"]
    assert devices[0]["node_id"] == identity["node_id"]

    assert len(receivers) == 5
    receiver_ids = {r["id"] for r in receivers}
    assert receiver_ids == set(identity["video_receiver_ids"]) | set(identity["audio_receiver_ids"])

    video_receivers = [r for r in receivers if r["format"] == "urn:x-nmos:format:video"]
    audio_receivers = [r for r in receivers if r["format"] == "urn:x-nmos:format:audio"]
    assert len(video_receivers) == 4
    assert len(audio_receivers) == 1
    for r in receivers:
        assert r["device_id"] == identity["device_id"]


@pytest.mark.asyncio
async def test_heartbeat_accepted_after_registration(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import registration_client

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    mock_app = create_mock_rds()
    async with _client_for(mock_app) as client:
        await registration_client.register_all(client, BASE_URL, config, identity)
        accepted = await registration_client.send_heartbeat(client, BASE_URL, identity["node_id"])

    assert accepted is True


@pytest.mark.asyncio
async def test_re_registration_after_registry_forgets_node(isolated_dirs):
    """Simulates the RDS restarting and losing its registration (a 404 on
    heartbeat), and confirms register_all() successfully re-registers
    everything -- the recovery path requirement 5.4 (robustness) implies
    and this system's run_forever() loop relies on."""
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import registration_client

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    mock_app = create_mock_rds()
    async with _client_for(mock_app) as client:
        await registration_client.register_all(client, BASE_URL, config, identity)

        await client.delete(f"/x-nmos/registration/v1.3/resource/nodes/{identity['node_id']}")
        forgotten = await registration_client.send_heartbeat(client, BASE_URL, identity["node_id"])
        assert forgotten is False

        await registration_client.register_all(client, BASE_URL, config, identity)
        re_accepted = await registration_client.send_heartbeat(client, BASE_URL, identity["node_id"])
        assert re_accepted is True

        nodes = (await client.get("/x-nmos/query/v1.3/nodes")).json()
    assert len(nodes) == 1
