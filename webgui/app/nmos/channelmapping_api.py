"""IS-08 Channel Mapping API (`/x-nmos/channelmapping/`) -- presence-only
stub.

Not part of this system's requirements (requirement 4.2.3 / 7.4.2 fixes
audio to 1ch/2ch with no dynamic routing, and the requirements document
never mentions IS-08); added only so `/x-nmos/` advertises the same four
APIs requirement 4.8.4.3.2.2.1 groups under one common port. `io/` reports
zero inputs/outputs because this system exposes no channel-mapping-capable
device -- there is nothing to route.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()

SUPPORTED_VERSIONS = ("v1.0",)


def _check_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=404, detail=f"unsupported IS-08 version: {version}")


@router.get("/x-nmos/channelmapping/")
def channelmapping_index() -> list[str]:
    return [f"{v}/" for v in SUPPORTED_VERSIONS]


@router.get("/x-nmos/channelmapping/{version}/")
def version_index(version: str) -> list[str]:
    _check_version(version)
    return ["io/", "map/"]


@router.get("/x-nmos/channelmapping/{version}/io")
@router.get("/x-nmos/channelmapping/{version}/io/")
def get_io(version: str) -> dict:
    _check_version(version)
    return {"ios": {}}


@router.get("/x-nmos/channelmapping/{version}/map/")
def map_index(version: str) -> list[str]:
    _check_version(version)
    return ["activations/"]


@router.get("/x-nmos/channelmapping/{version}/map/activations")
@router.get("/x-nmos/channelmapping/{version}/map/activations/")
def list_activations(version: str) -> list[dict]:
    _check_version(version)
    return []
