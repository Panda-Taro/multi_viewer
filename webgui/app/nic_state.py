"""webgui/app/nic_state.py

対応要件: ④-8 (「10G/1GのNIC IPアドレス等を実際にOSから読み取りGUIに反映」)、
⑦ (異なるハードウェアへ再展開してもコードは変えず、GUI設定のみで済む)

`ip -j addr show` (iproute2のJSON出力) をパースしてNIC一覧を得る。
パース処理はサブプロセス実行と分離しており、実際の `ip` コマンド出力例を
そのまま fixture として与えることで、非Linux環境でもロジックをテストできる。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


class NicStateError(RuntimeError):
    pass


@dataclass
class NicInfo:
    name: str
    mac: str
    up: bool
    ipv4_addresses: list[str] = field(default_factory=list)

    @property
    def primary_ipv4(self) -> str:
        return self.ipv4_addresses[0] if self.ipv4_addresses else ""


def parse_ip_addr_json(raw_json: str) -> list[NicInfo]:
    """`ip -j addr show` の出力(JSON配列)をパースする。

    各要素の例:
    {
      "ifname": "enp1s0f0",
      "operstate": "UP",
      "address": "aa:bb:cc:dd:ee:ff",
      "addr_info": [ {"family": "inet", "local": "192.168.100.1", "prefixlen": 24} ]
    }
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise NicStateError(f"ip addr の出力をJSONとして解析できません: {e}") from e

    result = []
    for entry in data:
        ifname = entry.get("ifname", "")
        if ifname == "lo":
            continue
        addr_info = entry.get("addr_info", [])
        ipv4s = [
            f"{a['local']}/{a['prefixlen']}"
            for a in addr_info
            if a.get("family") == "inet"
        ]
        result.append(
            NicInfo(
                name=ifname,
                mac=entry.get("address", ""),
                up=entry.get("operstate", "").upper() == "UP",
                ipv4_addresses=ipv4s,
            )
        )
    return result


def read_nic_state() -> list[NicInfo]:
    """実機(Linux)で `ip -j addr show` を実行し結果をパースする。

    非Linux/コマンド不在の場合は NicStateError を送出する
    (呼び出し側 = webgui/app/routers/system.py がフォールバック表示を行う)。
    """
    try:
        proc = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise NicStateError(f"ip コマンドの実行に失敗しました: {e}") from e

    return parse_ip_addr_json(proc.stdout)


def classify_nics(
    nics: list[NicInfo], amber_name: str, blue_name: str, control_name: str
) -> dict:
    """設定済みのAmber/Blue/制御NIC名に基づき役割ラベルを付与する (④-8表示用)。"""
    by_name = {n.name: n for n in nics}
    return {
        "amber": by_name.get(amber_name),
        "blue": by_name.get(blue_name),
        "control": by_name.get(control_name),
        "unclassified": [
            n for n in nics if n.name not in (amber_name, blue_name, control_name)
        ],
    }
