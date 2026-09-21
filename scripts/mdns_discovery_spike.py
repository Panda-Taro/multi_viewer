#!/usr/bin/env python3
"""Stage 2b, step 1 spike: browse `_nmos-register._tcp` and print what is
found. Read-only -- this does not register anything, and this system does
not advertise itself over mDNS (see mdns_discovery.py's docstring).

**Run this on the actual target server, not the Windows dev machine.**
Before running it, check for mDNS conflicts (avahi-daemon and
systemd-resolved both use UDP 5353):

    systemctl status avahi-daemon
    resolvectl mdns
    ss -ulnp | grep 5353

For a second opinion independent of this script/zeroconf, if avahi-utils
is installed you can also cross-check with:

    avahi-browse -rt _nmos-register._tcp

Usage (from the repo root, using the venv setup.sh created):

    /opt/multiviewer/venv/bin/python scripts/mdns_discovery_spike.py [seconds]

Or from a plain checkout with zeroconf installed in the current env:

    python scripts/mdns_discovery_spike.py [seconds]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webgui"))

from app.nmos.mdns_discovery import discover_registries  # noqa: E402


def main() -> int:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    print(f"Browsing _nmos-register._tcp for {timeout:.0f}s ...")
    registries = discover_registries(timeout_seconds=timeout)

    if not registries:
        print("No NMOS Registries found via mDNS.")
        print("If one is known to be broadcasting on this LAN, see the")
        print("conflict-check commands in this script's docstring.")
        return 1

    print(f"Found {len(registries)} registrie(s):")
    for r in registries:
        print(f"  name={r.name!r}")
        print(f"    server={r.server!r} addresses={r.addresses} port={r.port}")
        print(f"    priority(pri)={r.priority} txt={r.txt}")
        print(f"    registration_base_url={r.registration_base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
