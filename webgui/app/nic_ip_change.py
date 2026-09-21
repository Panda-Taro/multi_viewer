"""Applies OS-level NIC IP address changes, safely.

This is the module the incident report in the task brief is about: a prior
implementation changed NIC settings and locked the operator out over SSH.
The design here follows requirement 5.4.3 (rollback on misconfiguration)
and 7.5.2 (IP changes are reboot-based):

1. Never touch the network live. Write a netplan file, then schedule a
   reboot; the new address only takes effect when systemd-networkd
   re-applies netplan at boot. A broken address never fully takes effect on
   the running interface out from under the current SSH/WebGUI session.
2. Back up the previous netplan file (or record that none existed) before
   writing the new one, under /etc/multiviewer/netplan-backups/<ts>/.
3. Validate the new file with `netplan generate` (a dry run that does not
   touch the live network) before committing to it; on failure, the old
   file is restored and nothing is scheduled.
4. Record a "pending_confirm" state (see network_state.py). A separate,
   always-on systemd timer (multiviewer-nic-rollback.timer ->
   scripts/nic_rollback_check.py) checks after boot whether the operator
   confirmed the new address from the WebGUI within the timeout; if not,
   it restores the backup and reboots again.
5. The control NIC (WebGUI/SSH access) requires an explicit
   `confirmed_risk=True` flag from the caller, because breaking it is more
   disruptive to recover from physically than breaking a media NIC.

Nothing here has been exercised against a real NIC yet -- see README.md's
"実機検証が必要な項目" list.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import log_store, network_state

NETPLAN_DIR = Path(os.environ.get("MULTIVIEWER_NETPLAN_DIR", "/etc/netplan"))
BACKUP_ROOT = network_state.BACKUP_ROOT

TARGETS = ("control", "media_amber", "media_blue")

# The control NIC is what the WebGUI and SSH are reached through -- a
# mistake there is far more disruptive to recover from than a media NIC
# mistake, so it is flagged distinctly throughout the UI and API.
HIGH_RISK_TARGETS = ("control",)


class NicChangeError(Exception):
    pass


@dataclass
class NicChangeRequest:
    target: str  # "control" | "media_amber" | "media_blue"
    interface: str
    mode: str  # "static" | "dhcp"
    address: str = ""
    prefix: int = 24
    gateway: str = ""
    confirmed_risk: bool = False
    timeout_seconds: int = network_state.DEFAULT_TIMEOUT_SECONDS


def netplan_file_for(target: str) -> Path:
    if target not in TARGETS:
        raise NicChangeError(f"unknown network target: {target}")
    return NETPLAN_DIR / f"90-multiviewer-{target.replace('_', '-')}.yaml"


def render_netplan_yaml(interface: str, mode: str, address: str, prefix: int, gateway: str) -> str:
    if not interface:
        raise NicChangeError("interface name is required")
    lines = [
        "network:",
        "  version: 2",
        "  ethernets:",
        f"    {interface}:",
    ]
    if mode == "dhcp":
        lines.append("      dhcp4: true")
    elif mode == "static":
        if not address:
            raise NicChangeError("static mode requires an address")
        lines.append("      dhcp4: false")
        lines.append(f"      addresses: [{address}/{prefix}]")
        if gateway:
            lines.append("      routes:")
            lines.append(f"        - to: default")
            lines.append(f"          via: {gateway}")
    else:
        raise NicChangeError(f"unknown mode: {mode}")
    return "\n".join(lines) + "\n"


def _backup_dir_for_now() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return BACKUP_ROOT / ts


def _backup_existing_file(target: str, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    src = netplan_file_for(target)
    if src.exists():
        shutil.copy2(src, backup_dir / f"{target}.yaml")
    else:
        (backup_dir / f"{target}.absent").write_text("", encoding="utf-8")


def _validate_netplan(run: Callable[..., subprocess.CompletedProcess]) -> None:
    """Dry-run validation. `netplan generate` parses every file under
    /etc/netplan and writes the backend (networkd) config without touching
    live interfaces or requiring a reboot, so it is safe to call here."""
    if shutil.which("netplan") is None:
        # Non-Linux dev machine / netplan not installed: skip validation
        # rather than fail, so tests can run the rest of the flow.
        return
    result = run(["netplan", "generate"], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        raise NicChangeError(f"netplan generate failed: {result.stderr.strip()}")


def _default_reboot(delay_minutes: int = 1) -> None:
    if shutil.which("shutdown") is None:
        return
    subprocess.run(
        ["shutdown", "-r", f"+{delay_minutes}", "MultiViewer: applying network configuration change"],
        check=False,
    )


def apply_change(
    request: NicChangeRequest,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    reboot_fn: Callable[[], None] = _default_reboot,
) -> dict:
    if request.target in HIGH_RISK_TARGETS and not request.confirmed_risk:
        raise NicChangeError(
            "changing the control NIC requires confirmed_risk=True "
            "(this is the NIC the WebGUI/SSH are reached through)"
        )

    backup_dir = _backup_dir_for_now()
    _backup_existing_file(request.target, backup_dir)

    target_path = netplan_file_for(request.target)
    new_content = render_netplan_yaml(
        request.interface, request.mode, request.address, request.prefix, request.gateway
    )

    NETPLAN_DIR.mkdir(parents=True, exist_ok=True)
    original_existed = target_path.exists()
    original_content = target_path.read_text(encoding="utf-8") if original_existed else None
    target_path.write_text(new_content, encoding="utf-8")

    try:
        _validate_netplan(run)
    except NicChangeError:
        # Roll the file itself back immediately -- this failure is
        # detected synchronously, so there is no need to wait for the
        # timeout-based rollback path.
        if original_existed and original_content is not None:
            target_path.write_text(original_content, encoding="utf-8")
        else:
            target_path.unlink(missing_ok=True)
        raise

    state = network_state.begin_pending(
        backup_path=str(backup_dir),
        changed_targets=[request.target],
        timeout_seconds=request.timeout_seconds,
    )
    log_store.log_event(
        "network",
        "warning",
        f"NIC設定変更を適用し再起動を予約しました (target={request.target})。"
        f"{request.timeout_seconds}秒以内にWebGUIから確認操作が行われない場合は自動的にロールバックされます。",
        target=request.target,
        interface=request.interface,
        mode=request.mode,
        backup_path=str(backup_dir),
    )
    reboot_fn()
    return state


def confirm_change() -> dict:
    state = network_state.confirm()
    log_store.log_event("network", "info", "NIC設定変更が確認され、確定しました。")
    return state


def restore_backup(target: str, backup_dir: Path) -> None:
    target_path = netplan_file_for(target)
    backed_up_file = backup_dir / f"{target}.yaml"
    backed_up_absent_marker = backup_dir / f"{target}.absent"
    if backed_up_file.exists():
        shutil.copy2(backed_up_file, target_path)
    elif backed_up_absent_marker.exists():
        target_path.unlink(missing_ok=True)
    # else: no backup recorded for this target; leave current file as-is.


def perform_rollback_if_expired(
    reboot_fn: Callable[[], None] = _default_reboot,
) -> Optional[dict]:
    """Entry point for scripts/nic_rollback_check.py, run periodically by
    multiviewer-nic-rollback.timer. Returns the new state if a rollback was
    performed, else None."""
    state = network_state.load_state()
    if state["status"] != "pending_confirm":
        return None
    if not network_state.is_expired(state):
        return None

    backup_dir = Path(state["backup_path"]) if state["backup_path"] else None
    for target in state.get("changed_targets", []):
        if backup_dir is not None:
            restore_backup(target, backup_dir)

    if shutil.which("netplan") is not None:
        subprocess.run(["netplan", "generate"], capture_output=True, text=True, timeout=10, check=False)

    new_state = network_state.mark_rolled_back(
        "confirmation timeout elapsed; restored previous netplan configuration"
    )
    log_store.log_event(
        "network",
        "error",
        "NIC設定変更が確認時間内に確定されなかったため、自動的に以前の設定へロールバックし再起動します。",
        changed_targets=state.get("changed_targets", []),
    )
    reboot_fn()
    return new_state
