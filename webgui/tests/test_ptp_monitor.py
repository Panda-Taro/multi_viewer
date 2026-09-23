import importlib


def _reload(monkeypatch, tmp_path):
    config_dir = tmp_path / "etc-multiviewer"
    log_dir = tmp_path / "var-log-multiviewer"
    config_dir.mkdir()
    log_dir.mkdir()
    monkeypatch.setenv("MULTIVIEWER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MULTIVIEWER_LOG_DIR", str(log_dir))

    from app import log_store
    from app.ptp import monitor, pmc_client, status_store

    importlib.reload(log_store)
    importlib.reload(status_store)
    importlib.reload(monitor)
    return monitor, pmc_client, status_store, log_store


def test_poll_once_writes_syncing_before_enough_samples(tmp_path, monkeypatch):
    monitor, pmc_client, status_store, _ = _reload(monkeypatch, tmp_path)

    monkeypatch.setattr(
        pmc_client, "get_time_status", lambda uds: {"master_offset_ns": 50, "gm_present": True, "gm_id": "abc"}
    )
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: "SLAVE")

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")
    mon.poll_once(domain=127)

    status = status_store.read_status()
    assert status["legs"]["amber"]["state"] == "syncing"
    assert status["legs"]["amber"]["sample_count"] == 1


def test_poll_once_reaches_normal_after_enough_low_jitter_samples(tmp_path, monkeypatch):
    monitor, pmc_client, status_store, _ = _reload(monkeypatch, tmp_path)
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: "SLAVE")

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")
    # All samples identical -> jitter (stdev) is exactly 0, well within
    # the hardware threshold.
    monkeypatch.setattr(
        pmc_client, "get_time_status", lambda uds: {"master_offset_ns": 10, "gm_present": True, "gm_id": "abc"}
    )
    for _ in range(monitor.WINDOW_SIZE):
        mon.poll_once(domain=127)

    status = status_store.read_status()
    assert status["legs"]["amber"]["state"] == "normal"
    assert status["legs"]["amber"]["jitter_ns"] == 0.0


def test_poll_once_reports_gm_not_found_when_listening(tmp_path, monkeypatch):
    monitor, pmc_client, status_store, _ = _reload(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pmc_client, "get_time_status", lambda uds: {"master_offset_ns": 0, "gm_present": False, "gm_id": None}
    )
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: "LISTENING")

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")
    mon.poll_once(domain=127)

    status = status_store.read_status()
    assert status["legs"]["amber"]["state"] == "gm_not_found"


def test_poll_once_skips_write_when_pmc_unreachable(tmp_path, monkeypatch):
    """A transient pmc failure must not fabricate a state -- the status
    file should simply not be touched this cycle, letting it go stale
    (and eventually read as "unknown") rather than reporting something
    false."""
    monitor, pmc_client, status_store, _ = _reload(monkeypatch, tmp_path)
    monkeypatch.setattr(pmc_client, "get_time_status", lambda uds: None)
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: None)

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")
    mon.poll_once(domain=127)

    status = status_store.read_status()
    assert status["legs"]["amber"] is None


def test_poll_once_logs_on_state_transition(tmp_path, monkeypatch):
    monitor, pmc_client, status_store, log_store = _reload(monkeypatch, tmp_path)
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: "LISTENING")
    monkeypatch.setattr(
        pmc_client, "get_time_status", lambda uds: {"master_offset_ns": 0, "gm_present": False, "gm_id": None}
    )

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")
    mon.poll_once(domain=127)
    mon.poll_once(domain=127)  # same state again -- must not log a second time

    events = [e for e in log_store.read_events() if e["source"] == "ptp" and "状態が変化" in e["message"]]
    assert len(events) == 1


def test_run_forever_stops_when_should_continue_returns_false(tmp_path, monkeypatch):
    monitor, pmc_client, status_store, _ = _reload(monkeypatch, tmp_path)
    monkeypatch.setattr(pmc_client, "get_port_state", lambda uds: "SLAVE")
    monkeypatch.setattr(
        pmc_client, "get_time_status", lambda uds: {"master_offset_ns": 1, "gm_present": True, "gm_id": "abc"}
    )

    mon = monitor.LegMonitor("amber", interface="eth0", timestamping_mode="hardware", uds_address="/tmp/x.sock")

    calls = {"n": 0}

    def should_continue():
        calls["n"] += 1
        return calls["n"] <= 3

    sleeps = []
    monitor.run_forever([mon], domain=127, should_continue=should_continue, sleep=sleeps.append)

    assert calls["n"] == 4  # 3 True + 1 False
    assert len(sleeps) == 3
