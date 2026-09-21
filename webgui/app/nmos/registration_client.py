"""IS-04 Registration API client (requirement 4.7.1.1, 4.7.1.2 static mode,
4.7.1.4 heartbeat).

Registers this system as a Node with 1 Device and 5 Receivers on an
external RDS (NMOS Registry) using the static IP/port configured in
nmos.rds_static, then sends a heartbeat every 5 seconds
(POST health/nodes/{id}) as required by the Registration API to keep the
registration alive. If the RDS responds 404 to a heartbeat (meaning it has
forgotten this Node -- e.g. it restarted, or the registration expired) the
client re-registers everything from scratch.

Only static discovery is implemented here; mDNS & DNS-SD discovery
(rds_discovery="auto") is step 2b and is reported as "disabled" via
status_store in the meantime.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from .. import config_store, log_store
from . import identity as identity_module
from . import resources, status_store

HEARTBEAT_INTERVAL_SECONDS = 5.0
RETRY_INTERVAL_SECONDS = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def registration_base_url(rds_static: dict, api_version: str) -> str:
    return f"http://{rds_static['address']}:{rds_static['port']}/x-nmos/registration/{api_version}/"


async def register_resource(client: httpx.AsyncClient, base_url: str, resource_type: str, data: dict) -> None:
    response = await client.post(f"{base_url}resource", json={"type": resource_type, "data": data})
    response.raise_for_status()


async def register_all(client: httpx.AsyncClient, base_url: str, config: dict, identity: dict) -> None:
    """Registers Node, then Device, then all 5 Receivers, in that order
    (each references the previous by id, so the RDS must see them in this
    order for a strict/validating registry)."""
    await register_resource(client, base_url, "node", resources.build_node(config, identity))
    await register_resource(client, base_url, "device", resources.build_device(config, identity))
    for receiver in resources.build_all_receivers(config, identity):
        await register_resource(client, base_url, "receiver", receiver)


async def send_heartbeat(client: httpx.AsyncClient, base_url: str, node_id: str) -> bool:
    """Returns True if the heartbeat was accepted, False if the RDS does
    not know this Node (HTTP 404 -- caller should re-register). Raises for
    any other failure (network error, 5xx, etc.)."""
    response = await client.post(f"{base_url}health/nodes/{node_id}")
    if response.status_code == 200:
        return True
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return False


async def run_forever(
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Supervisor loop. Re-reads config.json every cycle so it follows
    WebGUI-driven changes to the RDS target or discovery mode without
    needing an explicit restart signal. Runs until cancelled."""
    while True:
        config = config_store.load_config()
        nmos_cfg = config["nmos"]

        if nmos_cfg["rds_discovery"] != "static":
            status_store.write_status(
                registration_status="disabled",
                last_error="rds_discovery='auto' (mDNS&DNS-SD) is not implemented yet (step 2b)",
            )
            await sleep(RETRY_INTERVAL_SECONDS)
            continue

        rds = nmos_cfg["rds_static"]
        if not rds.get("address") or not rds.get("port"):
            status_store.write_status(
                registration_status="disabled", last_error="RDS address/port is not configured"
            )
            await sleep(RETRY_INTERVAL_SECONDS)
            continue

        identity = identity_module.load_identity()
        base_url = registration_base_url(rds, rds["api_version"])
        status_store.write_status(registration_status="registering", rds_url=base_url)

        async with client_factory(timeout=5.0) as client:
            try:
                await register_all(client, base_url, config, identity)
            except Exception as exc:  # noqa: BLE001 -- any failure here just means "retry later"
                status_store.write_status(registration_status="error", last_error=str(exc))
                log_store.log_event("nmos", "error", f"RDSへの登録に失敗しました ({base_url}): {exc}")
                await sleep(RETRY_INTERVAL_SECONDS)
                continue

            status_store.write_status(
                registration_status="registered", last_registered_at=_now_iso(), last_error=None
            )
            log_store.log_event("nmos", "info", f"RDSへの登録に成功しました ({base_url})")

            await _heartbeat_loop(client, base_url, identity["node_id"], rds, sleep)


async def _heartbeat_loop(
    client: httpx.AsyncClient, base_url: str, node_id: str, rds_at_registration: dict, sleep: Callable
) -> None:
    """Sends heartbeats until one fails, the RDS forgets us, or the
    operator changes the RDS target in the WebGUI -- any of which returns
    control to run_forever() so it re-evaluates config from scratch."""
    while True:
        await sleep(HEARTBEAT_INTERVAL_SECONDS)

        current_cfg = config_store.load_config()
        if (
            current_cfg["nmos"]["rds_discovery"] != "static"
            or current_cfg["nmos"]["rds_static"] != rds_at_registration
        ):
            return  # target changed; let run_forever() pick up the new config

        try:
            accepted = await send_heartbeat(client, base_url, node_id)
        except Exception as exc:  # noqa: BLE001
            status_store.write_status(registration_status="error", last_error=str(exc))
            log_store.log_event("nmos", "warning", f"ハートビート送信に失敗しました: {exc}")
            return

        if not accepted:
            log_store.log_event("nmos", "warning", "RDSが本ノードを認識していません。再登録します。")
            return

        status_store.write_status(registration_status="registered", last_heartbeat_at=_now_iso())
