"""ptp4l configuration file generation (step 3a, requirement 6-4 / 4-3-5).

Every setting here is fixed by requirement 6-4 (SMPTE ST 2059-2 profile) or
by values sourced from published SMPTE ST 2059-2 PTP profile parameter
references (domain 127, logSyncInterval -3, logAnnounceInterval 0,
logMinDelayReqInterval -3, announceReceiptTimeout 3, End-to-End delay
mechanism) -- linuxptp itself does not ship a bundled SMPTE2059-2.cfg to
copy from, so these were cross-checked against two independent vendor
references rather than guessed; see NOTES.md "ST2059-2プロファイルの
各interval値の根拠" for the sources and reasoning. The one
operator-configurable value is the PTP domain (config.json's ptp.domain,
requirement 6-4-2).

`clientOnly 1` (requirement 4.3.5, 9.3.3) is NEVER derived from
config.json, WebGUI input, or any other runtime value -- it is a Python
literal in this module, with no code path that could make it anything
else. validate_client_only() exists specifically so both a unit test and
a startup self-check (ptp_main.py) can assert this holds for whatever
text this module actually produced.
"""
from __future__ import annotations

from pathlib import Path

# Requirement 4.3.5 / 9.3.3: this system must never behave as a PTP
# Master. Hardcoded -- see module docstring. Do not make this derived
# from config.json, a function argument, or any other input.
CLIENT_ONLY_LINE = "clientOnly              1"

TIMESTAMPING_HARDWARE = "hardware"
TIMESTAMPING_SOFTWARE = "software"

_VALID_TIMESTAMPING_MODES = (TIMESTAMPING_HARDWARE, TIMESTAMPING_SOFTWARE)


def generate_ptp4l_config(interface: str, domain: int, timestamping_mode: str, uds_address: str) -> str:
    """Returns the full contents of a ptp4l.conf for a single-port
    client-only ST 2059-2 profile session on `interface`."""
    if timestamping_mode not in _VALID_TIMESTAMPING_MODES:
        raise ValueError(f"unknown timestamping_mode: {timestamping_mode!r}")
    if not interface:
        raise ValueError("interface must not be empty")

    lines = [
        "[global]",
        CLIENT_ONLY_LINE,
        f"domainNumber            {domain}",
        "priority1               128",
        "priority2               128",
        # SMPTE ST 2059-2 profile message rates -- see module docstring.
        "logAnnounceInterval     0",
        "logSyncInterval         -3",
        "logMinDelayReqInterval  -3",
        "announceReceiptTimeout  3",
        "delay_mechanism         E2E",
        "network_transport       UDPv4",
        f"time_stamping           {timestamping_mode}",
        f"uds_address             {uds_address}",
        "",
        f"[{interface}]",
        "",
    ]
    return "\n".join(lines)


def validate_client_only(text: str) -> bool:
    """True iff `text` actually contains the hardcoded clientOnly
    directive, unmodified and uncommented. Used both as a unit-testable
    assertion and as ptp_main.py's startup self-check (requirement
    4.3.5's "起動時に設定ファイルを検査し..." defense-in-depth ask)."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        parts = stripped.split()
        if len(parts) == 2 and parts[0] == "clientOnly" and parts[1] == "1":
            return True
    return False


def write_ptp4l_config(
    path: Path, interface: str, domain: int, timestamping_mode: str, uds_address: str
) -> None:
    """Always regenerates the file from scratch -- never reads back an
    existing file to merge with it. That is itself part of the clientOnly
    defense: there is no code path by which a hand-edited config on disk
    could survive past the next service (re)start."""
    text = generate_ptp4l_config(interface, domain, timestamping_mode, uds_address)
    if not validate_client_only(text):
        # Unreachable in practice -- generate_ptp4l_config() always emits
        # CLIENT_ONLY_LINE above. Treated as a hard failure rather than
        # silently writing a file that could let this system announce
        # itself as a PTP master (requirement 4.3.5).
        raise RuntimeError("internal error: generated ptp4l config is missing 'clientOnly 1'")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
