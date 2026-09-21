"""Append-only event log used by the WebGUI and, in later steps, by the
PTP/NMOS/receiver processes to record events such as PTP failover, NMOS
connect/disconnect and receiver state changes (requirement 5.3.1).

Stored as JSON Lines so it can be tailed/exported trivially and appended to
concurrently by multiple processes without corrupting earlier entries.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.environ.get("MULTIVIEWER_LOG_DIR", "/var/log/multiviewer"))
LOG_PATH = LOG_DIR / "events.log"

_lock = threading.Lock()

# Keeping this bounded avoids the WebGUI log view/export growing unbounded
# on a long-running server, since step 1 explicitly excludes a log
# management backend (requirement 8.5.1).
MAX_LINES_KEPT = 20000


def log_event(source: str, level: str, message: str, **extra: Any) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "level": level,
        "message": message,
    }
    if extra:
        entry["extra"] = extra
    with _lock:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim_if_needed()


def _trim_if_needed() -> None:
    if not LOG_PATH.exists():
        return
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) > MAX_LINES_KEPT:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines[-MAX_LINES_KEPT:])


def read_events(limit: int = 500) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    with _lock, open(LOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    events = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    events.reverse()  # newest first
    return events


def export_path() -> Path:
    return LOG_PATH
