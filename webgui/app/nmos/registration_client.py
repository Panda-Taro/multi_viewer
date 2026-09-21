"""IS-04 Registration API client (requirement 4.7.1.1, 4.7.1.2, 4.7.1.4).

Registers this system as a Node with 1 Device and 5 Receivers on an RDS
(NMOS Registry), then sends a heartbeat every 5 seconds
(POST health/nodes/{id}) to keep the registration alive. If the RDS
responds 404 to a heartbeat (meaning it has forgotten this Node -- e.g. it
restarted, or the registration expired) the client re-registers everything
from scratch.

Two ways to find the RDS, selected by config.nmos.rds_discovery:

- "static": use config.nmos.rds_static (address/port/api_version)
  directly (requirement 4.7.1.2 static mode).
- "auto": browse for `_nmos-register._tcp` via mDNS (mdns_discovery.py,
  requirement 4.7.1.2 / 6.3.1.4 mDNS&DNS-SD mode), select the
  highest-priority result (lowest `pri` TXT value), and register with
  that. If the currently-registered auto-discovered registry stops
  responding to heartbeats, discovery re-runs and fails over to the next
  best one. If nothing is discovered, this is reported (not raised) and
  retried in the background -- it never blocks the WebGUI or the
  Connection API, which run in the same process pool but on the event
  loop, not inside this loop.

This was rolled out in 3 stages (see README.md "mDNS discovery" and
NOTES.md for the reasoning): (1) mdns_discovery.py alone, confirmed
against a real environment before being wired in here; (2) this module's
"auto" branch; (3) WebGUI display (routers/ptp_nmos.py, status_store.py's
discovered_registries/selected_registry fields).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from .. import config_store, log_store
from . import identity as identity_module
from . import mdns_discovery, resources, status_store

HEARTBEAT_INTERVAL_SECONDS = 5.0
RETRY_INTERVAL_SECONDS = 5.0
MDNS_DISCOVERY_TIMEOUT_SECONDS = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _describe_exception(exc: Exception) -> str:
    """`str(exc)` on an httpx.HTTPStatusError only gives the status code,
    not the registry's JSON-schema validation error body -- which is
    usually the only thing that actually explains a 400. Append it when
    present so log entries are useful for diagnosing a real registry's
    complaints without needing to reproduce the request by hand."""
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    body = response.text.strip()
    if not body:
        return str(exc)
    return f"{exc} | response body: {body[:2000]}"


def registration_base_url(rds_static: dict, api_version: str) -> str:
    return f"http://{rds_static['address']}:{rds_static['port']}/x-nmos/registration/{api_version}/"


def _registry_summary(registry: mdns_discovery.DiscoveredRegistry) -> dict:
    return {
        "name": registry.name,
        "addresses": registry.addresses,
        "port": registry.port,
        "priority": registry.priority,
        "base_url": registry.registration_base_url,
    }


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


async def discover_registries(
    timeout_seconds: float = MDNS_DISCOVERY_TIMEOUT_SECONDS,
    discover_fn: Callable[..., list[mdns_discovery.DiscoveredRegistry]] = mdns_discovery.discover_registries,
) -> list[mdns_discovery.DiscoveredRegistry]:
    """Runs the (blocking, thread-based) mDNS browse off the event loop so
    it never stalls the Connection API or WebGUI, which share this
    process's asyncio loop."""
    return await asyncio.to_thread(discover_fn, timeout_seconds=timeout_seconds)


async def run_forever(
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    sleep: Callable[[float], Any] = asyncio.sleep,
    discover_fn: Callable[..., list[mdns_discovery.DiscoveredRegistry]] = mdns_discovery.discover_registries,
) -> None:
    """Supervisor loop. Re-reads config.json every cycle so it follows
    WebGUI-driven changes to the RDS target or discovery mode without
    needing an explicit restart signal. Runs until cancelled."""
    exclude_registry_name: Optional[str] = None  # set for exactly one retry after a heartbeat failure in "auto" mode

    while True:
        config = config_store.load_config()
        nmos_cfg = config["nmos"]
        discovery_mode = nmos_cfg["rds_discovery"]
        selected_registry_name: Optional[str] = None

        if discovery_mode == "static":
            base_url, target_changed = await _resolve_static(nmos_cfg)
        elif discovery_mode == "auto":
            base_url, target_changed, selected_registry_name = await _resolve_auto(
                discover_fn, exclude_names={exclude_registry_name} if exclude_registry_name else None
            )
            exclude_registry_name = None  # only skip the failed one for a single retry
        else:
            status_store.write_status(
                registration_status="disabled",
                discovery_mode=discovery_mode,
                last_error=f"unknown rds_discovery value: {discovery_mode!r}",
                rds_url=None,
            )
            await sleep(RETRY_INTERVAL_SECONDS)
            continue

        if base_url is None:
            await sleep(RETRY_INTERVAL_SECONDS)
            continue

        identity = identity_module.load_identity()
        status_store.write_status(registration_status="registering", discovery_mode=discovery_mode, rds_url=base_url)

        async with client_factory(timeout=5.0) as client:
            try:
                await register_all(client, base_url, config, identity)
            except Exception as exc:  # noqa: BLE001 -- any failure here just means "retry later"
                detail = _describe_exception(exc)
                status_store.write_status(registration_status="error", last_error=detail)
                log_store.log_event("nmos", "error", f"RDSへの登録に失敗しました ({base_url}): {detail}")
                if discovery_mode == "auto":
                    exclude_registry_name = selected_registry_name
                await sleep(RETRY_INTERVAL_SECONDS)
                continue

            status_store.write_status(
                registration_status="registered", last_registered_at=_now_iso(), last_error=None
            )
            log_store.log_event("nmos", "info", f"RDSへの登録に成功しました ({base_url})")

            failed_name = await _heartbeat_loop(
                client,
                base_url,
                identity["node_id"],
                target_changed,
                sleep,
                registry_name=selected_registry_name if discovery_mode == "auto" else None,
            )
            if discovery_mode == "auto" and failed_name is not None:
                exclude_registry_name = failed_name


