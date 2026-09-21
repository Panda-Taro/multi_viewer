import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def isolated_dirs(tmp_path, monkeypatch):
    """Point every module that touches the filesystem at a throwaway
    directory tree, then reload them so their module-level path constants
    pick up the new env vars. Order matters: leaf modules before the
    routers/app that import them."""
    config_dir = tmp_path / "etc-multiviewer"
    log_dir = tmp_path / "var-log-multiviewer"
    netplan_dir = tmp_path / "etc-netplan"
    config_dir.mkdir()
    log_dir.mkdir()
    netplan_dir.mkdir()

    monkeypatch.setenv("MULTIVIEWER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MULTIVIEWER_LOG_DIR", str(log_dir))
    monkeypatch.setenv("MULTIVIEWER_NETPLAN_DIR", str(netplan_dir))

    from app import config_store, log_store, nic_ip_change
    from app.nmos import status_store as nmos_status_store

    importlib.reload(config_store)
    importlib.reload(log_store)
    importlib.reload(nic_ip_change)
    importlib.reload(nmos_status_store)

    return {
        "config_dir": config_dir,
        "log_dir": log_dir,
        "netplan_dir": netplan_dir,
        "config_store": config_store,
        "log_store": log_store,
        "nic_ip_change": nic_ip_change,
    }
