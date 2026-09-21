from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import config_store, log_store, network_state, nic_ip_change, nic_state

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()


@router.get("/mgmt/system")
def system_page(request: Request):
    config = config_store.load_config()
    return templates.TemplateResponse(
        "system.html",
        {
            "request": request,
            "config": config,
            "active_page": "system",
            "physical_interfaces": nic_state.list_physical_interface_names(),
            "network_state": network_state.load_state(),
            "rollback_timeout_default": network_state.DEFAULT_TIMEOUT_SECONDS,
            "high_risk_targets": nic_ip_change.HIGH_RISK_TARGETS,
        },
    )


@router.get("/api/network/state")
def get_network_state():
    state = network_state.load_state()
    state["seconds_remaining"] = network_state.seconds_remaining(state)
    return state


class NetworkApplyRequest(BaseModel):
    target: str  # "control" | "media_amber" | "media_blue"
    interface: str
    mode: str  # "static" | "dhcp"
    address: str = ""
    prefix: int = Field(default=24, ge=1, le=32)
    gateway: str = ""
    confirmed_risk: bool = False
    timeout_seconds: int = Field(default=network_state.DEFAULT_TIMEOUT_SECONDS, ge=30, le=1800)


@router.post("/api/network/apply")
def apply_network(update: NetworkApplyRequest):
    if update.target not in nic_ip_change.TARGETS:
        raise HTTPException(status_code=422, detail=f"target must be one of {nic_ip_change.TARGETS}")

    current_state = network_state.load_state()
    if current_state["status"] == "pending_confirm":
        raise HTTPException(
            status_code=409,
            detail=(
                "前回のネットワーク変更がまだ確認待ちです。確認またはロールバックの完了後に再度実行してください。"
            ),
        )

    request = nic_ip_change.NicChangeRequest(
        target=update.target,
        interface=update.interface,
        mode=update.mode,
        address=update.address,
        prefix=update.prefix,
        gateway=update.gateway,
        confirmed_risk=update.confirmed_risk,
        timeout_seconds=update.timeout_seconds,
    )
    try:
        state = nic_ip_change.apply_change(request)
    except nic_ip_change.NicChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Persist the *intended* configuration immediately so the GUI reflects
    # what was requested even before the reboot completes; nic_state.py
    # continues to report the OS's live view separately.
    config = config_store.load_config()
    config["network"][update.target] = {
        "interface": update.interface,
        "mode": update.mode,
        "address": update.address,
        "prefix": update.prefix,
        "gateway": update.gateway,
    }
    config_store.save_config(config)

    return {"status": "pending_reboot", "network_state": state}


@router.post("/api/network/confirm")
def confirm_network():
    state = network_state.load_state()
    if state["status"] != "pending_confirm":
        raise HTTPException(status_code=409, detail="確認待ちのネットワーク変更はありません")
    new_state = nic_ip_change.confirm_change()
    return {"status": "ok", "network_state": new_state}


class StreamingUpdate(BaseModel):
    bitrate_mbps: int = Field(ge=10, le=50)
    url_path: str = Field(min_length=2, pattern=r"^/[A-Za-z0-9_\-/]+/$")


@router.put("/api/streaming")
def update_streaming(update: StreamingUpdate):
    config = config_store.load_config()
    config["streaming"]["bitrate_mbps"] = update.bitrate_mbps
    config["streaming"]["url_path"] = update.url_path
    try:
        config_store.save_config(config)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc
    log_store.log_event("webgui", "info", "視聴用配信設定を更新しました", **update.model_dump())
    return {"status": "ok", "streaming": config["streaming"]}
