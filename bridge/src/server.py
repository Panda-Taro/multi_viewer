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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mtl"))

from translator import apply_activate_request, ActivateTranslationError  # noqa: E402
from igmp import plan_joins, join_ssm_group, IgmpError  # noqa: E402
from rxctl import RxSystemConfig  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multiviewer.bridge")

RX_CONFIG_PATH = Path(os.environ.get("MTL_RX_CONFIG", "/etc/multiviewer/mtl/rx_config.json"))
LOG_PATH = Path(os.environ.get("MULTIVIEWER_LOG", "/var/log/multiviewer/bridge.log"))

app = FastAPI(title="MultiViewer NMOS Bridge")

# プロセス内に保持する現在のRX設定 (実機では起動時にRX_CONFIG_PATHから読み込む)
_current_config = RxSystemConfig()


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

    join_plan_summaries = []
    is_linux = platform.system() == "Linux"
    for jr in join_requests:
        try:
            plans = plan_joins(
                jr.multicast_group,
                jr.source_ip,
                req.amber_iface,
                req.amber_ip,
                req.blue_iface,
                req.blue_ip,
            )
        except IgmpError as e:
            _log_event(f"[IGMP] [ERROR] {e}")
            raise HTTPException(status_code=400, detail=str(e))

        for plan in plans:
            join_plan_summaries.append(
                {
                    "group": plan.group,
                    "source": plan.source,
                    "interface": plan.interface_name,
                }
            )
            if is_linux:
                try:
                    join_ssm_group(plan)
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

    try:
        RX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RX_CONFIG_PATH.write_text(
            json.dumps(updated_config.to_mtl_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("RX設定ファイルの書き込みに失敗しました(実機以外での実行時は正常): %s", e)

    return {
        "receiver_role": req.receiver_role,
        "format_alarm": alarm,
        "igmp_joins": join_plan_summaries,
    }


@app.get("/state")
def state():
    return _current_config.to_mtl_json()
