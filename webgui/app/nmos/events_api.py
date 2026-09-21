"""IS-07 Events API (`/x-nmos/events/`) -- presence-only stub.

Not part of this system's requirements (the requirements document never
mentions IS-07); added only so `/x-nmos/` advertises the same four APIs
(channelmapping/connection/events/node) requirement 4.8.4.3.2.2.1 groups
under one common port, matching how other NMOS nodes self-describe. This
system has no IS-07 event sources (it is a receiver, not a sensor/control
device), so `sources/` and `flows/` are legitimately empty rather than
unimplemented -- there is nothing else to build here without inventing a
feature outside this project's scope.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()

SUPPORTED_VERSIONS = ("v1.0",)


def _check_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=404, detail=f"unsupported IS-07 version: {version}")


@router.get("/x-nmos/events/")
def events_index() -> list[str]:
    return [f"{v}/" for v in SUPPORTED_VERSIONS]


@router.get("/x-nmos/events/{version}/")
def version_index(version: str) -> list[str]:
    _check_version(version)
    return ["sources/", "flows/"]


@router.get("/x-nmos/events/{version}/sources")
@router.get("/x-nmos/events/{version}/sources/")
def list_sources(version: str) -> list[dict]:
    _check_version(version)
    return []


@router.get("/x-nmos/events/{version}/flows")
@router.get("/x-nmos/events/{version}/flows/")
def list_flows(version: str) -> list[dict]:
    _check_version(version)
    return []
