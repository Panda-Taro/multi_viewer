#!/usr/bin/env python3
"""Run periodically by multiviewer-nic-rollback.timer.

If a NIC IP change is pending confirmation and the confirmation window has
elapsed, restores the previous netplan configuration and reboots. This is
the self-lockout safety net described in README.md; it must not depend on
the WebGUI process being alive, since a broken control-NIC address could
also have made the WebGUI unreachable.
"""
import sys
from pathlib import Path

# Deployed layout is /opt/multiviewer/{nic_rollback_check.py,webgui/}; the
# in-repo layout (used for tests) is <repo>/scripts/nic_rollback_check.py
# with <repo>/webgui/ as a sibling directory. Try both so the same file
# works unmodified in either location.
_here = Path(__file__).resolve().parent
for _candidate in (_here / "webgui", _here.parent / "webgui"):
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))
        break

from app import nic_ip_change  # noqa: E402


def main() -> int:
    result = nic_ip_change.perform_rollback_if_expired()
    if result is not None:
        print(f"rolled back: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
