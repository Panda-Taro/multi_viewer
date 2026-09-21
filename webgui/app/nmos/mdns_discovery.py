"""mDNS & DNS-SD discovery of NMOS Registries (requirement 4.7.1.2 /
6.3.1.4: service type `_nmos-register._tcp`).

**Stage 2b, step 1 only** (per the staged rollout requested for this
step): this module browses for registries and returns what it finds. It
is deliberately NOT wired into registration_client.py yet -- rds_discovery
== "auto" still reports "disabled" there. Priority selection, failover,
and the actual switch-over to the discovered registry are stage 2, held
back until this discovery step itself is confirmed working against a real
mDNS environment (see scripts/mdns_discovery_spike.py and README.md
"mDNS discovery" section for why: mDNS behaviour is environment-dependent,
notably around avahi-daemon/systemd-resolved sharing UDP 5353).

This system never advertises itself over mDNS (it has no Node API to
discover it by -- see NOTES.md), so it only ever browses, never
registers a service of its own. That significantly limits the blast
radius of any mDNS conflict compared to a node that also announces itself.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

SERVICE_TYPE = "_nmos-register._tcp.local."


@dataclass
class DiscoveredRegistry:
    name: str
    addresses: list[str]
    port: int
    server: str
    txt: dict[str, str] = field(default_factory=dict)

    @property
    def priority(self) -> Optional[int]:
        """The NMOS-specific `pri` TXT record (AMWA BCP-002-01 "Natural
        Grouping"), not to be confused with zeroconf's own DNS-SD SRV
        priority field. Lower value = higher priority; `pri=0` is
        reserved for a parent/off-site registry. None if absent or not a
        valid integer -- callers (stage 2) should treat that as lowest
        priority."""
        raw = self.txt.get("pri")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @property
    def registration_base_url(self) -> Optional[str]:
        """Best-effort Registration API base URL for the highest-priority
        address this registry advertised, using the `api_ver` TXT record
        if present. Returns None if there is no usable address."""
        if not self.addresses:
            return None
        api_ver = self.txt.get("api_ver", "v1.3")
        protocol = self.txt.get("api_proto", "http")
        return f"{protocol}://{self.addresses[0]}:{self.port}/x-nmos/registration/{api_ver}/"


def _service_info_to_registry(info) -> Optional[DiscoveredRegistry]:
    if info is None:
        return None
    return DiscoveredRegistry(
        name=info.name,
        addresses=list(info.parsed_addresses()),
        port=info.port,
        server=info.server or "",
        txt=dict(info.decoded_properties or {}),
    )


def discover_registries(
    timeout_seconds: float = 5.0,
    zeroconf_factory=Zeroconf,
) -> list[DiscoveredRegistry]:
    """Blocking: browses for `_nmos-register._tcp` for `timeout_seconds`
    and returns whatever was found. Intended for the CLI spike script and,
    in a later stage, for being called from a background thread (zeroconf
    already runs its own network I/O thread internally, so this function
    itself is safe to call from a worker thread of an async application).
    """
    zc = zeroconf_factory()
    found: dict[str, DiscoveredRegistry] = {}
    lock = threading.Lock()

    def on_state_change(zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            info = zeroconf.get_service_info(service_type, name, timeout=3000)
            registry = _service_info_to_registry(info)
            with lock:
                if registry is not None:
                    found[name] = registry
                else:
                    found.pop(name, None)
        elif state_change == ServiceStateChange.Removed:
            with lock:
                found.pop(name, None)

    browser = ServiceBrowser(zc, SERVICE_TYPE, handlers=[on_state_change])
    try:
        time.sleep(timeout_seconds)
    finally:
        browser.cancel()
        zc.close()

    with lock:
        return list(found.values())
