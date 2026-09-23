import importlib


def _reload(monkeypatch, tmp_path):
    monkeypatch.setenv("MULTIVIEWER_CONFIG_DIR", str(tmp_path))
    from app.ptp import status_store

    importlib.reload(status_store)
    return status_store


def test_read_status_returns_defaults_when_no_file(tmp_path, monkeypatch):
    status_store = _reload(monkeypatch, tmp_path)
    status = status_store.read_status()
    assert status["domain"] is None
    assert status["active_leg"] is None
    assert status["legs"] == {"amber": None, "blue": None}


def test_write_leg_status_then_read_roundtrips(tmp_path, monkeypatch):
    status_store = _reload(monkeypatch, tmp_path)
    status_store.write_leg_status(
        "amber",
        domain=127,
        interface="eth0",
        timestamping_mode="hardware",
        port_state="SLAVE",
        gm_present=True,
        gm_id="00b058.feef.0b448a",
        offset_ns=100,
        jitter_ns=5.0,
        sample_count=60,
        state="normal",
    )
    status = status_store.read_status()
    assert status["domain"] == 127
    assert status["active_leg"] == "amber"
    assert status["legs"]["amber"]["interface"] == "eth0"
    assert status["legs"]["amber"]["state"] == "normal"
    assert status["legs"]["amber"]["last_sample_at"] is not None
    # Untouched leg keeps its schema slot ready for step 3b, unpopulated.
    assert status["legs"]["blue"] is None


def test_write_leg_status_rejects_unknown_leg(tmp_path, monkeypatch):
    status_store = _reload(monkeypatch, tmp_path)
    try:
        status_store.write_leg_status("green", domain=127, state="normal")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_active_leg_not_overwritten_by_a_leg_without_gm(tmp_path, monkeypatch):
    """Once amber reports gm_present, a later poll of a still-unpopulated
    blue leg (step 3b) must not clobber active_leg back to None."""
    status_store = _reload(monkeypatch, tmp_path)
    status_store.write_leg_status(
        "amber", domain=127, interface="eth0", gm_present=True, state="normal"
    )
    status_store.write_leg_status(
        "blue", domain=127, interface="eth1", gm_present=False, state="unknown"
    )
    status = status_store.read_status()
    assert status["active_leg"] == "amber"


def test_write_leg_status_is_atomic_no_partial_file_left(tmp_path, monkeypatch):
    status_store = _reload(monkeypatch, tmp_path)
    status_store.write_leg_status("amber", domain=127, state="normal")
    assert status_store.STATUS_PATH.exists()
    assert not status_store.STATUS_PATH.with_suffix(".json.tmp").exists()
