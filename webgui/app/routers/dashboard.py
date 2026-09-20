"""webgui/app/routers/dashboard.py

対応要件: ④-8 ダッシュボード (Pane1: プレビュー+モード切替、Pane2: 状態表示)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..config_store import store
from ..display_state import display_controller
from ..status import build_dashboard_status

router = APIRouter()
templates = Jinja2Templates(directory=str(__import__("pathlib").Path(__file__).parent.parent / "templates"))


def _collect_status():
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = 0.0

    receiver_activity = []
    for i, v in enumerate(store.media.videos):
        receiver_activity.append(
            {
                "label": f"Video Receiver {i + 1}",
                "enabled": v.enabled,
                "amber_active": bool(v.multicast_group_amber),
                "blue_active": bool(v.multicast_group_blue),
                "configured": v.is_configured(),
            }
        )
    receiver_activity.append(
        {
            "label": "Audio Receiver 1",
            "enabled": store.media.audio.enabled,
            "amber_active": bool(store.media.audio.multicast_group_amber),
            "blue_active": bool(store.media.audio.multicast_group_blue),
            "configured": store.media.audio.is_configured(),
        }
    )

    from ..nic_state import read_nic_state, NicStateError

    try:
        nics = read_nic_state()
        bandwidth = {n.name: 0.0 for n in nics}  # 実機では/sys/class/net統計から算出
    except NicStateError:
        bandwidth = {}

    viewer_url = f"http://{store.nic.control_ip_cidr.split('/')[0]}/{store.viewer.viewer_path}/"

    return build_dashboard_status(
        cpu_percent=cpu,
        nic_bandwidth_mbps=bandwidth,
        receiver_activity=receiver_activity,
        ptp_locked=False,  # 実機ではmtl/scripts/ptp_status.shの結果を反映
        ptp_source="unknown",
        viewer_url=viewer_url,
    )


@router.get("/mgmt/", response_class=HTMLResponse)
def dashboard_page(request: Request):
    status = _collect_status()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_nav": "dashboard",
            "status": status,
            "display_mode": display_controller.mode.value,
            "selected_index": display_controller.selected_index,
            "format_alarm": display_controller.format_alarm,
        },
    )


@router.post("/api/display-mode/toggle")
def toggle_display_mode():
    """④-4: WebGUI・視聴ページ共通の表示モード切替API。1秒以内の反映を狙い、
    FFmpeg zmqフィルタへのランタイムコマンド送出のみで処理する(プロセス再起動なし)。
    """
    commands = display_controller.toggle()
    return JSONResponse(
        {
            "mode": display_controller.mode.value,
            "selected_index": display_controller.selected_index,
            "zmq_commands": commands,
        }
    )


@router.post("/api/display-mode/select/{index}")
def select_single(index: int):
    """④-4: シングル表示モードで表示するReceiverを選択する。"""
    from fastapi import HTTPException
    from layout import DisplayMode, LayoutError  # compositor/ (display_state.pyがsys.path登録済み)

    try:
        commands = display_controller.set_mode(DisplayMode.SINGLE, selected_index=index)
    except LayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(
        {
            "mode": display_controller.mode.value,
            "selected_index": display_controller.selected_index,
            "zmq_commands": commands,
        }
    )


@router.get("/api/status")
def api_status():
    status = _collect_status()
    return JSONResponse(
        {
            "cpu_percent": status.cpu_percent,
            "nic_bandwidth_mbps": status.nic_bandwidth_mbps,
            "ptp_locked": status.ptp_locked,
            "ptp_source": status.ptp_source,
            "viewer_url": status.viewer_url,
            "receivers": [
                {"label": r.label, "led": r.led.value} for r in status.receivers
            ],
        }
    )
