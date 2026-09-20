import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pytest
from igmp import plan_joins, plan_leaves, IgmpError


def test_plan_joins_returns_amber_and_blue():
    plans = plan_joins(
        group="239.1.1.10",
        source="192.168.1.50",
        amber_iface="amber0",
        amber_ip="192.168.100.1",
        blue_iface="blue0",
        blue_ip="192.168.101.1",
    )
    assert len(plans) == 2
    interfaces = {p.interface_name for p in plans}
    assert interfaces == {"amber0", "blue0"}
    for p in plans:
        assert p.group == "239.1.1.10"
        assert p.source == "192.168.1.50"


def test_plan_joins_rejects_empty_group():
    with pytest.raises(IgmpError):
        plan_joins("", "192.168.1.50", "a", "1.1.1.1", "b", "2.2.2.2")


def test_plan_joins_rejects_invalid_ipv4():
    with pytest.raises(IgmpError):
        plan_joins("not-an-ip", "192.168.1.50", "a", "1.1.1.1", "b", "2.2.2.2")


def test_plan_joins_rejects_invalid_source():
    with pytest.raises(IgmpError):
        plan_joins("239.1.1.10", "not-an-ip", "a", "1.1.1.1", "b", "2.2.2.2")


def test_plan_leaves_targets_amber_and_blue_same_as_join():
    """④-8-4-2-1補足仕様: Leaveの対象決定はJoinと同じ(Amber/Blue両系統)。"""
    plans = plan_leaves(
        group="239.1.1.10",
        source="192.168.1.50",
        amber_iface="amber0",
        amber_ip="192.168.100.1",
        blue_iface="blue0",
        blue_ip="192.168.101.1",
    )
    assert {p.interface_name for p in plans} == {"amber0", "blue0"}
