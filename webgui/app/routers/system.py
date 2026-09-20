"""webgui/app/routers/system.py

対応要件: ④-8 システム設定 (NIC IP、視聴配信設定、ログビューア導線)、
⑤ (NIC IP変更の確認/ロールバック機構)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config_store import store, ConfigValidationError, NicSettings
from ..log_store import log_store
from ..nic_ip_change import NicIpChangeManager, NicIpChangeError
from ..nic_state import read_nic_state, NicStateError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# WebGUIプロセス内で共有するNIC IP変更管理 (④-8, ⑤)
nic_change_manager = NicIpChangeManager()


@router.get("/mgmt/system", response_class=HTMLResponse)
def system_page(request: Request, error: str | None = None, notice: str | None = None):
    try:
        os_nics = read_nic_state()
    except NicStateError:
        os_nics = []

    recent_log_entries = list(reversed(log_store.filter()[-50:]))

    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "active_nav": "system",
            "nic": store.nic,
            "viewer": store.viewer,
            "os_nics": os_nics,
            "pending_changes": nic_change_manager.active_pending(),
            "recent_log_entries": recent_log_entries,
            "error": error,
            "notice": notice,
        },
    )


@router.post("/mgmt/system/nic")
def update_nic(
    amber_name: str = Form(...),
    amber_ip_cidr: str = Form(...),
    blue_name: str = Form(...),
    blue_ip_cidr: str = Form(...),
    control_name: str = Form(...),
    control_ip_cidr: str = Form(...),
):
    """④-8: NIC IP変更はGUI保存時点では即時反映せず、pending化してから
    「再起動して適用」操作で反映する二段階方式とした (自己ロックアウト防止、⑤)。
    """
    candidate = NicSettings(
        amber_name=amber_name,
        amber_ip_cidr=amber_ip_cidr,
        blue_name=blue_name,
        blue_ip_cidr=blue_ip_cidr,
        control_name=control_name,
        control_ip_cidr=control_ip_cidr,
    )
    try:
        # 変更差分がある項目だけpending登録する
        previous = store.nic
        for name, prev_cidr, new_cidr in (
            (candidate.amber_name, previous.amber_ip_cidr, candidate.amber_ip_cidr),
            (candidate.blue_name, previous.blue_ip_cidr, candidate.blue_ip_cidr),
            (candidate.control_name, previous.control_ip_cidr, candidate.control_ip_cidr),
        ):
            if prev_cidr != new_cidr:
                nic_change_manager.request_change(name, prev_cidr, new_cidr)
        store.update_nic(candidate)
    except (ConfigValidationError, NicIpChangeError) as e:
        return RedirectResponse(url=f"/mgmt/system?error={e}", status_code=303)

    return RedirectResponse(
        url="/mgmt/system?notice="
        + "IP変更を保存しました。反映にはサーバ再起動が必要です。再起動後、"
        + "一定時間内に到達確認が取れない場合は自動的に元の設定へロールバックされます。",
        status_code=303,
    )


@router.post("/mgmt/system/viewer")
def update_viewer(
    viewer_path: str = Form("monitor01"),
    bitrate_mbps: int = Form(20),
):
    candidate = store.viewer
    candidate = type(candidate)(
        viewer_path=viewer_path,
        bitrate_mbps=bitrate_mbps,
        control_nic_ip=store.nic.control_ip_cidr.split("/")[0],
    )
    try:
        store.update_viewer(candidate)
    except ConfigValidationError as e:
        return RedirectResponse(url=f"/mgmt/system?error={e}", status_code=303)
    return RedirectResponse(url="/mgmt/system", status_code=303)
