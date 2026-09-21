from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config_store
from .routers import dashboard, logs, media, network, ptp_nmos

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="MultiViewer WebGUI")

app.mount("/mgmt/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(dashboard.router)
app.include_router(media.router)
app.include_router(ptp_nmos.router)
app.include_router(network.router)
app.include_router(logs.router)


@app.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/mgmt/")


@app.get("/monitor01/")
def viewer_placeholder(request: Request):
    """Placeholder for the WHEP viewing page (requirement 4.6.2 / 6.4.2).

    Real WebRTC playback is wired up in step 5 once MediaMTX and the
    compositor exist; for step 1 this route only confirms the URL and
    shows the display-mode UI stub so the navigation path required by
    4.8.4.1.1.2 exists end to end.
    """
    config = config_store.load_config()
    return templates.TemplateResponse(
        "viewer.html", {"request": request, "config": config}
    )
