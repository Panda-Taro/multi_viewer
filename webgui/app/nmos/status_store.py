"""Cross-process status hand-off between the NMOS service
(multiviewer-nmos.service, registration client + Connection API) and the
WebGUI process (dashboard). Same pattern step 1 used for network state: a
small JSON file under MULTIVIEWER_CONFIG_DIR, written by one process and
read by the other, so the dashboard does not need to make a network call
to another local port just to show status.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_DIR = Path(os.environ.get("MULTIVIEWER_CONFIG_DIR", "/etc/multiviewer"))
STATUS_PATH = STATUS_DIR / "nmos-status.json"

_lock = threading.Lock()

_DEFAULT_STATUS = {
    "registration_status": "disabled",  # "disabled" | "registering" | "registered" | "error"
    "rds_url": None,
    "last_registered_at": None,
    "last_heartbeat_at": None,
    "last_error": None,
    "updated_at": None,
}


def write_status(**fields: Any) -> None:
    with _lock:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        status = dict(_DEFAULT_STATUS)
        if STATUS_PATH.exists():
            try:
                with open(STATUS_PATH, encoding="utf-8") as f:
                    status.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
        status.update(fields)
        status["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp_path = STATUS_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATUS_PATH)


def read_status() -> dict[str, Any]:
    with _lock:
        if not STATUS_PATH.exists():
            return dict(_DEFAULT_STATUS)
        try:
            with open(STATUS_PATH, encoding="utf-8") as f:
                status = dict(_DEFAULT_STATUS)
                status.update(json.load(f))
                return status
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULT_STATUS)
