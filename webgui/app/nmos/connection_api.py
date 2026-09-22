"""IS-05 (Connection API) -- Receiver-only, requirement 4.7.2 / 6.3.2.

Implements the `single/receivers/{id}/{constraints,staged,active,
transporttype}` resources of the AMWA NMOS IS-05 Connection API for our 5
fixed Receivers (no Sender resources -- this system never sends).

`staged` state lives in memory only (per-process); `active` state is
derived from config.json (config_store), since that is what the rest of
this system (WebGUI, and later the MTL bridge) reads. Activating a staged
change (`activation.mode == "activate_immediate"`) copies the staged
transport params into config.json and marks the receiver's `sdp_source` as
"nmos" (requirement 4.8.4.2.1.3 -- the WebGUI reflects this in real time by
polling the same config).

Because `staged` is a cache seeded from config.json only on first access,
anything that writes a receiver's config.json fields through a path other
than this module's own `_activate()` (currently: media.py's manual-save
endpoints) MUST call `invalidate_staged()`/`invalidate_staged_for()`
afterwards. Otherwise a later activate_immediate that doesn't itself
change any value (e.g. a controller's periodic re-sync) would silently
overwrite that other write with the stale cached staged values -- this
was a real bug (see NOTES.md "config.jsonをsource of truthとして保つ"),
and the invariant this module now maintains is: config.json's `enabled`
and endpoint fields are always the source of truth; staged/active exist to
reflect and stage changes to it, never to silently regress it.

Only `activate_immediate` is supported; scheduled activation
(`activate_scheduled_absolute`/`_relative`) is rejected with 400 -- no
external controller behaviour in this NMOS-Testing-Tool-free environment
was available to validate a scheduler against, so it was left out rather
than shipped unverified. See NOTES.md.

Route paths: per the official AMWA IS-05 RAML (nmos-device-connection-
management ConnectionAPI.raml), `single`, `single/receivers`,
`single/receivers/{id}`, and the leaf resources
(`constraints`/`staged`/`active`/`transporttype`) do NOT have a trailing
slash in their canonical URL -- only the top-level "list what's available"
resources (`/x-nmos/connection/`, `/x-nmos/connection/{version}/`) do,
since those return directory-style listings whose *entries* are
slash-suffixed strings (e.g. `["single/"]`), which is a different thing
from the URL used to fetch that listing. An earlier revision registered
every route with a trailing slash, which is spec-incorrect; a real NMOS
controller requesting the canonical (no-slash) URL got a 307 from
FastAPI's default redirect_slashes behaviour, its PATCH did not follow
the redirect, and the failure never reached this module's own code (so
nothing was logged here) -- see NOTES.md for the incident this fixes.
Every affected route below is now registered under BOTH forms (with and
without the trailing slash) so neither direction ever needs a redirect.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException

from .. import config_store, log_store
from . import identity as identity_module
from . import sdp as sdp_module

router = APIRouter()

SUPPORTED_VERSIONS = ("v1.0", "v1.1")

_staged_lock = threading.Lock()
_staged: dict[str, dict] = {}


def _tai_now() -> str:
    now = time.time()
    sec = int(now)
    nsec = int((now - sec) * 1e9)
    return f"{sec}:{nsec}"


def _check_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=404, detail=f"unsupported IS-05 version: {version}")


def _receiver_kind_index(receiver_id: str) -> tuple[str, int]:
    identity = identity_module.load_identity()
    lookup = identity_module.receiver_lookup(identity)
    if receiver_id not in lookup:
        raise HTTPException(status_code=404, detail="unknown receiver id")
    return lookup[receiver_id]


def _receiver_config(config: dict, kind: str, index: int) -> dict:
    return config["receivers"][kind][index]


def _leg_from_config(endpoint: dict, enabled: bool) -> dict:
    return {
        "source_ip": endpoint["source_ip"] or None,
        "multicast_ip": endpoint["group_ip"] or None,
        "interface_ip": "auto",
        "destination_port": endpoint["port"] or "auto",
        "rtp_enabled": enabled,
    }


def _active_from_config(receiver_cfg: dict) -> dict:
    has_sdp = bool(receiver_cfg.get("nmos_sdp"))
    return {
        "sender_id": receiver_cfg.get("sender_id"),
        "master_enable": receiver_cfg["enabled"],
        "activation": {"mode": None, "requested_time": None, "activation_time": None},
        "transport_file": {
            "data": receiver_cfg.get("nmos_sdp"),
            "type": "application/sdp" if has_sdp else None,
        },
        "transport_params": [
            _leg_from_config(receiver_cfg["amber"], receiver_cfg["enabled"]),
            _leg_from_config(receiver_cfg["blue"], receiver_cfg["enabled"]),
        ],
    }


def _get_or_init_staged(receiver_id: str, kind: str, index: int) -> dict:
    with _staged_lock:
        if receiver_id not in _staged:
            config = config_store.load_config()
            _staged[receiver_id] = _active_from_config(_receiver_config(config, kind, index))
        return _staged[receiver_id]


def reset_staged_cache() -> None:
    """Test hook: clears the in-memory staged state between test cases."""
    with _staged_lock:
        _staged.clear()


def invalidate_staged(receiver_id: str) -> None:
    """Drops the cached `staged` value for one receiver, if any, so the
    next GET/PATCH re-initializes it from the current config.json.

    Must be called by anything that writes a receiver's config.json fields
    *outside* the IS-05 activate path (currently: media.py's manual-save
    endpoints) -- otherwise a stale in-memory `staged` can silently
    overwrite that write on a later activate_immediate that doesn't itself
    change any value (e.g. a controller's periodic re-sync). See NOTES.md
    "config.jsonをsource of truthとして保つ" for the bug this fixes and
    why a targeted invalidation was chosen over redesigning staged to
    merge live config on every read.
    """
    with _staged_lock:
        _staged.pop(receiver_id, None)


def invalidate_staged_for(kind: str, index: int) -> None:
    """Convenience wrapper for callers (media.py) that only know a
    receiver by its config.json position (0-based `index` within
    `receivers.video` or `receivers.audio`), not its NMOS UUID."""
    identity = identity_module.load_identity()
    ids_by_kind = {
        "video": identity["video_receiver_ids"],
        "audio": identity["audio_receiver_ids"],
    }
    try:
        receiver_id = ids_by_kind[kind][index]
    except (KeyError, IndexError):
        return
    invalidate_staged(receiver_id)


@router.get("/x-nmos/connection/")
def connection_index() -> list[str]:
    return [f"{v}/" for v in SUPPORTED_VERSIONS]


@router.get("/x-nmos/connection/{version}/")
def version_index(version: str) -> list[str]:
    _check_version(version)
    return ["single/"]


@router.get("/x-nmos/connection/{version}/single")
@router.get("/x-nmos/connection/{version}/single/")
def single_index(version: str) -> list[str]:
    _check_version(version)
    return ["receivers/"]


@router.get("/x-nmos/connection/{version}/single/receivers")
@router.get("/x-nmos/connection/{version}/single/receivers/")
def list_receivers(version: str) -> list[str]:
    _check_version(version)
    identity = identity_module.load_identity()
    ids = list(identity["video_receiver_ids"]) + list(identity["audio_receiver_ids"])
    return [f"{rid}/" for rid in ids]


@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}")
@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/")
def receiver_index(version: str, receiver_id: str) -> list[str]:
    _check_version(version)
    _receiver_kind_index(receiver_id)
    return ["constraints/", "staged/", "active/", "transporttype/"]


@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/constraints")
@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/constraints/")
def get_constraints(version: str, receiver_id: str) -> list[dict]:
    _check_version(version)
    _receiver_kind_index(receiver_id)
    return [{}, {}]  # unconstrained, one object per leg (Amber, Blue)


@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/transporttype")
@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/transporttype/")
def get_transport_type(version: str, receiver_id: str) -> str:
    _check_version(version)
    _receiver_kind_index(receiver_id)
    return "urn:x-nmos:transport:rtp.mcast"


@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/staged")
@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/staged/")
def get_staged(version: str, receiver_id: str) -> dict:
    _check_version(version)
    kind, index = _receiver_kind_index(receiver_id)
    return _get_or_init_staged(receiver_id, kind, index)


@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/active")
@router.get("/x-nmos/connection/{version}/single/receivers/{receiver_id}/active/")
def get_active(version: str, receiver_id: str) -> dict:
    _check_version(version)
    kind, index = _receiver_kind_index(receiver_id)
    config = config_store.load_config()
    return _active_from_config(_receiver_config(config, kind, index))


@router.patch("/x-nmos/connection/{version}/single/receivers/{receiver_id}/staged")
@router.patch("/x-nmos/connection/{version}/single/receivers/{receiver_id}/staged/")
def patch_staged(version: str, receiver_id: str, patch: dict = Body(...)) -> dict:
    _check_version(version)
    kind, index = _receiver_kind_index(receiver_id)
    staged = _get_or_init_staged(receiver_id, kind, index)

    with _staged_lock:
        if "sender_id" in patch:
            staged["sender_id"] = patch["sender_id"]

        if "master_enable" in patch:
            staged["master_enable"] = bool(patch["master_enable"])

        if "transport_params" in patch:
            incoming = patch["transport_params"]
            if not isinstance(incoming, list) or len(incoming) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="transport_params must be a 2-element array (leg 0 = Amber, leg 1 = Blue)",
                )
            for leg, update in zip(staged["transport_params"], incoming):
                leg.update(update)

        if "transport_file" in patch:
            staged["transport_file"] = patch["transport_file"] or {"data": None, "type": None}
            data = staged["transport_file"].get("data")
            if data:
                _apply_sdp_to_staged_transport_params(staged, data)

        if "activation" in patch and patch["activation"]:
            mode = patch["activation"].get("mode")
            if mode not in (None, "activate_immediate"):
                raise HTTPException(
                    status_code=400,
                    detail=f"activation mode '{mode}' is not supported yet (only activate_immediate)",
                )
            staged["activation"] = {
                "mode": mode,
                "requested_time": patch["activation"].get("requested_time"),
                "activation_time": None,
            }
            if mode == "activate_immediate":
                try:
                    _activate(kind, index, receiver_id, staged)
                except OSError as exc:
                    raise HTTPException(
                        status_code=500, detail=f"設定の保存に失敗しました: {exc}"
                    ) from exc
                staged["activation"]["activation_time"] = _tai_now()

        return staged


def _apply_sdp_to_staged_transport_params(staged: dict, sdp_text: str) -> None:
    legs = sdp_module.parse_sdp(sdp_text)
    if not legs:
        return
    amber = legs[0]
    blue = legs[1] if len(legs) > 1 else legs[0]
    for leg_state, parsed in zip(staged["transport_params"], (amber, blue)):
        if parsed.get("source_ip"):
            leg_state["source_ip"] = parsed["source_ip"]
        if parsed.get("group_ip"):
            leg_state["multicast_ip"] = parsed["group_ip"]
        if parsed.get("port"):
            leg_state["destination_port"] = parsed["port"]


def _resolve_video_format(current: Optional[str], leg: Optional[sdp_module.SdpLeg]) -> str:
    """Always returns a concrete value ("59.94i"/"59.94p"), never the old
    literal "sdp" placeholder (removed per operator request -- the field
    must always display something real, updated live from the SDP's
    actual scan type when NMOS-driven). If the SDP's fmtp conveyed a scan
    type, use it; otherwise keep whatever concrete value is already
    there, falling back to the spec default (requirement 6.1.1) only for
    an invalid/legacy stored value."""
    if leg is not None and leg.get("interlaced") is not None:
        return "59.94i" if leg["interlaced"] else "59.94p"
    if current in ("59.94i", "59.94p"):
        return current
    return "59.94i"


def _resolve_packet_time(current: Optional[str], leg: Optional[sdp_module.SdpLeg]) -> str:
    """Same idea as `_resolve_video_format`, for audio packet time."""
    if leg is not None and leg.get("packet_time_ms") is not None:
        return "0.125ms" if abs(leg["packet_time_ms"] - 0.125) < 0.01 else "1ms"
    if current in ("1ms", "0.125ms"):
        return current
    return "1ms"


def _activate(kind: str, index: int, receiver_id: str, staged: dict) -> None:
    payload_type: Optional[int] = None
    legs: list[sdp_module.SdpLeg] = []
    sdp_text = staged.get("transport_file", {}).get("data")
    if sdp_text:
        legs = sdp_module.parse_sdp(sdp_text)
        if legs and legs[0].get("payload_type") is not None:
            payload_type = legs[0]["payload_type"]

    with config_store.locked_config() as config:
        receiver_cfg = _receiver_config(config, kind, index)

        receiver_cfg["enabled"] = staged["master_enable"]
        for endpoint_key, leg in zip(("amber", "blue"), staged["transport_params"]):
            endpoint = receiver_cfg[endpoint_key]
            endpoint["source_ip"] = leg.get("source_ip") or ""
            endpoint["group_ip"] = leg.get("multicast_ip") or ""
            port = leg.get("destination_port")
            if isinstance(port, int):
                endpoint["port"] = port
        if payload_type is not None:
            receiver_cfg["payload_id"] = payload_type
        receiver_cfg["sdp_source"] = "nmos"
        receiver_cfg["nmos_sdp"] = sdp_text
        receiver_cfg["sender_id"] = staged.get("sender_id")

        # A controller that only PATCHes bare transport_params (no SDP text)
        # has no format info for us to derive -- first_leg is None in that
        # case, and the resolver functions above just keep whatever concrete
        # value is already stored.
        first_leg = legs[0] if legs else None
        if kind == "video":
            receiver_cfg["video_format"] = _resolve_video_format(receiver_cfg.get("video_format"), first_leg)
        else:
            receiver_cfg["sampling"] = "48kHz"  # the only rate this system supports
            receiver_cfg["packet_time"] = _resolve_packet_time(receiver_cfg.get("packet_time"), first_leg)

    log_store.log_event(
        "nmos",
        "info",
        f"IS-05 activateにより{kind} Receiver{index + 1}の設定を更新しました",
        receiver_id=receiver_id,
        master_enable=staged["master_enable"],
    )
