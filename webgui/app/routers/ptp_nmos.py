from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import config_store, log_store
from ..nmos import status_store as nmos_status_store

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()

RDS_DISCOVERY_CHOICES = {"static", "auto"}
NMOS_API_VERSIONS = {"v1.1", "v1.2", "v1.3"}
SOURCE_PORT_MODES = {"auto", "manual"}


@router.get("/mgmt/ptp-nmos")
def ptp_nmos_page(request: Request):
    config = config_store.load_config()
    return templates.TemplateResponse(
        "ptp_nmos.html",
        {"request": request, "config": config, "active_page": "ptp-nmos"},
    )


class PtpUpdate(BaseModel):
    domain: int = Field(ge=0, le=127)


@router.put("/api/ptp")
def update_ptp(update: PtpUpdate):
    config = config_store.load_config()
    config["ptp"]["domain"] = update.domain
    try:
        config_store.save_config(config)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc
    log_store.log_event("webgui", "info", "PTP設定を更新しました", domain=update.domain)
    return {"status": "ok", "ptp": config["ptp"]}


class RdsStatic(BaseModel):
    address: str = ""
    port: int = Field(default=0, ge=0, le=65535)
    api_version: str = "v1.3"


class NmosUpdate(BaseModel):
    rds_discovery: str
    rds_static: RdsStatic
    common_port: int = Field(ge=0, le=65535)
    source_port_mode: str
    source_port: Optional[int] = Field(default=None, ge=0, le=65535)

    def validate_choices(self) -> Optional[str]:
        if self.rds_discovery not in RDS_DISCOVERY_CHOICES:
            return f"rds_discovery must be one of {sorted(RDS_DISCOVERY_CHOICES)}"
        if self.rds_static.api_version not in NMOS_API_VERSIONS:
            return f"rds_static.api_version must be one of {sorted(NMOS_API_VERSIONS)}"
        if self.source_port_mode not in SOURCE_PORT_MODES:
            return f"source_port_mode must be one of {sorted(SOURCE_PORT_MODES)}"
        if self.source_port_mode == "manual" and self.source_port is None:
            return "source_port is required when source_port_mode is 'manual'"
        return None


@router.put("/api/nmos")
def update_nmos(update: NmosUpdate):
    error = update.validate_choices()
    if error:
        raise HTTPException(status_code=422, detail=error)

    config = config_store.load_config()
    config["nmos"] = {
        "rds_discovery": update.rds_discovery,
        "rds_static": update.rds_static.model_dump(),
        "common_port": update.common_port,
        "source_port_mode": update.source_port_mode,
        "source_port": update.source_port,
    }
    try:
        config_store.save_config(config)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"設定の保存に失敗しました: {exc}") from exc
    log_store.log_event("webgui", "info", "NMOS設定を更新しました")
    return {"status": "ok", "nmos": config["nmos"]}


@router.get("/api/nmos/status")
def get_nmos_status():
    """Polled by ptp_nmos.js (stage 2b step 3): registration status plus,
    when discovery_mode == "auto", the mDNS-discovered registries and
    which one is currently selected/registered with."""
    return nmos_status_store.read_status()
