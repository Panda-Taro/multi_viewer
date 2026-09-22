"""IS-04 Node API (`/x-nmos/node/`).

Step 2a's original scope explicitly left the Node API out ("P2P mode is
out of scope; static registration via the RDS is the priority path" --
see NOTES.md). It is added here because a real Node compared against this
system's `/x-nmos/` root is expected to advertise
channelmapping/connection/events/node together (requirement
4.8.4.3.2.2.1 groups them under one common port), and because this system
already builds the exact same resource JSON for Registration -- serving it
here too is nearly free and gives external NMOS controllers a working P2P
discovery path (requirement 4.7.1.4) as a side effect.

Read-only: an external controller can discover this Node's Device and
Receivers here, but all control still happens through the IS-05
Connection API (connection_api.py), matching requirement 4.7.3 (Receiver
functionality only, no Sender).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import config_store
from . import identity as identity_module
from . import resources

router = APIRouter()

SUPPORTED_VERSIONS = tuple(resources.IS04_VERSIONS)  # v1.1, v1.2, v1.3 (requirement 4.7.1.3)


def _check_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=404, detail=f"unsupported IS-04 version: {version}")


def _current_config_and_identity() -> tuple[dict, dict]:
    with config_store.locked_config_optional_write() as (config, save):
        if identity_module.ensure_identity(config):
            save()
        identity = config["identity"]
    return config, identity


@router.get("/x-nmos/node/")
def node_index() -> list[str]:
    return [f"{v}/" for v in SUPPORTED_VERSIONS]


@router.get("/x-nmos/node/{version}/")
def version_index(version: str) -> list[str]:
    _check_version(version)
    return ["self/", "devices/", "sources/", "flows/", "senders/", "receivers/"]


@router.get("/x-nmos/node/{version}/self")
@router.get("/x-nmos/node/{version}/self/")
def get_self(version: str) -> dict:
    _check_version(version)
    config, identity = _current_config_and_identity()
    return resources.build_node(config, identity)


@router.get("/x-nmos/node/{version}/devices")
@router.get("/x-nmos/node/{version}/devices/")
def list_devices(version: str) -> list[dict]:
    _check_version(version)
    config, identity = _current_config_and_identity()
    return [resources.build_device(config, identity)]


@router.get("/x-nmos/node/{version}/devices/{device_id}")
@router.get("/x-nmos/node/{version}/devices/{device_id}/")
def get_device(version: str, device_id: str) -> dict:
    _check_version(version)
    config, identity = _current_config_and_identity()
    if device_id != identity["device_id"]:
        raise HTTPException(status_code=404, detail="unknown device id")
    return resources.build_device(config, identity)


@router.get("/x-nmos/node/{version}/receivers")
@router.get("/x-nmos/node/{version}/receivers/")
def list_receivers(version: str) -> list[dict]:
    _check_version(version)
    config, identity = _current_config_and_identity()
    return resources.build_all_receivers(config, identity)


@router.get("/x-nmos/node/{version}/receivers/{receiver_id}")
@router.get("/x-nmos/node/{version}/receivers/{receiver_id}/")
def get_receiver(version: str, receiver_id: str) -> dict:
    _check_version(version)
    config, identity = _current_config_and_identity()
    lookup = identity_module.receiver_lookup(identity)
    if receiver_id not in lookup:
        raise HTTPException(status_code=404, detail="unknown receiver id")
    kind, index = lookup[receiver_id]
    if kind == "video":
        return resources.build_video_receiver(index, config, identity)
    return resources.build_audio_receiver(index, config, identity)


# This system has no Sender resources (requirement 4.7.3 / 8.1.2: Receiver
# functionality only) and does not itself decode ST2110 into IS-04 Source/
# Flow resources (that would describe media *this Node originates*, which
# it does not -- it only receives). Both collections are legitimately
# empty rather than unimplemented.
@router.get("/x-nmos/node/{version}/senders")
@router.get("/x-nmos/node/{version}/senders/")
def list_senders(version: str) -> list[dict]:
    _check_version(version)
    return []


@router.get("/x-nmos/node/{version}/sources")
@router.get("/x-nmos/node/{version}/sources/")
def list_sources(version: str) -> list[dict]:
    _check_version(version)
    return []


@router.get("/x-nmos/node/{version}/flows")
@router.get("/x-nmos/node/{version}/flows/")
def list_flows(version: str) -> list[dict]:
    _check_version(version)
    return []
