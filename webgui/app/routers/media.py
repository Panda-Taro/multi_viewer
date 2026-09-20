"""webgui/app/routers/media.py

対応要件: ④-8-4-2 メディアストリーム設定 (Receiverのみ。PTP・NMOS設定は
④-8-4-3として別画面 webgui/app/routers/ptp_nmos.py に分離した)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config_store import store, ConfigValidationError
from ..nmos_sync import notify_receiver_toggle

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
            "error": error,
        },
    )


@router.post("/mgmt/media/video/{index}")
def update_video(
    index: int,
    enabled: bool = Form(False),
    source_ip: str = Form(""),
    multicast_group_amber: str = Form(""),
    multicast_group_blue: str = Form(""),
    port: int = Form(0),
    payload_type: int = Form(112),
    video_format_mode: str = Form("sdp"),
):
    try:
        store.update_video_receiver(
            index,
            enabled=enabled,
            source_ip=source_ip,
            multicast_group_amber=multicast_group_amber,
            multicast_group_blue=multicast_group_blue,
            port=port,
            payload_type=payload_type,
            video_format_mode=video_format_mode,
        )
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    notify_receiver_toggle("video", index, enabled)
    return RedirectResponse(url="/mgmt/media", status_code=303)


@router.post("/mgmt/media/audio")
def update_audio(
    enabled: bool = Form(False),
    source_ip: str = Form(""),
    multicast_group_amber: str = Form(""),
    multicast_group_blue: str = Form(""),
    port: int = Form(0),
    payload_type: int = Form(111),
    sampling_mode: str = Form("sdp"),
    ptime_mode: str = Form("sdp"),
):
    try:
        store.update_audio_receiver(
            enabled=enabled,
            source_ip=source_ip,
            multicast_group_amber=multicast_group_amber,
            multicast_group_blue=multicast_group_blue,
            port=port,
            payload_type=payload_type,
            sampling_mode=sampling_mode,
            ptime_mode=ptime_mode,
        )
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/media?error={e}", status_code=303)
    notify_receiver_toggle("audio", 0, enabled)
    return RedirectResponse(url="/mgmt/media", status_code=303)
