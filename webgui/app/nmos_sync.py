"""webgui/app/nmos_sync.py

対応要件: ④-8-4-2-1補足仕様(Receiver有効/無効)

WebGUIでReceiverを手動トグルした際、bridge (bridge/src/server.py) の
`/webgui/receiver-toggle` を呼び出し、内部状態(MTL Rxセッション有効/無効
+ IGMPv3 Join/Leave)を更新させる。bridgeはこの操作をNMOSからのIS-05
deactivateと全く同じ経路(translator.apply_enable_request/apply_deactivate_request)
で処理するため、WebGUIトグルとIS-05 master_enableは同一の内部状態を指す
(要件: 「WebGUIトグルとIS-05のmaster_enableは常に一致させる」)。

bridgeが未起動の場合でもWebGUI側の操作自体は失敗させない(疎結合。
nmos-cpp側の活性化ハンドラ(nmos/node_implementation/
multiviewer_node_implementation.cpp)が同様にbridge未起動を許容している
設計判断と合わせている)。
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("multiviewer.webgui.nmos_sync")

BRIDGE_TOGGLE_URL = os.environ.get(
    "MULTIVIEWER_BRIDGE_TOGGLE_URL", "http://127.0.0.1:8090/webgui/receiver-toggle"
)

_RECEIVER_ROLE_BY_KIND_INDEX = {
    ("video", 0): "video-receiver-1",
    ("video", 1): "video-receiver-2",
    ("video", 2): "video-receiver-3",
    ("video", 3): "video-receiver-4",
    ("audio", 0): "audio-receiver-1",
}


def receiver_role(receiver_kind: str, index: int = 0) -> str:
    try:
        return _RECEIVER_ROLE_BY_KIND_INDEX[(receiver_kind, index)]
    except KeyError as e:
        raise ValueError(f"不明なreceiver_kind/index: {receiver_kind}/{index}") from e


def notify_receiver_toggle(receiver_kind: str, index: int, enabled: bool) -> None:
    """bridgeへWebGUIトグル操作を通知する。bridge未起動時は警告ログのみ。"""
    try:
        role = receiver_role(receiver_kind, index)
        httpx.post(BRIDGE_TOGGLE_URL, json={"receiver_role": role, "enabled": enabled}, timeout=2.0)
    except Exception as e:  # bridge未起動・通信断はWebGUI操作自体を失敗させない
        logger.warning("bridgeへのReceiver有効/無効通知に失敗しました: %s", e)
