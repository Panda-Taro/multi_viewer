from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from .. import log_store

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()


@router.get("/mgmt/logs")
def logs_page(request: Request):
    return templates.TemplateResponse(
        "logs.html",
        {"request": request, "active_page": "logs"},
    )


@router.get("/api/logs")
def get_logs(limit: int = 500):
    return {"events": log_store.read_events(limit=min(limit, log_store.MAX_LINES_KEPT))}


@router.get("/api/logs/export")
def export_logs():
    path = log_store.export_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return FileResponse(path, filename="multiviewer-events.log", media_type="text/plain")
