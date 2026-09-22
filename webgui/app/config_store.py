"""Persistent configuration store for MultiViewer.

Step 1 only writes/reads settings here; later steps (NMOS, PTP, MTL,
compositor) read the same file to learn what the operator configured.
Storage is a single JSON file, guarded by a process-wide lock and written
atomically (write to temp file + os.replace) so a crash never leaves a
half-written config behind.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("MULTIVIEWER_CONFIG_DIR", "/etc/multiviewer"))
CONFIG_PATH = CONFIG_DIR / "config.json"

_DEFAULT_ENDPOINT = {"source_ip": "", "group_ip": "", "port": 0}

_DEFAULT_VIDEO_RECEIVER = {
    "enabled": False,
    "payload_id": 96,
    # "59.94i" | "59.94p" -- always a concrete value, never a literal "sdp"
    # placeholder (removed per operator request: the field must always show
    # a real value, updated live from the SDP's actual scan type when
    # NMOS-driven -- see nmos/connection_api.py's _resolve_video_format()
    # and NOTES.md "video_format等のSDP選択肢廃止").
    "video_format": "59.94i",
    "color_format": "YCbCr4:2:2_10bit_SDR",
    "amber": dict(_DEFAULT_ENDPOINT),
    "blue": dict(_DEFAULT_ENDPOINT),
    "sdp_source": "manual",  # "manual" | "nmos"
    "nmos_sdp": None,
    # The IS-05 sender_id the controller last staged for this receiver
    # (None if never set, or if manually cleared). Persisted so the IS-04
    # Receiver resource's `subscription.sender_id` -- and the IS-05
    # `active.sender_id` -- reflect what this receiver is actually
    # subscribed to, instead of a hardcoded placeholder. See
    # nmos/resources.py's _receiver_common() and NOTES.md "subscription
    # の動的化・RDSへの再登録".
    "sender_id": None,
}

_DEFAULT_AUDIO_RECEIVER = {
    "enabled": False,
    "payload_id": 97,
    "sampling": "48kHz",  # the only rate this system supports; always concrete
    "packet_time": "1ms",  # "1ms" | "0.125ms" -- always concrete, see above
    "amber": dict(_DEFAULT_ENDPOINT),
    "blue": dict(_DEFAULT_ENDPOINT),
    "sdp_source": "manual",
    "nmos_sdp": None,
    "sender_id": None,
}

_DEFAULT_NIC = {"interface": "", "mode": "static", "address": "", "prefix": 24, "gateway": ""}

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "receivers": {
        "video": [dict(_DEFAULT_VIDEO_RECEIVER) for _ in range(4)],
        "audio": [dict(_DEFAULT_AUDIO_RECEIVER) for _ in range(1)],
    },
    "ptp": {
        "domain": 0,
    },
    "nmos": {
        "rds_discovery": "static",  # "static" | "auto"
        "rds_static": {"address": "", "port": 0, "api_version": "v1.3"},
        "common_port": 8080,  # channelmapping/connection/events/node
        "source_port_mode": "auto",  # "auto" | "manual"
        "source_port": None,
    },
    # Stable IS-04 resource identifiers. Generated once (uuid4) on first use
    # by webgui/app/nmos/identity.py and persisted here so the Node keeps
    # the same identity across restarts -- re-registering with a different
    # Node ID each time would create duplicate Nodes in the RDS instead of
    # updating the existing one.
    "identity": {
        "node_id": None,
        "device_id": None,
        "video_receiver_ids": [None, None, None, None],
        "audio_receiver_ids": [None],
    },
    "network": {
        "media_amber": dict(_DEFAULT_NIC),
        "media_blue": dict(_DEFAULT_NIC),
        "control": dict(_DEFAULT_NIC),
    },
    "streaming": {
        "bitrate_mbps": 20,
        "url_path": "/monitor01/",
    },
    "display": {
        "mode": "quad",  # "quad" | "single"
        "single_source": 1,
    },
}

_lock = threading.Lock()


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge overlay into base, keeping base's keys when overlay is missing them.

    Guards against older config files on disk missing keys that newer code
    added (e.g. after a schema addition in a later step).
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config() -> dict[str, Any]:
    with _lock:
        if not CONFIG_PATH.exists():
            return copy.deepcopy(DEFAULT_CONFIG)
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                on_disk = json.load(f)
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(DEFAULT_CONFIG)
        return _deep_merge(DEFAULT_CONFIG, on_disk)


def save_config(config: dict[str, Any]) -> None:
    """Atomically persist the given config dict to disk."""
    with _lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, CONFIG_PATH)


def update_section(section: str, value: Any) -> dict[str, Any]:
    """Replace one top-level section (e.g. "ptp", "network") and save."""
    config = load_config()
    if section not in DEFAULT_CONFIG:
        raise KeyError(f"unknown config section: {section}")
    config[section] = value
    save_config(config)
    return config
