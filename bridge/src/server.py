"""bridge/src/server.py

対応要件: ④-7

nmos-cpp の node_implementation からのactivate通知を受け、translator.py で
MTL RX設定へ反映しigmp.py でIGMPv3 joinを行うFastAPIサーバ。
systemd/multiviewer-bridge.service から `uvicorn bridge.src.server:app` として
起動される。
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_HERE = os.path.dirname(os.path.abspath(__file__))
# `uvicorn bridge.src.server:app` のようにパッケージ経由で読み込まれる場合、
# server.py自身のディレクトリ(bridge/src)は自動的にはsys.pathへ追加されない
# ため、同ディレクトリ内のtranslator/igmpをimportするために明示的に追加する。
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "..", "mtl"))

from translator import (  # noqa: E402
    apply_activate_request,
    apply_deactivate_request,
    apply_enable_request,
    ActivateTranslationError,
)
from igmp import plan_joins, plan_leaves, join_ssm_group, leave_ssm_group, IgmpError  # noqa: E402
from rxctl import RxSystemConfig  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multiviewer.bridge")

RX_CONFIG_PATH = Path(os.environ.get("MTL_RX_CONFIG", "/etc/multiviewer/mtl/rx_config.json"))
LOG_PATH = Path(os.environ.get("MULTIVIEWER_LOG", "/var/log/multiviewer/bridge.log"))

app = FastAPI(title="MultiViewer NMOS Bridge")

# プロセス内に保持する現在のRX設定 (実機では起動時にRX_CONFIG_PATHから読み込む)
_current_config = RxSystemConfig()

# receiver_role -> interface_name -> Joinソケット。
# ④-8-4-2-1補足仕様: 無効化時にIGMPv3 Leaveを送出するため、Join済みソケットを
# 保持しておく (bridgeプロセス内メモリのみ。プロセス再起動を跨いだ保持は行わない)。
_join_sockets: dict[str, dict[str, "object"]] = {}


class ActivateRequest(BaseModel):
    receiver_role: str  # 例: "video-receiver-1", "audio-receiver-1"
    sdp: str
    amber_iface: str = "amber0"
    amber_ip: str = "192.168.100.1"
    blue_iface: str = "blue0"
    blue_ip: str = "192.168.101.1"


def _log_event(message: str) -> None:
    logger.info(message)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        # 実機以外(パーミッションなし等)ではログファイル書き込みをスキップする
        pass


@app.get("/health")
def health():
    return {"status": "ok"}


def _write_rx_config(config: RxSystemConfig) -> None:
    try:
        RX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RX_CONFIG_PATH.write_text(
            json.dumps(config.to_mtl_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("RX設定ファイルの書き込みに失敗しました(実機以外での実行時は正常): %s", e)


def _perform_joins(receiver_role: str, join_requests, amber_iface, amber_ip, blue_iface, blue_ip) -> list[dict]:
    """④-7,⑦: Amber/Blue両NICでIGMPv3 joinを行い、Leave用にソケットを保持する。"""
    join_plan_summaries = []
    is_linux = platform.system() == "Linux"
    sockets_for_role = _join_sockets.setdefault(receiver_role, {})
    for jr in join_requests:
        try:
            plans = plan_joins(
                jr.multicast_group, jr.source_ip, amber_iface, amber_ip, blue_iface, blue_ip
            )
        except IgmpError as e:
            _log_event(f"[IGMP] [ERROR] {e}")
            raise HTTPException(status_code=400, detail=str(e))

        for plan in plans:
            join_plan_summaries.append(
                {"group": plan.group, "source": plan.source, "interface": plan.interface_name}
            )
            if is_linux:
                try:
                    sockets_for_role[plan.interface_name] = join_ssm_group(plan)
                    _log_event(
                        f"[IGMP] [INFO] IGMPv3 join発行 group={plan.group} "
                        f"source={plan.source} interface={plan.interface_name}"
                    )
                except IgmpError as e:
                    _log_event(f"[IGMP] [ERROR] {e}")
            else:
                _log_event(
                    f"[IGMP] [INFO] (非Linux環境のためjoinはスキップ) "
                    f"group={plan.group} source={plan.source} interface={plan.interface_name}"
                )
    return join_plan_summaries


def _perform_leaves(receiver_role: str, leave_request, amber_iface, amber_ip, blue_iface, blue_ip) -> list[dict]:
    """④-8-4-2-1補足仕様: Receiver無効化時にAmber/Blue両NICでIGMPv3 leaveを行う。"""
    leave_plan_summaries = []
    is_linux = platform.system() == "Linux"
    sockets_for_role = _join_sockets.get(receiver_role, {})
    try:
        plans = plan_leaves(
            leave_request.multicast_group,
            leave_request.source_ip,
            amber_iface,
            amber_ip,
            blue_iface,
            blue_ip,
        )
    except IgmpError as e:
        # 未設定(グループ/送信元が空)のReceiverを無効化しただけの場合はLeave自体が
        # 不要なため、エラーにはせずスキップする。
        _log_event(f"[IGMP] [INFO] Leave対象なし(未設定Receiver): {e}")
        return leave_plan_summaries

    for plan in plans:
        leave_plan_summaries.append(
            {"group": plan.group, "source": plan.source, "interface": plan.interface_name}
        )
        if is_linux:
            try:
                sock = sockets_for_role.pop(plan.interface_name, None)
                leave_ssm_group(plan, sock)
                _log_event(
                    f"[IGMP] [INFO] IGMPv3 leave発行 group={plan.group} "
                    f"source={plan.source} interface={plan.interface_name}"
                )
            except IgmpError as e:
                _log_event(f"[IGMP] [ERROR] {e}")
        else:
            _log_event(
                f"[IGMP] [INFO] (非Linux環境のためleaveはスキップ) "
                f"group={plan.group} source={plan.source} interface={plan.interface_name}"
            )
    return leave_plan_summaries


@app.post("/nmos/activate")
def activate(req: ActivateRequest):
    global _current_config
    try:
        updated_config, join_requests, alarm = apply_activate_request(
            _current_config, req.receiver_role, req.sdp
        )
    except ActivateTranslationError as e:
        _log_event(f"[NMOS] [ERROR] activate失敗 receiver={req.receiver_role} reason={e}")
        raise HTTPException(status_code=400, detail=str(e))

    _current_config = updated_config
    _log_event(f"[NMOS] [INFO] activate成功 receiver={req.receiver_role}")

    if alarm:
        _log_event(f"[VIDEO] [WARN] {alarm}")

    join_plan_summaries = _perform_joins(
        req.receiver_role, join_requests, req.amber_iface, req.amber_ip, req.blue_iface, req.blue_ip
    )
    _write_rx_config(updated_config)

    return {
        "receiver_role": req.receiver_role,
        "format_alarm": alarm,
        "igmp_joins": join_plan_summaries,
    }


class ReceiverToggleRequest(BaseModel):
    """④-8-4-2-1補足仕様: WebGUI手動トグル、またはIS-05 deactivate(master_enable=false)
    の両方が最終的にこのモデルへ到達し、同一のMTL Rxセッション制御+IGMP Join/Leave
    ロジックを通る (内部状態を一本化するための共通経路)。
    """

    receiver_role: str
    enabled: bool
    amber_iface: str = "amber0"
    amber_ip: str = "192.168.100.1"
    blue_iface: str = "blue0"
    blue_ip: str = "192.168.101.1"


def _set_receiver_enabled(req: ReceiverToggleRequest, trigger: str) -> dict:
    """trigger: ログ表示用のトリガー種別ラベル("WebGUI" | "NMOS")。

    WebGUIトグルとIS-05のmaster_enableは常に同一の内部状態(RxSystemConfigの
    enabledフィールド)を操作するため、どちらの経路から呼ばれても挙動は同じである。
    """
    global _current_config
    try:
        if req.enabled:
            updated_config, join_request = apply_enable_request(_current_config, req.receiver_role)
        else:
            updated_config, join_request = apply_deactivate_request(_current_config, req.receiver_role)
    except ActivateTranslationError as e:
        _log_event(f"[NMOS] [ERROR] {trigger}による有効/無効切替に失敗 receiver={req.receiver_role} reason={e}")
        raise HTTPException(status_code=400, detail=str(e))

    _current_config = updated_config
    action_label = "有効化" if req.enabled else "無効化"
    _log_event(f"[NMOS] [INFO] {trigger}操作によりReceiver{action_label} receiver={req.receiver_role}")

    if req.enabled:
        igmp_summary = _perform_joins(
            req.receiver_role, [join_request], req.amber_iface, req.amber_ip, req.blue_iface, req.blue_ip
        )
    else:
        igmp_summary = _perform_leaves(
            req.receiver_role, join_request, req.amber_iface, req.amber_ip, req.blue_iface, req.blue_ip
        )

    _write_rx_config(updated_config)

    return {
        "receiver_role": req.receiver_role,
        "enabled": req.enabled,
        "igmp": igmp_summary,
    }


@app.post("/nmos/deactivate")
def nmos_deactivate(req: ReceiverToggleRequest):
    """④-8-4-2-1補足仕様: 外部NMOSコントローラからのIS-05 deactivate要求
    (master_enable=false)を受けて、MTL Rxセッション停止+IGMPv3 leaveを行う。
    nmos-cpp側 (node_implementation) がactive.master_enableの値に応じて
    /nmos/activate または本エンドポイントのどちらかへ通知する設計とする。
    """
    return _set_receiver_enabled(req, trigger="NMOS")


@app.post("/webgui/receiver-toggle")
def webgui_receiver_toggle(req: ReceiverToggleRequest):
    """④-8-4-2-1補足仕様: WebGUI手動トグル操作。IS-05の`active.master_enable`にも
    同じ値を反映する必要があるため、WebGUI側はこの呼び出しの成否をもとに
    nmos-cpp自身のIS-05 Connection APIへも同期PATCHを行う
    (webgui/app/nmos_sync.py、要実機検証)。
    """
    return _set_receiver_enabled(req, trigger="WebGUI")


@app.get("/state")
def state():
    return _current_config.to_mtl_json()
