"""webgui/app/routers/media.py

対応要件: ④-8 メディアストリーム設定 (Receiver/PTP/NMOS)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config_store import store, ConfigValidationError, NmosSettings

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/mgmt/media", response_class=HTMLResponse)
def media_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "media.html",
        {
            "active_nav": "media",
            "videos": store.media.videos,
            "audio": store.media.audio,
            "ptp": store.media.ptp,
            "nmos": store.nmos,
            "error": error,
        },
    )


@router.post("/mgmt/media/video/{index}")
def update_video(
    index: int,
    source_ip: str = Form(""),
    multicast_group_amber: str = Form(""),
    multicast_group_blue: str = Form(""),
    port: int = Form(0),
    payload_type: int = Form(112),
    video_format: str = Form("i1080p59"),
    pg_format: str = Form("YUV_422_10bit"),
):
    try:
        store.update_video_receiver(
            index,
            source_ip=source_ip,
            multicast_group_amber=multicast_group_amber,
            multicast_group_blue=multicast_group_blue,
            port=port,
            payload_type=payload_type,
            video_format=video_format,
            pg_format=pg_format,
        )
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/media", status_code=303)


@router.post("/mgmt/media/audio")
def update_audio(
    source_ip: str = Form(""),
    multicast_group_amber: str = Form(""),
    multicast_group_blue: str = Form(""),
    port: int = Form(0),
    payload_type: int = Form(111),
    sample_rate: int = Form(48000),
    packet_time_ms: float = Form(1.0),
):
    try:
        store.update_audio_receiver(
            source_ip=source_ip,
            multicast_group_amber=multicast_group_amber,
            multicast_group_blue=multicast_group_blue,
            port=port,
            payload_type=payload_type,
            sample_rate=sample_rate,
            packet_time_ms=packet_time_ms,
        )
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/media", status_code=303)


@router.post("/mgmt/media/ptp")
def update_ptp(domain: int = Form(24)):
    try:
        store.update_ptp_domain(domain)
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/media", status_code=303)


@router.post("/mgmt/media/nmos")
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
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/media", status_code=303)
