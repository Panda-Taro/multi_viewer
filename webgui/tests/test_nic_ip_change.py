import subprocess

import pytest


class FakeReboot:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def test_render_netplan_yaml_static(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    yaml_text = nic_ip_change.render_netplan_yaml("eth0", "static", "192.168.10.10", 24, "192.168.10.1")
    assert "eth0" in yaml_text
    assert "192.168.10.10/24" in yaml_text
    assert "via: 192.168.10.1" in yaml_text
    assert "dhcp4: false" in yaml_text


def test_render_netplan_yaml_dhcp(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    yaml_text = nic_ip_change.render_netplan_yaml("eth0", "dhcp", "", 24, "")
    assert "dhcp4: true" in yaml_text


def test_render_netplan_yaml_static_requires_address(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    with pytest.raises(nic_ip_change.NicChangeError):
        nic_ip_change.render_netplan_yaml("eth0", "static", "", 24, "")


def test_control_target_requires_confirmed_risk(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    request = nic_ip_change.NicChangeRequest(
        target="control", interface="eth0", mode="static", address="192.168.1.5", prefix=24
    )
    with pytest.raises(nic_ip_change.NicChangeError):
        nic_ip_change.apply_change(request, reboot_fn=FakeReboot())


def test_control_target_succeeds_with_confirmed_risk(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    reboot = FakeReboot()
    request = nic_ip_change.NicChangeRequest(
        target="control", interface="eth0", mode="static", address="192.168.1.5", prefix=24,
        confirmed_risk=True,
    )
    result = nic_ip_change.apply_change(request, reboot_fn=reboot)
    assert result["status"] == "rebooting"
    assert reboot.calls == 1


def test_apply_change_writes_file_and_reboots_immediately(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    reboot = FakeReboot()

    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="192.168.20.10", prefix=24
    )
    result = nic_ip_change.apply_change(request, reboot_fn=reboot)

    assert result["status"] == "rebooting"
    assert reboot.calls == 1
    target_path = nic_ip_change.netplan_file_for("media_amber")
    assert target_path.exists()
    assert "192.168.20.10/24" in target_path.read_text(encoding="utf-8")


def test_apply_change_restores_original_on_validation_failure(isolated_dirs, monkeypatch):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    target_path = nic_ip_change.netplan_file_for("media_amber")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    original = "network:\n  version: 2\n  ethernets:\n    eth1:\n      dhcp4: true\n"
    target_path.write_text(original, encoding="utf-8")

    monkeypatch.setattr(nic_ip_change.shutil, "which", lambda name: "/usr/sbin/netplan")

    def failing_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="bad yaml")

    reboot = FakeReboot()
    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="10.0.0.5", prefix=24
    )
    with pytest.raises(nic_ip_change.NicChangeError):
        nic_ip_change.apply_change(request, run=failing_run, reboot_fn=reboot)

    assert target_path.read_text(encoding="utf-8") == original
    assert reboot.calls == 0


def test_apply_change_removes_file_on_validation_failure_when_none_existed_before(isolated_dirs, monkeypatch):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    target_path = nic_ip_change.netplan_file_for("media_blue")
    assert not target_path.exists()

    monkeypatch.setattr(nic_ip_change.shutil, "which", lambda name: "/usr/sbin/netplan")

    def failing_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="bad yaml")

    request = nic_ip_change.NicChangeRequest(
        target="media_blue", interface="eth2", mode="static", address="10.0.0.5", prefix=24
    )
    with pytest.raises(nic_ip_change.NicChangeError):
        nic_ip_change.apply_change(request, run=failing_run, reboot_fn=FakeReboot())

    assert not target_path.exists()
