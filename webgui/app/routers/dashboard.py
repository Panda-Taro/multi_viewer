from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import config_store, log_store, network_state, nic_state, system_stats

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()


@router.get("/mgmt/")
def dashboard_page(request: Request):
    config = config_store.load_config()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "config": config,
            "active_page": "dashboard",
        },
    )


@router.get("/api/dashboard/status")
def dashboard_status():
    config = config_store.load_config()
    interfaces = {i["name"]: i for i in nic_state.list_interfaces()}

    def nic_summary(nic_cfg: dict) -> dict:
        live = interfaces.get(nic_cfg.get("interface"))
        return {
            "interface": nic_cfg.get("interface"),
            "configured_mode": nic_cfg.get("mode"),
            "configured_address": nic_cfg.get("address"),
            "link_state": live["state"] if live else "unknown",
            "live_addresses": live["addresses"] if live else [],
        }

    video_leds = [
        {"id": idx + 1, "enabled": r["enabled"], "state": "receiving" if r["enabled"] else "disabled"}
        for idx, r in enumerate(config["receivers"]["video"])
    ]
    audio_leds = [
        {"id": idx + 1, "enabled": r["enabled"], "state": "receiving" if r["enabled"] else "disabled"}
        for idx, r in enumerate(config["receivers"]["audio"])
    ]

    return {
        "nics": {
            "media_amber": nic_summary(config["network"]["media_amber"]),
            "media_blue": nic_summary(config["network"]["media_blue"]),
            "control": nic_summary(config["network"]["control"]),
        },
        "cpu_percent": system_stats.cpu_percent(),
        "memory_percent": system_stats.memory_percent(),
        "video_receivers": video_leds,
        "audio_receivers": audio_leds,
        # PTP lock state is reported by the PTP client implemented in a
        # later step; step 1 exposes the field as "not_implemented" so the
        # dashboard layout and polling logic do not need to change later.
        "ptp_lock_state": "not_implemented",
        "display_mode": config["display"]["mode"],
        "single_source": config["display"]["single_source"],
        "viewer_url_path": config["streaming"]["url_path"],
        "network_pending": network_state.load_state(),
    }


class DisplayModeUpdate(BaseModel):
    mode: str = Field(pattern="^(quad|single)$")
    single_source: int = Field(ge=1, le=4)


@router.post("/api/display")
def update_display_mode(update: DisplayModeUpdate):
    config = config_store.load_config()
    config["display"]["mode"] = update.mode
    config["display"]["single_source"] = update.single_source
    try:
        config_store.save_config(config)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc
    log_store.log_event(
        "webgui", "info", "表示モードを変更しました", mode=update.mode, single_source=update.single_source
    )
    return {"status": "ok", "display": config["display"]}
