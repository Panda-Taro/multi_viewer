"""mediamtx/generate_config.py

対応要件: ④-6, ④-8 (WebGUIのビットレート/URL設定をMediaMTX設定へ反映)

WebGUIで設定された viewer_path (例 "monitor01") / control_nic_ip / bitrate_mbps
を元に mediamtx.yml を再生成する。MediaMTX自体のYAML構造にのみ依存し、
実バイナリなしでテスト可能。
"""
from __future__ import annotations

from dataclasses import dataclass


class MediaMtxConfigError(ValueError):
    pass


@dataclass
class ViewerSettings:
    """④-8 システム設定 > 視聴配信設定。"""

    viewer_path: str = "monitor01"       # URL /monitor01/ のパス部分
    bitrate_mbps: int = 20               # 10-50Mbps範囲
    control_nic_ip: str = "0.0.0.0"

    def validate(self) -> None:
        if not self.viewer_path or "/" in self.viewer_path:
            raise MediaMtxConfigError(f"不正な viewer_path: {self.viewer_path!r}")
        if not (10 <= self.bitrate_mbps <= 50):
            raise MediaMtxConfigError(
                f"bitrate_mbpsは10-50の範囲でなければならない: {self.bitrate_mbps}"
            )


def build_config_dict(settings: ViewerSettings) -> dict:
    """MediaMTX YAMLに対応するPython dict (yaml.safe_dumpでそのまま出力可能)。"""
    settings.validate()
    return {
        "logLevel": "info",
        "logDestinations": ["stdout", "file"],
        "logFile": "/var/log/multiviewer/mediamtx.log",
        "apiAddress": "127.0.0.1:9997",
        "api": True,
        "webrtc": True,
        "webrtcAddress": ":8889",
        "webrtcIPsFromInterfaces": True,
        "authMethod": "internal",
        "authInternalUsers": [
            {
                "user": "any",
                "pass": None,
                "ips": [],
                "permissions": [
                    {"action": "publish"},
                    {"action": "read"},
                    {"action": "playback"},
                ],
            }
        ],
        "paths": {
            settings.viewer_path: {
                "source": "publisher",
                "sourceOnDemand": False,
            }
        },
    }


def viewer_url(settings: ViewerSettings, control_nic_ip: str | None = None) -> str:
    """④-6: デフォルト http://(1G NIC IP)/monitor01/ を組み立てる。"""
    ip = control_nic_ip or settings.control_nic_ip
    return f"http://{ip}/{settings.viewer_path}/"


def render_yaml(settings: ViewerSettings) -> str:
    import yaml  # PyYAML: webgui/mediamtx双方の依存として明記

    return yaml.safe_dump(
        build_config_dict(settings), allow_unicode=True, sort_keys=False
    )
