"""Tests for the pure parsing/selection logic in mdns_discovery.py.

`discover_registries()` itself does real multicast network I/O via
zeroconf's ServiceBrowser and is intentionally NOT unit tested here -- that
is exactly what scripts/mdns_discovery_spike.py is for, run by hand
against a real mDNS environment (see README.md "mDNS discovery"). What can
be tested without a network is everything downstream of a discovered
zeroconf.ServiceInfo: converting it to our own DiscoveredRegistry, and
that dataclass's derived properties.
"""
from zeroconf import ServiceInfo

from app.nmos.mdns_discovery import DiscoveredRegistry, _service_info_to_registry


def _make_service_info(**properties: str) -> ServiceInfo:
    return ServiceInfo(
        "_nmos-register._tcp.local.",
        "Test Registry._nmos-register._tcp.local.",
        addresses=[b"\xc0\xa8\x01\x0a"],  # 192.168.1.10
        port=8010,
        properties=properties,
        server="registry-host.local.",
    )


def test_service_info_to_registry_converts_address_port_and_txt():
    info = _make_service_info(pri="100", api_ver="v1.3", api_proto="http")
    registry = _service_info_to_registry(info)

    assert registry.name == "Test Registry._nmos-register._tcp.local."
    assert registry.addresses == ["192.168.1.10"]
    assert registry.port == 8010
    assert registry.server == "registry-host.local."
    assert registry.txt == {"pri": "100", "api_ver": "v1.3", "api_proto": "http"}


def test_service_info_to_registry_returns_none_for_none_input():
    assert _service_info_to_registry(None) is None


def test_priority_parses_valid_integer():
    registry = DiscoveredRegistry(name="a", addresses=["1.2.3.4"], port=80, server="a", txt={"pri": "50"})
    assert registry.priority == 50


def test_priority_is_none_when_txt_missing():
    registry = DiscoveredRegistry(name="a", addresses=["1.2.3.4"], port=80, server="a", txt={})
    assert registry.priority is None


def test_priority_is_none_when_not_an_integer():
    registry = DiscoveredRegistry(name="a", addresses=["1.2.3.4"], port=80, server="a", txt={"pri": "not-a-number"})
    assert registry.priority is None


def test_priority_zero_is_a_valid_priority_not_falsy_none():
    """pri=0 is reserved for a parent/off-site registry per BCP-002-01 --
    it must round-trip as the integer 0, not be treated as "absent"."""
    registry = DiscoveredRegistry(name="a", addresses=["1.2.3.4"], port=80, server="a", txt={"pri": "0"})
    assert registry.priority == 0


def test_registration_base_url_uses_txt_api_version_and_protocol():
    registry = DiscoveredRegistry(
        name="a", addresses=["192.168.1.10"], port=8010, server="a",
        txt={"api_ver": "v1.2", "api_proto": "https"},
    )
    assert registry.registration_base_url == "https://192.168.1.10:8010/x-nmos/registration/v1.2/"


def test_registration_base_url_defaults_when_txt_missing():
    registry = DiscoveredRegistry(name="a", addresses=["192.168.1.10"], port=8010, server="a", txt={})
    assert registry.registration_base_url == "http://192.168.1.10:8010/x-nmos/registration/v1.3/"


def test_registration_base_url_is_none_without_addresses():
    registry = DiscoveredRegistry(name="a", addresses=[], port=8010, server="a", txt={})
    assert registry.registration_base_url is None
