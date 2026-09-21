"""State machine for the NIC IP change safety mechanism.

Design (see README.md "IPアドレス変更の安全機構" and requirement 5.4.3 /
7.5.2):

  stable ----apply()----> pending_confirm ----confirm()----> stable
                                |
                                | (timeout elapsed, checked by
                                |  multiviewer-nic-rollback.timer)
                                v
                          rolled_back  (then a fresh apply() -> pending_confirm
                                        can happen again)

The state file is intentionally separate from config.json: it must survive
and be interpreted correctly even if config.json itself becomes malformed,
and it is written by both the WebGUI process and the standalone rollback
check script (scripts/nic_rollback_check.py), so it needs a stable,
minimal, dependency-free format.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATE_DIR = Path(os.environ.get("MULTIVIEWER_CONFIG_DIR", "/etc/multiviewer"))
STATE_PATH = STATE_DIR / "network-state.json"
BACKUP_ROOT = STATE_DIR / "netplan-backups"

DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes, per the request's example

_lock = threading.Lock()

_DEFAULT_STATE = {
    "status": "stable",  # "stable" | "pending_confirm" | "rolled_back"
    "pending_since": None,
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "backup_path": None,
    "changed_targets": [],
    "last_rollback_at": None,
    "last_rollback_reason": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict[str, Any]:
    with _lock:
        return _load_state_locked()


def _load_state_locked() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return dict(_DEFAULT_STATE)
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_STATE)
    state = dict(_DEFAULT_STATE)
    state.update(on_disk)
    return state


def _save_state_locked(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, STATE_PATH)


def begin_pending(
    backup_path: str,
    changed_targets: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    with _lock:
        state = {
            "status": "pending_confirm",
            "pending_since": _now_iso(),
            "timeout_seconds": timeout_seconds,
            "backup_path": backup_path,
            "changed_targets": changed_targets,
            "last_rollback_at": None,
            "last_rollback_reason": None,
        }
        _save_state_locked(state)
        return state


def confirm() -> dict[str, Any]:
    """Called from the WebGUI once the operator has verified the new IP
    works. Only valid while pending_confirm; anything else is a no-op that
    returns the current state unchanged, so a stray double-click is safe."""
    with _lock:
        state = _load_state_locked()
        if state["status"] != "pending_confirm":
            return state
        state["status"] = "stable"
        state["pending_since"] = None
        state["backup_path"] = None
        state["changed_targets"] = []
        _save_state_locked(state)
        return state


def mark_rolled_back(reason: str) -> dict[str, Any]:
    with _lock:
        state = _load_state_locked()
        state["status"] = "rolled_back"
        state["last_rollback_at"] = _now_iso()
        state["last_rollback_reason"] = reason
        state["pending_since"] = None
        _save_state_locked(state)
        return state


def seconds_remaining(state: Optional[dict[str, Any]] = None) -> Optional[float]:
    state = state or load_state()
    if state["status"] != "pending_confirm" or not state["pending_since"]:
        return None
    since = datetime.fromisoformat(state["pending_since"])
    elapsed = (datetime.now(timezone.utc) - since).total_seconds()
    return max(0.0, state["timeout_seconds"] - elapsed)


def is_expired(state: Optional[dict[str, Any]] = None) -> bool:
    remaining = seconds_remaining(state)
    return remaining is not None and remaining <= 0
