"""webgui/app/routers/logs.py

対応要件: ④-8 (大画面ログビューア + エクスポート/ダウンロード)、⑤
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from ..log_store import log_store

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/mgmt/logs", response_class=HTMLResponse)
def logs_page(request: Request, component: str | None = None, level: str | None = None):
    entries = log_store.filter(component=component, level=level)
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active_nav": "logs",
            "entries": list(reversed(entries[-500:])),
            "component": component or "",
            "level": level or "",
        },
    )


@router.get("/mgmt/logs/export")
def export_logs():
    text = log_store.export_text()
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": "attachment; filename=multiviewer.log"},
    )
