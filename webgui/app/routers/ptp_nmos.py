"""webgui/app/routers/ptp_nmos.py

対応要件: ④-8-4-3 PTP・NMOS設定 (Receiver設定とは別の専用1画面)

更新版要件定義書「4.8 WebGUI」で、PTP設定・NMOS設定はメディアストリーム
設定(Receiver)とは独立した「1つの画面ですべて表示できるように密度を高く
する」専用画面として区分されたため、従来 webgui/app/routers/media.py に
同居していたPTP/NMOS設定ルートをここへ分離した。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config_store import store, ConfigValidationError, NmosSettings

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/mgmt/ptp-nmos", response_class=HTMLResponse)
def ptp_nmos_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "ptp_nmos.html",
        {
            "active_nav": "ptp_nmos",
            "ptp": store.media.ptp,
            "nmos": store.nmos,
            "error": error,
        },
    )


@router.post("/mgmt/ptp-nmos/ptp")
def update_ptp(domain: int = Form(24)):
    try:
        store.update_ptp_domain(domain)
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/ptp-nmos?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/ptp-nmos", status_code=303)


@router.post("/mgmt/ptp-nmos/nmos")
def update_nmos(
    discovery_mode: str = Form("mdns"),
    registration_address: str = Form(""),
    registration_port: int = Form(0),
    is04_version: str = Form("v1.3"),
    is05_version: str = Form("v1.1"),
    node_api_port: str = Form("auto"),
    registration_api_port: str = Form("auto"),
):
    candidate = NmosSettings(
        discovery_mode=discovery_mode,
        registration_address=registration_address,
        registration_port=registration_port,
        is04_version=is04_version,
        is05_version=is05_version,
        node_api_port=node_api_port,
        registration_api_port=registration_api_port,
    )
    try:
        store.update_nmos(candidate)
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/ptp-nmos?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/ptp-nmos", status_code=303)
