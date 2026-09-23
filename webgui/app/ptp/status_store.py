"""Cross-process status hand-off for PTP monitoring (step 3a).

Same pattern as nmos/status_store.py: a small JSON file under
MULTIVIEWER_CONFIG_DIR, written by the PTP monitor loop
(multiviewer-ptp.service, app/ptp_main.py + app/ptp/monitor.py) and read
by the WebGUI process's dashboard. A plain threading.Lock is sufficient
here -- unlike config_store.py, which needed a real cross-process lock --
because there is exactly one writer process for this file; no
cross-process read-modify-write race is possible the way it was for
config.json (see config_store.py's module docstring for that story).

Schema is keyed by "leg" (amber/blue) from the start, even though step 3a
only ever populates "amber": step 3b (Amber/Blue + BMCA failover) only
needs to start populating "blue" and start deriving "active_leg" from
BMCA's actual port selection instead of this step's single-leg stand-in --
no schema migration needed.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_DIR = Path(os.environ.get("MULTIVIEWER_CONFIG_DIR", "/etc/multiviewer"))
STATUS_PATH = STATUS_DIR / "ptp-status.json"

_lock = threading.Lock()

_DEFAULT_STATUS: dict[str, Any] = {
    "domain": None,
    # "amber" | "blue" | None. Step 3a: whichever leg last reported
    # gm_present=True (trivial with one leg). Step 3b replaces this with
    # BMCA's actual selected port.
    "active_leg": None,
    "legs": {
        "amber": None,
        "blue": None,
    },
}


def _default_leg() -> dict[str, Any]:
    return {
        "interface": None,
        "timestamping_mode": None,
        "port_state": None,
        "gm_present": False,
        "gm_id": None,
        "offset_ns": None,
        "jitter_ns": None,
        "sample_count": 0,
        "state": "unknown",
        "last_sample_at": None,
    }


def _read_unlocked() -> dict[str, Any]:
    status = copy.deepcopy(_DEFAULT_STATUS)
    if not STATUS_PATH.exists():
        return status
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
    except (json.JSONDecodeError, OSError):
        return status
    status.update(on_disk)
    if not isinstance(status.get("legs"), dict):
        status["legs"] = {"amber": None, "blue": None}
    return status


def _write_unlocked(status: dict[str, Any]) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATUS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATUS_PATH)


def write_leg_status(leg: str, domain: int, **fields: Any) -> None:
    if leg not in ("amber", "blue"):
        raise ValueError(f"unknown leg: {leg!r}")
    with _lock:
        status = _read_unlocked()
        status["domain"] = domain
        leg_status = status["legs"].get(leg) or _default_leg()
        leg_status.update(fields)
        leg_status["last_sample_at"] = datetime.now(timezone.utc).isoformat()
        status["legs"][leg] = leg_status
        if leg_status.get("gm_present"):
            status["active_leg"] = leg
        _write_unlocked(status)


def read_status() -> dict[str, Any]:
    with _lock:
        return _read_unlocked()
