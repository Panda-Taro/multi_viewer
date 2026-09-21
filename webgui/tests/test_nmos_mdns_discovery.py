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

from app.nmos.mdns_discovery import DiscoveredRegistry, _service_info_to_registry, select_best_registry


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


def test_api_ver_is_a_comma_separated_list_not_a_single_version():
    """Regression test: a real nmos-cpp Registry discovered during step 2b
    stage 1 testing advertised api_ver="v1.0,v1.1,v1.2,v1.3". An earlier
    revision embedded that whole string into the URL path
    (".../registration/v1.0,v1.1,v1.2,v1.3/"), which is not a valid
    Registration API URL."""
    registry = DiscoveredRegistry(
        name="nmos-cpp_registration_172-17-201-11_3210._nmos-register._tcp.local.",
        addresses=["172.17.201.11"],
        port=3210,
        server="nmos-controller.local.",
        txt={"api_proto": "http", "api_ver": "v1.0,v1.1,v1.2,v1.3", "api_auth": "false", "pri": "100"},
    )
    assert registry.supported_api_versions == ["v1.0", "v1.1", "v1.2", "v1.3"]
    assert registry.registration_base_url == "http://172.17.201.11:3210/x-nmos/registration/v1.3/"


def test_registration_base_url_picks_highest_preferred_version_available():
    registry = DiscoveredRegistry(
        name="a", addresses=["1.2.3.4"], port=80, server="a", txt={"api_ver": "v1.0,v1.1,v1.2"}
    )
    assert registry.registration_base_url == "http://1.2.3.4:80/x-nmos/registration/v1.2/"


def test_registration_base_url_falls_back_to_first_advertised_version_if_none_preferred():
    registry = DiscoveredRegistry(name="a", addresses=["1.2.3.4"], port=80, server="a", txt={"api_ver": "v1.0"})
    assert registry.registration_base_url == "http://1.2.3.4:80/x-nmos/registration/v1.0/"


def _registry(name: str, pri: str | None) -> DiscoveredRegistry:
    txt = {"pri": pri} if pri is not None else {}
    return DiscoveredRegistry(name=name, addresses=["1.2.3.4"], port=80, server="a", txt=txt)


def test_select_best_registry_picks_lowest_pri():
    registries = [_registry("low-priority", "200"), _registry("high-priority", "10"), _registry("mid", "100")]
    assert select_best_registry(registries).name == "high-priority"


def test_select_best_registry_pri_zero_wins_over_any_positive_value():
    registries = [_registry("normal", "50"), _registry("parent", "0")]
    assert select_best_registry(registries).name == "parent"


def test_select_best_registry_treats_missing_priority_as_lowest():
    registries = [_registry("no-priority", None), _registry("has-priority", "999")]
    assert select_best_registry(registries).name == "has-priority"


def test_select_best_registry_returns_none_for_empty_list():
    assert select_best_registry([]) is None


def test_select_best_registry_returns_the_only_one_even_without_priority():
    registries = [_registry("only-one", None)]
    assert select_best_registry(registries).name == "only-one"
