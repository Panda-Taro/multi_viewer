"""Builds IS-04 resource JSON (Node / Device / Receiver x5) as plain dicts.

This follows the shape of the AMWA NMOS IS-04 v1.3 resource schemas closely
enough to register successfully and be usable by a Query API client, but it
is not validated byte-for-byte against the official JSON Schema files (see
NOTES.md "NMOS実装の判断" for why, and README.md for what remains
unverified against a real/official registry).

Only Receiver resources exist (requirement 4.7.3: this system is
Receiver-only; no Sender resources).
"""
from __future__ import annotations

import socket
import time
from typing import Any

from .. import nic_state

NMOS_NODE_LABEL = "MultiViewer"
IS04_VERSIONS = ["v1.1", "v1.2", "v1.3"]
IS05_VERSIONS = ["v1.0", "v1.1"]

# ST2110-30 / AES67 default: 24-bit linear PCM. Requirement 6.2.1 says the
# codec is uncompressed PCM; this is the standard NMOS caps media_type for
# that.
AUDIO_MEDIA_TYPE = "audio/L24"
VIDEO_MEDIA_TYPE = "video/raw"


def _tai_version() -> str:
    """A NMOS "version" timestamp: <seconds>:<nanoseconds>, monotonically
    increasing (good enough here since wall-clock time only moves forward
    between our own resource rebuilds)."""
    now = time.time()
    sec = int(now)
    nsec = int((now - sec) * 1e9)
    return f"{sec}:{nsec}"


def _control_ip(config: dict) -> str:
    control_cfg = config["network"]["control"]
    interfaces = {i["name"]: i for i in nic_state.list_interfaces()}
    live = interfaces.get(control_cfg.get("interface"))
    if live and live["addresses"]:
        return live["addresses"][0]["address"]
    if control_cfg.get("address"):
        return control_cfg["address"]
    return "127.0.0.1"


def _media_interfaces(config: dict) -> list[dict[str, Any]]:
    """Node-level `interfaces` array (added in IS-04 v1.2), one per media
    NIC. Receivers reference these by name via `interface_bindings`."""
    interfaces = {i["name"]: i for i in nic_state.list_interfaces()}
    result = []
    for name, target in (("media_amber", "media_amber"), ("media_blue", "media_blue")):
        nic_cfg = config["network"][target]
        live = interfaces.get(nic_cfg.get("interface"))
        mac = live["mac"] if live and live.get("mac") else "00:00:00:00:00:00"
        # IS-04's node_interface schema requires DASH-separated lowercase
        # hex for port_id: `^([0-9a-f]{2}-){5}[0-9a-f]{2}$`, with no
        # freeform fallback (chassis_id does allow a freeform string, but
        # port_id does not -- confirmed against the official AMWA IS-04
        # v1.3 schema after a real registry rejected a colon-separated
        # value with 400 Bad Request). A prior revision of this code used
        # colons, which was wrong; do not "fix" this back to colons.
        mac_dashes = mac.lower().replace(":", "-")
        result.append(
            {
                "name": name,
                "chassis_id": mac_dashes,
                "port_id": mac_dashes,
            }
        )
    return result


def build_node(config: dict, identity: dict) -> dict[str, Any]:
    ip = _control_ip(config)
    port = config["nmos"]["common_port"]
    return {
        "id": identity["node_id"],
        "version": _tai_version(),
        "label": NMOS_NODE_LABEL,
        "description": "MultiViewer ST2110 Receiver Node (Receiver-only, no Sender)",
        "tags": {},
        "href": f"http://{ip}:{port}/",
        "hostname": socket.gethostname(),
        "api": {
            "versions": IS04_VERSIONS,
            "endpoints": [{"host": ip, "port": port, "protocol": "http"}],
        },
        "caps": {},
        "services": [],
        # ref_type "ptp" requires additional fields (traceable/version/
        # gmid/locked) that only a real PTP client can supply -- not
        # implemented until step 3. Declaring "internal" here is accurate
        # for now and avoids a schema validation failure (400) against a
        # real registry; revisit once PTP status is available.
        "clocks": [{"name": "clk0", "ref_type": "internal"}],
        "interfaces": _media_interfaces(config),
    }


def build_device(config: dict, identity: dict) -> dict[str, Any]:
    ip = _control_ip(config)
    port = config["nmos"]["common_port"]
    receiver_ids = list(identity["video_receiver_ids"]) + list(identity["audio_receiver_ids"])
    return {
        "id": identity["device_id"],
        "version": _tai_version(),
        "label": f"{NMOS_NODE_LABEL} Device",
        "description": "MultiViewer receiver device (4 video + 1 audio)",
        "tags": {},
        "type": "urn:x-nmos:device:generic",
        "node_id": identity["node_id"],
        "senders": [],
        "receivers": receiver_ids,
        "controls": [
            {"href": f"http://{ip}:{port}/x-nmos/connection/{v}/", "type": f"urn:x-nmos:control:sr-ctrl/{v}"}
            for v in IS05_VERSIONS
        ],
    }


def _receiver_common(
    receiver_id: str,
    device_id: str,
    label: str,
    format_urn: str,
    media_type: str,
) -> dict[str, Any]:
    return {
        "id": receiver_id,
        "version": _tai_version(),
        "label": label,
        "description": label,
        "tags": {},
        "device_id": device_id,
        "format": format_urn,
        "caps": {"media_types": [media_type]},
        "transport": "urn:x-nmos:transport:rtp.mcast",
        # Two legs: index 0 = Amber (A系), index 1 = Blue (B系), matching
        # this system's ST2022-7 dual-NIC receive design.
        "interface_bindings": ["media_amber", "media_blue"],
        "subscription": {"sender_id": None, "active": False},
    }


def build_video_receiver(index: int, config: dict, identity: dict) -> dict[str, Any]:
    receiver_id = identity["video_receiver_ids"][index]
    label = f"{NMOS_NODE_LABEL} Video Receiver {index + 1}"
    return _receiver_common(
        receiver_id, identity["device_id"], label, "urn:x-nmos:format:video", VIDEO_MEDIA_TYPE
    )


def build_audio_receiver(index: int, config: dict, identity: dict) -> dict[str, Any]:
    receiver_id = identity["audio_receiver_ids"][index]
    label = f"{NMOS_NODE_LABEL} Audio Receiver {index + 1}"
    return _receiver_common(
        receiver_id, identity["device_id"], label, "urn:x-nmos:format:audio", AUDIO_MEDIA_TYPE
    )


def build_all_receivers(config: dict, identity: dict) -> list[dict[str, Any]]:
    receivers = [build_video_receiver(i, config, identity) for i in range(len(identity["video_receiver_ids"]))]
    receivers += [build_audio_receiver(i, config, identity) for i in range(len(identity["audio_receiver_ids"]))]
    return receivers
