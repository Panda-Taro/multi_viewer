"""The NMOS service's FastAPI app: hosts the IS-05 Connection API and runs
the IS-04 Registration client as a background task for the process
lifetime.

This is a separate FastAPI app/process from the WebGUI (see
webgui/app/nmos_main.py and systemd/multiviewer-nmos.service), listening
on config.nmos.common_port -- the "channelmapping/connection/events/node"
port requirement 4.8.4.3.2.2.1 asks the operator to configure, distinct
from the WebGUI's port 80. See NOTES.md for why this is a separate process
rather than a second listener bolted onto the WebGUI.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

from fastapi import FastAPI

from . import channelmapping_api, connection_api, events_api, node_api, registration_client


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(registration_client.run_forever())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="MultiViewer NMOS Service", lifespan=lifespan)

    @app.get("/x-nmos/")
    def root_index() -> list[str]:
        # Advertise all four APIs requirement 4.8.4.3.2.2.1 groups under
        # one common port, matching how other NMOS nodes self-describe.
        # events/channelmapping are presence-only stubs (see their
        # modules' docstrings); connection/node are real.
        return ["channelmapping/", "connection/", "events/", "node/"]

    app.include_router(connection_api.router)
    app.include_router(node_api.router)
    app.include_router(events_api.router)
    app.include_router(channelmapping_api.router)
    return app


app = create_app()
