import asyncio
import json

import httpx
import pytest

# `registration_client` is imported locally inside each test function
# (after `isolated_dirs` has pointed env vars at a throwaway directory),
# rather than once at module level. A module-level import here would bind
# to whatever `app.config_store` object existed at test *collection* time;
# other fixtures in this suite (see test_app_routes.py's `client` fixture)
# purge and re-import `app.*` between tests, which would silently orphan
# that early-bound reference from the object `isolated_dirs` actually
# reloads.


class RecordingTransport(httpx.MockTransport):
    """Wraps httpx.MockTransport to also record every request made, so
    tests can assert on call order (Node, then Device, then each
    Receiver) without depending on real network I/O."""

    def __init__(self, handler):
        self.calls: list[httpx.Request] = []

        def recording_handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)

        super().__init__(recording_handler)


@pytest.mark.asyncio
async def test_register_all_posts_node_device_then_5_receivers(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import registration_client

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = RecordingTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await registration_client.register_all(client, "http://rds.example/x-nmos/registration/v1.3/", config, identity)

    assert len(transport.calls) == 7  # 1 node + 1 device + 4 video receivers + 1 audio receiver
    types = [json.loads(c.content)["type"] for c in transport.calls]
    assert types[0] == "node"
    assert types[1] == "device"
    assert types[2:].count("receiver") == 5


@pytest.mark.asyncio
async def test_register_all_raises_on_http_error(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import registration_client

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await registration_client.register_all(
                client, "http://rds.example/x-nmos/registration/v1.3/", config, identity
            )


@pytest.mark.asyncio
async def test_send_heartbeat_returns_true_on_200():
    from app.nmos import registration_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"health": "2020-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await registration_client.send_heartbeat(client, "http://rds.example/x-nmos/registration/v1.3/", "node-1")
    assert result is True


@pytest.mark.asyncio
async def test_send_heartbeat_returns_false_on_404():
    from app.nmos import registration_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await registration_client.send_heartbeat(client, "http://rds.example/x-nmos/registration/v1.3/", "node-1")
    assert result is False


@pytest.mark.asyncio
async def test_send_heartbeat_raises_on_server_error():
    from app.nmos import registration_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await registration_client.send_heartbeat(
                client, "http://rds.example/x-nmos/registration/v1.3/", "node-1"
            )


@pytest.mark.asyncio
async def test_run_forever_reports_disabled_when_rds_not_configured(isolated_dirs):
    from app.nmos import registration_client, status_store

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(sleep=fake_sleep)

    status = status_store.read_status()
    assert status["registration_status"] == "disabled"
    assert "not configured" in status["last_error"]


@pytest.mark.asyncio
async def test_run_forever_registers_and_heartbeats_then_stops(isolated_dirs):
    from app import config_store
    from app.nmos import registration_client, status_store

    config = config_store.load_config()
    config["nmos"]["rds_discovery"] = "static"
    config["nmos"]["rds_static"] = {"address": "rds.example", "port": 8010, "api_version": "v1.3"}
    config_store.save_config(config)

    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/resource" in request.url.path:
            call_log.append("register")
            return httpx.Response(200, json={})
        if "/health/" in request.url.path:
            call_log.append("heartbeat")
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:  # allow one heartbeat cycle, then stop the test
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(client_factory=client_factory, sleep=fake_sleep)

    assert call_log.count("register") == 7  # node + device + 5 receivers
    assert call_log.count("heartbeat") == 1

    status = status_store.read_status()
    assert status["registration_status"] == "registered"
