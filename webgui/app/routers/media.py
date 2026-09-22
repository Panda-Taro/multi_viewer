from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import config_store, log_store
from ..nmos import connection_api as nmos_connection_api

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()

VIDEO_FORMAT_CHOICES = {"59.94i", "59.94p"}
COLOR_FORMAT_CHOICES = {"YCbCr4:2:2_10bit_SDR"}
AUDIO_SAMPLING_CHOICES = {"48kHz"}
AUDIO_PACKET_TIME_CHOICES = {"1ms", "0.125ms"}


class Endpoint(BaseModel):
    source_ip: str = ""
    group_ip: str = ""
    port: int = Field(default=0, ge=0, le=65535)


class VideoReceiverUpdate(BaseModel):
    enabled: bool
    payload_id: int = Field(ge=0, le=127)
    video_format: str
    color_format: str
    amber: Endpoint
    blue: Endpoint

    def validate_choices(self) -> Optional[str]:
        if self.video_format not in VIDEO_FORMAT_CHOICES:
            return f"video_format must be one of {sorted(VIDEO_FORMAT_CHOICES)}"
        if self.color_format not in COLOR_FORMAT_CHOICES:
            return f"color_format must be one of {sorted(COLOR_FORMAT_CHOICES)}"
        return None


class AudioReceiverUpdate(BaseModel):
    enabled: bool
    payload_id: int = Field(ge=0, le=127)
    sampling: str
    packet_time: str
    amber: Endpoint
    blue: Endpoint

    def validate_choices(self) -> Optional[str]:
        if self.sampling not in AUDIO_SAMPLING_CHOICES:
            return f"sampling must be one of {sorted(AUDIO_SAMPLING_CHOICES)}"
        if self.packet_time not in AUDIO_PACKET_TIME_CHOICES:
            return f"packet_time must be one of {sorted(AUDIO_PACKET_TIME_CHOICES)}"
        return None


@router.get("/mgmt/media")
def media_page(request: Request):
    config = config_store.load_config()
    return templates.TemplateResponse(
        "media.html",
        {"request": request, "config": config, "active_page": "media"},
    )


def _receiver_index(index: int, count: int) -> int:
    """Convert the 1-based index used by the UI/API to a 0-based list index."""
    if not 1 <= index <= count:
        raise HTTPException(status_code=404, detail=f"receiver index must be between 1 and {count}")
    return index - 1


@router.get("/api/media/receivers")
def get_receivers():
    """Polled by media.js so receivers currently driven by NMOS
    (sdp_source == "nmos") reflect IS-05 activate calls in near-real-time
    on the WebGUI (requirement 4.8.4.2.1.3), without the operator having to
    reload the page."""
    config = config_store.load_config()
    return {"video": config["receivers"]["video"], "audio": config["receivers"]["audio"]}


@router.put("/api/media/video/{index}")
def update_video_receiver(index: int, update: VideoReceiverUpdate):
    error = update.validate_choices()
    if error:
        raise HTTPException(status_code=422, detail=error)

    try:
        with config_store.locked_config() as config:
            receivers = config["receivers"]["video"]
            idx = _receiver_index(index, len(receivers))

            previous = receivers[idx]
            receivers[idx] = {
                **previous,
                "enabled": update.enabled,
                "payload_id": update.payload_id,
                "video_format": update.video_format,
                "color_format": update.color_format,
                "amber": update.amber.model_dump(),
                "blue": update.blue.model_dump(),
                "sdp_source": "manual",
                # A manual save fully supersedes whatever NMOS last set; leaving
                # the old SDP/sender_id around would misrepresent this receiver as
                # still subscribed to a Sender it may no longer resemble at all.
                "nmos_sdp": None,
                "sender_id": None,
            }
    except OSError as exc:
        # Requirement 4.8.3.1: on save failure, show an error and keep the
        # previous value -- returning 500 without having mutated the saved
        # file means the caller's already-rendered form (still showing the
        # old value) simply needs to surface this error, not revert.
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc

    # This write bypassed the IS-05 activate path, so any cached `staged`
    # value for this receiver is now stale relative to config.json --
    # drop it so the next NMOS GET/PATCH/activate re-reads the value just
    # saved here instead of silently reverting it. See connection_api.py's
    # module docstring and NOTES.md for the bug this closes.
    nmos_connection_api.invalidate_staged_for("video", idx)

    log_store.log_event("webgui", "info", f"映像Receiver{index}の設定を更新しました")
    return {"status": "ok", "receiver": receivers[idx]}


@router.put("/api/media/audio/{index}")
def update_audio_receiver(index: int, update: AudioReceiverUpdate):
    error = update.validate_choices()
    if error:
        raise HTTPException(status_code=422, detail=error)

    try:
        with config_store.locked_config() as config:
            receivers = config["receivers"]["audio"]
            idx = _receiver_index(index, len(receivers))

            previous = receivers[idx]
            receivers[idx] = {
                **previous,
                "enabled": update.enabled,
                "payload_id": update.payload_id,
                "sampling": update.sampling,
                "packet_time": update.packet_time,
                "amber": update.amber.model_dump(),
                "blue": update.blue.model_dump(),
                "sdp_source": "manual",
                "nmos_sdp": None,
                "sender_id": None,
            }
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc

    nmos_connection_api.invalidate_staged_for("audio", idx)

    log_store.log_event("webgui", "info", f"音声Receiver{index}の設定を更新しました")
    return {"status": "ok", "receiver": receivers[idx]}