async def _resolve_static(nmos_cfg: dict) -> tuple[Optional[str], Callable[[dict], bool]]:
    rds = nmos_cfg["rds_static"]
    if not rds.get("address") or not rds.get("port"):
        status_store.write_status(
            registration_status="disabled",
            discovery_mode="static",
            last_error="RDS address/port is not configured",
            rds_url=None,
            discovered_registries=[],
            selected_registry=None,
        )
        return None, _static_target_changed(rds)

    base_url = registration_base_url(rds, rds["api_version"])
    # Clear any stale discovery info left over from a previous "auto" run.
    status_store.write_status(discovery_mode="static", discovered_registries=[], selected_registry=None)
    return base_url, _static_target_changed(rds)


def _static_target_changed(rds_at_registration: dict) -> Callable[[dict], bool]:
    def target_changed(current_cfg: dict) -> bool:
        return (
            current_cfg["nmos"]["rds_discovery"] != "static"
            or current_cfg["nmos"]["rds_static"] != rds_at_registration
        )

    return target_changed


async def _resolve_auto(
    discover_fn: Callable[..., list[mdns_discovery.DiscoveredRegistry]],
    exclude_names: Optional[set[str]] = None,
) -> tuple[Optional[str], Callable[[dict], bool], Optional[str]]:
    status_store.write_status(registration_status="discovering", discovery_mode="auto", last_error=None, rds_url=None)

    registries = await discover_registries(discover_fn=discover_fn)
    best = mdns_discovery.select_best_registry(registries, exclude_names=exclude_names)
    status_store.write_status(
        discovery_mode="auto",
        discovered_registries=[_registry_summary(r) for r in registries],
        selected_registry=_registry_summary(best) if best else None,
    )

    if best is None or best.registration_base_url is None:
        status_store.write_status(
            registration_status="error",
            last_error="mDNSでRDS(_nmos-register._tcp)が見つかりませんでした。再試行します。",
            rds_url=None,
        )
        return None, _auto_target_changed(), None

    return best.registration_base_url, _auto_target_changed(), best.name


def _auto_target_changed() -> Callable[[dict], bool]:
    def target_changed(current_cfg: dict) -> bool:
        # Re-discovery/failover of the *currently registered* registry
        # happens on heartbeat failure (see _heartbeat_loop), not
        # proactively every heartbeat tick -- only an operator switching
        # away from "auto" interrupts an otherwise-healthy session early.
        return current_cfg["nmos"]["rds_discovery"] != "auto"

    return target_changed


async def _heartbeat_loop(
    client: httpx.AsyncClient,
    base_url: str,
    node_id: str,
    target_changed: Callable[[dict], bool],
    sleep: Callable,
    registry_name: Optional[str] = None,
) -> Optional[str]:
    """Sends heartbeats until one fails, the RDS forgets us, or the
    operator changes the discovery target in the WebGUI -- any of which
    returns control to run_forever() so it re-evaluates config from
    scratch. Returns `registry_name` if a heartbeat genuinely failed
    (network error or the RDS forgetting us) -- the signal run_forever()
    uses, in "auto" mode, to exclude this registry from the very next
    discovery/selection attempt (the failover path). Returns None on a
    clean exit (operator switched discovery target) or when not running
    in "auto" mode (registry_name left as None by the caller)."""
    while True:
        await sleep(HEARTBEAT_INTERVAL_SECONDS)

        current_cfg = config_store.load_config()
        if target_changed(current_cfg):
            return None  # target changed; let run_forever() pick up the new config

        try:
            accepted = await send_heartbeat(client, base_url, node_id)
        except Exception as exc:  # noqa: BLE001
            detail = _describe_exception(exc)
            status_store.write_status(registration_status="error", last_error=detail)
            log_store.log_event("nmos", "warning", f"ハートビート送信に失敗しました: {detail}")
            return registry_name

        if not accepted:
            log_store.log_event("nmos", "warning", "RDSが本ノードを認識していません。再登録します。")
            return registry_name

        status_store.write_status(registration_status="registered", last_heartbeat_at=_now_iso())
