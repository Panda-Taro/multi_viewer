from datetime import datetime, timedelta, timezone


def test_initial_state_is_stable(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    state = network_state.load_state()
    assert state["status"] == "stable"


def test_begin_pending_then_confirm_returns_to_stable(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    network_state.begin_pending(backup_path="/tmp/backup", changed_targets=["control"], timeout_seconds=300)
    assert network_state.load_state()["status"] == "pending_confirm"

    confirmed = network_state.confirm()
    assert confirmed["status"] == "stable"
    assert confirmed["backup_path"] is None


def test_confirm_without_pending_change_is_a_no_op(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    state = network_state.confirm()
    assert state["status"] == "stable"


def test_is_expired_false_before_timeout(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    network_state.begin_pending(backup_path="/tmp/backup", changed_targets=["control"], timeout_seconds=300)
    assert network_state.is_expired() is False
    remaining = network_state.seconds_remaining()
    assert 290 <= remaining <= 300


def test_is_expired_true_after_timeout_elapsed(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    state = network_state.begin_pending(
        backup_path="/tmp/backup", changed_targets=["control"], timeout_seconds=1
    )
    # Simulate time passing by rewriting pending_since into the past.
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    state["pending_since"] = past.isoformat()
    network_state._save_state_locked(state)

    assert network_state.is_expired() is True
    assert network_state.seconds_remaining() == 0.0


def test_mark_rolled_back_records_reason(isolated_dirs):
    network_state = isolated_dirs["network_state"]
    network_state.begin_pending(backup_path="/tmp/backup", changed_targets=["media_amber"], timeout_seconds=300)
    state = network_state.mark_rolled_back("timeout")
    assert state["status"] == "rolled_back"
    assert state["last_rollback_reason"] == "timeout"
