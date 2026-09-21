def test_log_event_then_read_events_returns_newest_first(isolated_dirs):
    log_store = isolated_dirs["log_store"]
    log_store.log_event("test", "info", "first")
    log_store.log_event("test", "warning", "second")

    events = log_store.read_events()
    assert [e["message"] for e in events] == ["second", "first"]
    assert events[0]["level"] == "warning"


def test_read_events_returns_empty_list_when_no_log_file(isolated_dirs):
    log_store = isolated_dirs["log_store"]
    assert log_store.read_events() == []


def test_log_store_trims_to_max_lines(isolated_dirs, monkeypatch):
    log_store = isolated_dirs["log_store"]
    monkeypatch.setattr(log_store, "MAX_LINES_KEPT", 5)
    for i in range(10):
        log_store.log_event("test", "info", f"event-{i}")

    with open(log_store.LOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 5
