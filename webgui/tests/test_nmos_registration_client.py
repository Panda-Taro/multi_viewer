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


@pytest.mark.asyncio
async def test_run_forever_reregisters_when_config_changes_mid_session(isolated_dirs):
    """Regression test for the reported bug: a manual WebGUI save (or an
    IS-05 activate) while a session is healthily heartbeating must reach
    the RDS as an updated resource -- otherwise external NMOS controllers
    watching this Node/Receiver via the RDS never see the change, even
    though our own status shows "registered" the whole time. Before the
    fix, only send_heartbeat() (no resource data) was called between the
    initial registration and a reconnect."""
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
        if sleep_calls["count"] == 2:
            # Simulate a manual WebGUI save landing between heartbeat ticks.
            cfg = config_store.load_config()
            cfg["receivers"]["video"][0]["enabled"] = True
            config_store.save_config(cfg)
        elif sleep_calls["count"] >= 3:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(client_factory=client_factory, sleep=fake_sleep)

    # 7 for the initial registration, then 7 more once the config change
    # was detected -- not just a bare heartbeat.
    assert call_log.count("register") == 14
    assert call_log.count("heartbeat") == 2

    status = status_store.read_status()
    assert status["registration_status"] == "registered"
    assert status["last_error"] is None


def _fake_registry(name, host, port, pri, module):
    return module.mdns_discovery.DiscoveredRegistry(
        name=name,
        addresses=[host],
        port=port,
        server=f"{name}.local.",
        txt={"pri": str(pri), "api_ver": "v1.3", "api_proto": "http"},
    )


@pytest.mark.asyncio
async def test_run_forever_auto_mode_registers_with_discovered_registry(isolated_dirs):
    from app import config_store
    from app.nmos import registration_client, status_store

    config = config_store.load_config()
    config["nmos"]["rds_discovery"] = "auto"
    config_store.save_config(config)

    registry = _fake_registry("rds-a", "10.0.0.1", 8010, pri=100, module=registration_client)

    def discover_fn(timeout_seconds):
        return [registry]

    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/resource" in request.url.path:
            call_log.append(str(request.url))
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(
            client_factory=client_factory, sleep=fake_sleep, discover_fn=discover_fn
        )

    assert len(call_log) == 7
    assert all("10.0.0.1:8010" in url for url in call_log)

    status = status_store.read_status()
    assert status["discovery_mode"] == "auto"
    assert status["selected_registry"]["name"] == "rds-a"
    assert status["discovered_registries"] == [
        {"name": "rds-a", "addresses": ["10.0.0.1"], "port": 8010, "priority": 100,
         "base_url": "http://10.0.0.1:8010/x-nmos/registration/v1.3/"}
    ]


@pytest.mark.asyncio
async def test_run_forever_auto_mode_picks_highest_priority(isolated_dirs):
    from app import config_store
    from app.nmos import registration_client, status_store

    config = config_store.load_config()
    config["nmos"]["rds_discovery"] = "auto"
    config_store.save_config(config)

    low_priority = _fake_registry("low-pri", "10.0.0.2", 8020, pri=200, module=registration_client)
    high_priority = _fake_registry("high-pri", "10.0.0.1", 8010, pri=10, module=registration_client)

    def discover_fn(timeout_seconds):
        return [low_priority, high_priority]

    registered_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/resource" in request.url.path:
            registered_hosts.append(request.url.host)
        return httpx.Response(200, json={})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    async def fake_sleep(seconds: float) -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(
            client_factory=client_factory, sleep=fake_sleep, discover_fn=discover_fn
        )

    assert set(registered_hosts) == {"10.0.0.1"}  # the pri=10 registry, not pri=200

    status = status_store.read_status()
    assert status["selected_registry"]["name"] == "high-pri"


@pytest.mark.asyncio
async def test_run_forever_auto_mode_no_registries_reports_error_and_retries(isolated_dirs):
    from app import config_store
    from app.nmos import registration_client, status_store

    config = config_store.load_config()
    config["nmos"]["rds_discovery"] = "auto"
    config_store.save_config(config)

    def discover_fn(timeout_seconds):
        return []

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(sleep=fake_sleep, discover_fn=discover_fn)

    status = status_store.read_status()
    assert status["registration_status"] == "error"
    assert "見つかりませんでした" in status["last_error"]
    assert status["discovered_registries"] == []
    assert status["selected_registry"] is None
    assert sleep_calls["count"] >= 2  # it kept retrying rather than crashing


@pytest.mark.asyncio
async def test_run_forever_auto_mode_fails_over_to_next_registry_after_heartbeat_failure(isolated_dirs):
    from app import config_store
    from app.nmos import registration_client, status_store

    config = config_store.load_config()
    config["nmos"]["rds_discovery"] = "auto"
    config_store.save_config(config)

    # primary has the better (lower) priority; secondary should only be
    # used once primary starts failing heartbeats.
    primary = _fake_registry("primary", "10.0.0.1", 8010, pri=10, module=registration_client)
    secondary = _fake_registry("secondary", "10.0.0.2", 8020, pri=50, module=registration_client)

    def discover_fn(timeout_seconds):
        return [primary, secondary]

    registered_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/resource" in request.url.path:
            registered_hosts.append(request.url.host)
            return httpx.Response(200, json={})
        if "/health/" in request.url.path:
            if request.url.host == "10.0.0.1":
                return httpx.Response(404)  # primary has stopped recognising us
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        # 1st sleep: inside the primary's heartbeat loop (triggers the
        # 404 above). 2nd sleep: inside the secondary's heartbeat loop,
        # after failover -- stop there.
        if sleep_calls["count"] >= 3:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await registration_client.run_forever(
            client_factory=client_factory, sleep=fake_sleep, discover_fn=discover_fn
        )

    # Registered with the primary first, then -- after its heartbeat 404'd
    # -- re-registered with the secondary instead of the primary again.
    assert registered_hosts[:7] == ["10.0.0.1"] * 7
    assert registered_hosts[7:14] == ["10.0.0.2"] * 7

    status = status_store.read_status()
    assert status["selected_registry"]["name"] == "secondary"
