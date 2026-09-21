"""A minimal, self-built mock of an NMOS RDS (Registry) -- just enough of
the IS-04 Registration API and Query API to integration-test our
registration client end to end: register resources, list them back via
Query, heartbeat, and simulate the registry forgetting a Node (404).

This is NOT the official AMWA nmos-cpp Registry or the NMOS Testing Tool.
Building/running those was not available in this environment (no network
access to fetch/build a C++ project during this session). See README.md
"結合テストについて" for what this integration test does and does not
prove, and what remains unverified against a real/official registry.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

RESOURCE_TYPES_PLURAL = {"node": "nodes", "device": "devices", "receiver": "receivers", "sender": "senders"}


def create_mock_rds() -> FastAPI:
    app = FastAPI(title="Mock NMOS RDS (test-only)")
    store: dict[str, dict[str, dict]] = {"nodes": {}, "devices": {}, "receivers": {}, "senders": {}}
    app.state.store = store

    @app.post("/x-nmos/registration/{version}/resource")
    async def register_resource(version: str, request: Request):
        body = await request.json()
        resource_type = body.get("type")
        data = body.get("data")
        if resource_type not in RESOURCE_TYPES_PLURAL:
            raise HTTPException(status_code=400, detail=f"unknown resource type: {resource_type}")
        store[RESOURCE_TYPES_PLURAL[resource_type]][data["id"]] = data
        return {"type": resource_type, "data": data}

    @app.post("/x-nmos/registration/{version}/health/nodes/{node_id}")
    def heartbeat(version: str, node_id: str):
        if node_id not in store["nodes"]:
            raise HTTPException(status_code=404, detail="node not registered")
        return {"health": "2026-01-01T00:00:00Z"}

    @app.get("/x-nmos/query/{version}/{resource_type_plural}")
    def query_list(version: str, resource_type_plural: str):
        if resource_type_plural not in store:
            raise HTTPException(status_code=404, detail="unknown resource collection")
        return list(store[resource_type_plural].values())

    @app.delete("/x-nmos/registration/{version}/resource/nodes/{node_id}", include_in_schema=False)
    def forget_node(version: str, node_id: str):
        """Test-only helper (not part of the real IS-04 API): simulates
        the registry losing track of a Node, so tests can exercise the
        re-registration path (a 404 on heartbeat)."""
        store["nodes"].pop(node_id, None)
        return {"status": "forgotten"}

    return app
