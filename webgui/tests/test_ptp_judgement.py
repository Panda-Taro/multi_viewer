from datetime import datetime, timedelta, timezone

from app.ptp import judgement


def test_compute_jitter_ns_needs_at_least_two_samples():
    assert judgement.compute_jitter_ns([]) is None
    assert judgement.compute_jitter_ns([100]) is None
    assert judgement.compute_jitter_ns([100, 100]) == 0.0


def test_compute_jitter_ns_matches_population_stdev():
    samples = [0, 1000, -1000, 500, -500]
    import statistics

    assert judgement.compute_jitter_ns(samples) == statistics.pstdev(samples)


def test_determine_state_gm_not_found_when_listening():
    state = judgement.determine_state(
        port_state="LISTENING", gm_present=False, sample_count=0, jitter_ns=None, timestamping_mode="hardware"
    )
    assert state == judgement.STATE_GM_NOT_FOUND


def test_determine_state_gm_not_found_when_gm_present_false_even_if_slave():
    """gmPresent is authoritative -- a stale SLAVE port_state reading
    without a currently-present GM must not be reported as synced."""
    state = judgement.determine_state(
        port_state="SLAVE", gm_present=False, sample_count=50, jitter_ns=10.0, timestamping_mode="hardware"
    )
    assert state == judgement.STATE_GM_NOT_FOUND


def test_determine_state_syncing_when_uncalibrated():
    state = judgement.determine_state(
        port_state="UNCALIBRATED", gm_present=True, sample_count=0, jitter_ns=None, timestamping_mode="hardware"
    )
    assert state == judgement.STATE_SYNCING


def test_determine_state_syncing_when_slave_but_not_enough_samples():
    state = judgement.determine_state(
        port_state="SLAVE",
        gm_present=True,
        sample_count=judgement.MIN_SAMPLES_FOR_JITTER - 1,
        jitter_ns=0.0,
        timestamping_mode="hardware",
    )
    assert state == judgement.STATE_SYNCING


def test_determine_state_normal_when_slave_and_jitter_within_hardware_threshold():
    state = judgement.determine_state(
        port_state="SLAVE",
        gm_present=True,
        sample_count=judgement.MIN_SAMPLES_FOR_JITTER,
        jitter_ns=judgement.JITTER_THRESHOLD_NS["hardware"] - 1,
        timestamping_mode="hardware",
    )
    assert state == judgement.STATE_NORMAL


def test_determine_state_abnormal_when_slave_and_jitter_exceeds_hardware_threshold():
    state = judgement.determine_state(
        port_state="SLAVE",
        gm_present=True,
        sample_count=judgement.MIN_SAMPLES_FOR_JITTER,
        jitter_ns=judgement.JITTER_THRESHOLD_NS["hardware"] + 1,
        timestamping_mode="hardware",
    )
    assert state == judgement.STATE_ABNORMAL


def test_determine_state_thresholds_differ_by_three_orders_of_magnitude_between_modes():
    """Requirement 5-1-4: software timestamping's expected precision is
    milliseconds vs hardware's microseconds -- a jitter value that is
    "abnormal" on hardware timestamping must be "normal" on software
    timestamping, or software-timestamped deployments would be
    permanently stuck showing 異常."""
    jitter = judgement.JITTER_THRESHOLD_NS["hardware"] * 10  # well above HW threshold

    hw_state = judgement.determine_state(
        port_state="SLAVE",
        gm_present=True,
        sample_count=judgement.MIN_SAMPLES_FOR_JITTER,
        jitter_ns=jitter,
        timestamping_mode="hardware",
    )
    sw_state = judgement.determine_state(
        port_state="SLAVE",
        gm_present=True,
        sample_count=judgement.MIN_SAMPLES_FOR_JITTER,
        jitter_ns=jitter,
        timestamping_mode="software",
    )
    assert hw_state == judgement.STATE_ABNORMAL
    assert sw_state == judgement.STATE_NORMAL


def test_determine_state_abnormal_for_unexpected_port_state():
    state = judgement.determine_state(
        port_state="FAULTY", gm_present=True, sample_count=50, jitter_ns=0.0, timestamping_mode="hardware"
    )
    assert state == judgement.STATE_ABNORMAL


def test_is_stale_true_when_missing():
    assert judgement.is_stale(None) is True
    assert judgement.is_stale("") is True


def test_is_stale_false_when_recent():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent = (now - timedelta(seconds=1)).isoformat()
    assert judgement.is_stale(recent, now=now) is False


def test_is_stale_true_when_old():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = (now - timedelta(seconds=judgement.STALE_THRESHOLD_SECONDS + 1)).isoformat()
    assert judgement.is_stale(old, now=now) is True


def test_effective_leg_view_returns_unknown_for_missing_leg():
    view = judgement.effective_leg_view(None)
    assert view["state"] == judgement.STATE_UNKNOWN


def test_effective_leg_view_downgrades_stale_normal_to_unknown():
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=judgement.STALE_THRESHOLD_SECONDS + 10)).isoformat()
    leg_status = {
        "interface": "eth0",
        "timestamping_mode": "hardware",
        "port_state": "SLAVE",
        "gm_present": True,
        "gm_id": "00b058.feef.0b448a",
        "offset_ns": 10,
        "jitter_ns": 5.0,
        "sample_count": 60,
        "state": judgement.STATE_NORMAL,
        "last_sample_at": stale_time,
    }
    view = judgement.effective_leg_view(leg_status)
    assert view["state"] == judgement.STATE_UNKNOWN
    # Everything else about the last known sample is still visible.
    assert view["gm_id"] == "00b058.feef.0b448a"


def test_effective_leg_view_keeps_fresh_state_as_is():
    leg_status = {
        "interface": "eth0",
        "timestamping_mode": "hardware",
        "port_state": "SLAVE",
        "gm_present": True,
        "gm_id": "00b058.feef.0b448a",
        "offset_ns": 10,
        "jitter_ns": 5.0,
        "sample_count": 60,
        "state": judgement.STATE_NORMAL,
        "last_sample_at": datetime.now(timezone.utc).isoformat(),
    }
    view = judgement.effective_leg_view(leg_status)
    assert view["state"] == judgement.STATE_NORMAL
