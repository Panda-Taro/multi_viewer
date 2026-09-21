"""mDNS & DNS-SD discovery of NMOS Registries (requirement 4.7.1.2 /
6.3.1.4: service type `_nmos-register._tcp`).

Stage 2b was rolled out in 3 steps: (1) discovery-only spike, confirmed
against a real environment (no avahi-daemon, systemd-resolved mDNS
disabled, a real nmos-cpp Registry discovered successfully -- see
README.md "mDNS discovery" for the confirmed results and the `api_ver`
comma-separated-list bug that testing caught), (2) integration into
registration_client.py (priority selection + failover, this module's
`select_best_registry`), (3) WebGUI display. All three are now wired up.

This system never advertises itself over mDNS (it has no need to be
discovered -- it is Receiver-only, requirement 4.7.3), so it only ever
browses, never registers a service of its own. That significantly limits
the blast radius of any mDNS conflict compared to a node that also
announces itself.
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
    def supported_api_versions(self) -> list[str]:
        """`api_ver` (AMWA BCP-002-01) is a COMMA-SEPARATED LIST of every
        version the registry supports (e.g. "v1.0,v1.1,v1.2,v1.3"), not a
        single version -- confirmed against a real nmos-cpp Registry's
        advertisement during step 2b stage 1 testing. An earlier revision
        of this code embedded the raw string directly into a URL path,
        producing an invalid URL; do not do that again."""
        raw = self.txt.get("api_ver", "")
        return [v.strip() for v in raw.split(",") if v.strip()]

    # Registration client (registration_client.py) and the resource JSON
    # this system builds (resources.py) target this shape; prefer the
    # newest of these the registry actually advertises.
    _PREFERRED_VERSIONS = ("v1.3", "v1.2", "v1.1")

    @property
    def registration_base_url(self) -> Optional[str]:
        """Best-effort Registration API base URL for the first address
        this registry advertised, picking the highest version from
        `_PREFERRED_VERSIONS` that the registry actually supports (falling
        back to whatever it does advertise, or "v1.3" if it advertised no
        usable version list at all). Returns None if there is no address."""
        if not self.addresses:
            return None
        versions = self.supported_api_versions
        version = next((v for v in self._PREFERRED_VERSIONS if v in versions), None)
        if version is None:
            version = versions[0] if versions else "v1.3"
        protocol = self.txt.get("api_proto", "http")
        return f"{protocol}://{self.addresses[0]}:{self.port}/x-nmos/registration/{version}/"


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


def select_best_registry(
    registries: list[DiscoveredRegistry],
    exclude_names: Optional[set[str]] = None,
) -> Optional[DiscoveredRegistry]:
    """Stage 2b step 2: pick the highest-priority (lowest `pri`) discovered
    registry, per AMWA BCP-002-01. A registry with no usable `pri` value
    (missing or non-numeric) is treated as lowest priority -- it sorts
    after every registry that advertised a real one, but is still
    selectable if it is the only registry found.

    `exclude_names` lets a caller doing failover skip a registry that just
    failed a heartbeat (registration_client.py's `_resolve_auto`), so a
    still-mDNS-visible-but-unresponsive registry doesn't just get
    reselected forever. If excluding leaves nothing, falls back to
    considering the full list -- a flaky lone registry is still better
    than none."""
    if not registries:
        return None

    candidates = registries
    if exclude_names:
        filtered = [r for r in registries if r.name not in exclude_names]
        if filtered:
            candidates = filtered

    def sort_key(registry: DiscoveredRegistry) -> tuple[bool, int]:
        priority = registry.priority
        return (priority is None, priority if priority is not None else 0)

    return sorted(candidates, key=sort_key)[0]
