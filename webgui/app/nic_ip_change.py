"""Applies OS-level NIC IP address changes.

Writes a netplan file for the given target and reboots the server so the
new address takes effect on boot (requirement 7.5.2: IP changes assume a
reboot). Before committing, the new file is validated with
`netplan generate` (a dry run that does not touch the live network); on
failure the previous file content is restored and nothing is rebooted.

There is deliberately no backup/confirm/auto-rollback mechanism here: an
earlier revision of this module had one (see git history), but the
operator asked for changes to apply immediately and stay applied, with no
automatic recovery step. A misconfigured control NIC can therefore make
the WebGUI/SSH unreachable with no automatic way back -- see README.md for
the operational precautions this requires (verify settings before
confirming, keep a physical console/IPMI path available).

The control NIC (WebGUI/SSH access) still requires an explicit
`confirmed_risk=True` flag from the caller, since breaking it is harder to
recover from than breaking a media NIC.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import log_store

NETPLAN_DIR = Path(os.environ.get("MULTIVIEWER_NETPLAN_DIR", "/etc/netplan"))

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


def _default_reboot() -> None:
    if shutil.which("reboot") is None:
        return
    subprocess.run(["reboot"], check=False)


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
        # Detected synchronously: put the previous file content back
        # immediately so an invalid config never reaches a reboot.
        if original_existed and original_content is not None:
            target_path.write_text(original_content, encoding="utf-8")
        else:
            target_path.unlink(missing_ok=True)
        raise

    log_store.log_event(
        "network",
        "warning",
        f"NIC設定変更を適用し、サーバーを再起動します (target={request.target})。",
        target=request.target,
        interface=request.interface,
        mode=request.mode,
    )
    reboot_fn()
    return {"status": "rebooting", "target": request.target}
