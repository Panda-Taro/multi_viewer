import subprocess

import pytest


def _noop_reboot():
    pass


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
        nic_ip_change.apply_change(request, reboot_fn=_noop_reboot)


def test_apply_change_backs_up_absent_file_and_sets_pending(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    network_state = isolated_dirs["network_state"]
    reboot = FakeReboot()

    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="192.168.20.10", prefix=24
    )
    state = nic_ip_change.apply_change(request, reboot_fn=reboot)

    assert state["status"] == "pending_confirm"
    assert reboot.calls == 1
    assert nic_ip_change.netplan_file_for("media_amber").exists()

    backup_dir = list(nic_ip_change.BACKUP_ROOT.iterdir())[0]
    assert (backup_dir / "media_amber.absent").exists()
    assert network_state.load_state()["status"] == "pending_confirm"


def test_apply_change_backs_up_existing_file_content(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    target_path = nic_ip_change.netplan_file_for("media_blue")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("network:\n  version: 2\n  ethernets:\n    eth2:\n      dhcp4: true\n", encoding="utf-8")

    request = nic_ip_change.NicChangeRequest(
        target="media_blue", interface="eth2", mode="static", address="192.168.30.10", prefix=24
    )
    nic_ip_change.apply_change(request, reboot_fn=FakeReboot())

    backup_dir = list(nic_ip_change.BACKUP_ROOT.iterdir())[0]
    backed_up = (backup_dir / "media_blue.yaml").read_text(encoding="utf-8")
    assert "dhcp4: true" in backed_up
    assert "192.168.30.10" in target_path.read_text(encoding="utf-8")


def test_apply_change_restores_original_on_validation_failure(isolated_dirs, monkeypatch):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    target_path = nic_ip_change.netplan_file_for("media_amber")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    original = "network:\n  version: 2\n  ethernets:\n    eth1:\n      dhcp4: true\n"
    target_path.write_text(original, encoding="utf-8")

    monkeypatch.setattr(nic_ip_change.shutil, "which", lambda name: "/usr/sbin/netplan")

    def failing_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="bad yaml")

    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="10.0.0.5", prefix=24
    )
    with pytest.raises(nic_ip_change.NicChangeError):
        nic_ip_change.apply_change(request, run=failing_run, reboot_fn=FakeReboot())

    assert target_path.read_text(encoding="utf-8") == original


def test_confirm_change_clears_pending_state(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="10.0.0.5", prefix=24
    )
    nic_ip_change.apply_change(request, reboot_fn=FakeReboot())
    state = nic_ip_change.confirm_change()
    assert state["status"] == "stable"


def test_rollback_is_noop_when_stable(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    reboot = FakeReboot()
    result = nic_ip_change.perform_rollback_if_expired(reboot_fn=reboot)
    assert result is None
    assert reboot.calls == 0


def test_rollback_is_noop_when_pending_but_not_expired(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    reboot = FakeReboot()
    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="10.0.0.5", prefix=24,
        timeout_seconds=300,
    )
    nic_ip_change.apply_change(request, reboot_fn=FakeReboot())

    result = nic_ip_change.perform_rollback_if_expired(reboot_fn=reboot)
    assert result is None
    assert reboot.calls == 0


def test_rollback_restores_backup_and_reboots_when_expired(isolated_dirs):
    nic_ip_change = isolated_dirs["nic_ip_change"]
    network_state = isolated_dirs["network_state"]
    target_path = nic_ip_change.netplan_file_for("media_amber")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    original = "network:\n  version: 2\n  ethernets:\n    eth1:\n      dhcp4: true\n"
    target_path.write_text(original, encoding="utf-8")

    request = nic_ip_change.NicChangeRequest(
        target="media_amber", interface="eth1", mode="static", address="10.0.0.5", prefix=24,
        timeout_seconds=1,
    )
    nic_ip_change.apply_change(request, reboot_fn=FakeReboot())

    # Force expiry the same way test_network_state does.
    from datetime import datetime, timedelta, timezone

    state = network_state.load_state()
    state["pending_since"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    network_state._save_state_locked(state)

    reboot = FakeReboot()
    result = nic_ip_change.perform_rollback_if_expired(reboot_fn=reboot)

    assert result is not None
    assert result["status"] == "rolled_back"
    assert reboot.calls == 1
    assert target_path.read_text(encoding="utf-8") == original
