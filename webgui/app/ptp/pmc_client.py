"""Wraps linuxptp's `pmc` management client to poll a running ptp4l
instance's status over its Unix Domain Socket management interface.

Output parsing note: pmc's field-printing code (linuxptp's pmc.c,
`pmc_show()`) prefixes every field line with two tabs (the `IFMT` macro,
`"\\n\\t\\t"`) and separates each field name from its value with a single
space -- confirmed against the linuxptp source itself, not guessed. This
module does not depend on the exact format of the header line printed
above the fields (the "<clockIdentity>-<port> seq N RESPONSE MANAGEMENT
<NAME>" line); it just treats every line starting with whitespace as a
"name value" pair and looks up the specific field names it needs, so
variation in that header line's exact format cannot break the parser --
at worst it adds a harmless unused key to the parsed dict.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any, Optional

DEFAULT_TIMEOUT_SECONDS = 3.0


def _run_pmc(uds_address: str, query: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Optional[str]:
    if shutil.which("pmc") is None:
        return None
    try:
        result = subprocess.run(
            ["pmc", "-u", "-b", "0", "-s", uds_address, query],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def parse_fields(output: str) -> dict[str, str]:
    """Every indented line becomes one name/value pair, keyed by its first
    whitespace-separated token. Lines that don't start with whitespace
    (e.g. the leading "sending: GET ..." echo) are ignored."""
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if not line or not line[:1].isspace():
            continue
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            fields[parts[0]] = parts[1]
    return fields


def get_time_status(uds_address: str) -> Optional[dict[str, Any]]:
    """Queries `GET TIME_STATUS_NP`. Returns None if pmc could not be
    reached or the reply didn't contain the fields expected (ptp4l not
    running yet, management socket not ready, etc.) -- callers should
    treat that as "this poll cycle failed", not as any particular PTP
    state, and simply try again next cycle."""
    output = _run_pmc(uds_address, "GET TIME_STATUS_NP")
    if output is None:
        return None
    fields = parse_fields(output)
    if "gmPresent" not in fields:
        return None
    offset_raw = fields.get("master_offset")
    try:
        offset_ns: Optional[int] = int(offset_raw) if offset_raw is not None else None
    except ValueError:
        offset_ns = None
    return {
        "master_offset_ns": offset_ns,
        "gm_present": fields.get("gmPresent") == "true",
        "gm_id": fields.get("gmIdentity"),
    }


def get_port_state(uds_address: str) -> Optional[str]:
    """Queries `GET PORT_DATA_SET`, returning the `portState` field
    (e.g. "LISTENING", "UNCALIBRATED", "SLAVE") or None if unreachable."""
    output = _run_pmc(uds_address, "GET PORT_DATA_SET")
    if output is None:
        return None
    fields = parse_fields(output)
    return fields.get("portState")
