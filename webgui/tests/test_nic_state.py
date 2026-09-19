import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import json
import pytest
from app.nic_state import parse_ip_addr_json, classify_nics, NicStateError

SAMPLE = json.dumps(
    [
        {
            "ifname": "lo",
            "operstate": "UNKNOWN",
            "address": "00:00:00:00:00:00",
            "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
        },
        {
            "ifname": "amber0",
            "operstate": "UP",
            "address": "aa:bb:cc:00:00:01",
            "addr_info": [{"family": "inet", "local": "192.168.100.1", "prefixlen": 24}],
        },
        {
            "ifname": "blue0",
            "operstate": "DOWN",
            "address": "aa:bb:cc:00:00:02",
            "addr_info": [],
        },
        {
            "ifname": "eth0",
            "operstate": "UP",
            "address": "aa:bb:cc:00:00:03",
            "addr_info": [{"family": "inet", "local": "192.168.10.10", "prefixlen": 24}],
        },
    ]
)


def test_parse_excludes_loopback():
    nics = parse_ip_addr_json(SAMPLE)
    names = [n.name for n in nics]
    assert "lo" not in names
    assert set(names) == {"amber0", "blue0", "eth0"}


def test_parse_up_down_state():
    nics = {n.name: n for n in parse_ip_addr_json(SAMPLE)}
    assert nics["amber0"].up is True
    assert nics["blue0"].up is False


def test_parse_ipv4_addresses():
    nics = {n.name: n for n in parse_ip_addr_json(SAMPLE)}
    assert nics["amber0"].primary_ipv4 == "192.168.100.1/24"
    assert nics["blue0"].ipv4_addresses == []


def test_parse_rejects_invalid_json():
    with pytest.raises(NicStateError):
        parse_ip_addr_json("not json")


def test_classify_nics_maps_roles():
    nics = parse_ip_addr_json(SAMPLE)
    classified = classify_nics(nics, amber_name="amber0", blue_name="blue0", control_name="eth0")
    assert classified["amber"].name == "amber0"
    assert classified["blue"].name == "blue0"
    assert classified["control"].name == "eth0"
    assert classified["unclassified"] == []
