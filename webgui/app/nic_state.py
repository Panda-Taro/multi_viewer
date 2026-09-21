"""Read-only view of the current OS network state.

Per requirement 4.8.4.4.1.1, the WebGUI must reflect whatever the OS
actually reports rather than caching its own idea of NIC state -- that way
the same build works unmodified on a different machine, driven purely by
what the operator configures through the GUI.

On a non-Linux dev machine (this project is edited on Windows, deployed on
Ubuntu Server) the `ip` command is unavailable; every function here
degrades to returning empty/zeroed data instead of raising, so the app and
its tests run the same way on both platforms.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def _run_json(args: list[str]) -> Any:
    if shutil.which(args[0]) is None:
        return None
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def list_interfaces() -> list[dict[str, Any]]:
    """Return [{name, state, mac, addresses: [{address, prefix, family}]}]."""
    data = _run_json(["ip", "-j", "addr", "show"])
    if data is None:
        return []
    interfaces = []
    for link in data:
        addresses = [
            {
                "address": a.get("local"),
                "prefix": a.get("prefixlen"),
                "family": a.get("family"),
            }
            for a in link.get("addr_info", [])
            if a.get("family") == "inet"
        ]
        interfaces.append(
            {
                "name": link.get("ifname"),
                "state": link.get("operstate", "unknown"),
                "mac": link.get("address", ""),
                "addresses": addresses,
            }
        )
    return interfaces


def interface_stats(name: str) -> dict[str, Any]:
    """Cumulative rx/tx byte counters for one interface, read from sysfs.

    Only a snapshot; the dashboard polls this periodically client-side and
    derives a rough bandwidth figure from the delta itself, so no
    background sampling daemon is needed for step 1.
    """
    try:
        rx = int(open(f"/sys/class/net/{name}/statistics/rx_bytes").read().strip())
        tx = int(open(f"/sys/class/net/{name}/statistics/tx_bytes").read().strip())
    except OSError:
        return {"rx_bytes": None, "tx_bytes": None}
    return {"rx_bytes": rx, "tx_bytes": tx}


def list_physical_interface_names() -> list[str]:
    """Interface names excluding loopback/virtual, for populating the NIC
    picker in the network settings form."""
    names = []
    for iface in list_interfaces():
        name = iface["name"]
        if name and name != "lo" and not name.startswith(("docker", "veth", "br-")):
            names.append(name)
    return names
