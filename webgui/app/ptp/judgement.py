"""Pure decision logic for PTP status: jitter computation, state
determination, and status-file staleness. Kept separate from monitor.py
(the polling loop, which calls pmc and has side effects) and
status_store.py (file I/O) so all of the actual "is this normal, syncing,
abnormal, ...?" logic can be unit tested without invoking pmc or touching
the filesystem.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

# Requirement 5-1-4: hardware-timestamping NICs are expected to sync to
# sub-microsecond accuracy; software timestamping is explicitly allowed to
# degrade to millisecond-order accuracy -- three orders of magnitude
# worse. A single fixed jitter threshold would either be permanently
# "異常" for software timestamping or never catch a real problem on
# hardware timestamping, so the threshold is chosen per mode. These are
# initial, defensible round-number values (1us / 1ms, exactly matching
# the "3桁以上違います" the requirement itself describes) pending
# real-hardware tuning -- see NOTES.md and the step 3a completion report
# for the reasoning and what to revisit once real offset/jitter figures
# are observed on the target hardware.
JITTER_THRESHOLD_NS = {
    "hardware": 1_000,  # 1 microsecond (population stdev of the offset window)
    "software": 1_000_000,  # 1 millisecond
}

# Below this many rolling-window samples, a jitter figure isn't considered
# statistically meaningful yet -- report "syncing" instead of judging it.
MIN_SAMPLES_FOR_JITTER = 10

# If the status file's last sample is older than this, the collector
# process itself is presumed stopped/dead -- report "unknown" rather than
# an increasingly-stale "normal"/"abnormal" verdict. 5x monitor.py's ~1s
# poll period: generous enough to absorb one or two slow/failed pmc calls
# without flapping to "unknown" and back.
STALE_THRESHOLD_SECONDS = 5.0

STATE_NORMAL = "normal"
STATE_SYNCING = "syncing"
STATE_GM_NOT_FOUND = "gm_not_found"
STATE_ABNORMAL = "abnormal"
STATE_UNKNOWN = "unknown"

# portState values (IEEE 1588 / linuxptp) that mean "no grandmaster
# actually locked yet" regardless of what gmPresent happens to report.
_NOT_YET_SYNCING_STATES = {"LISTENING", "INITIALIZING"}
# The transitional state between LISTENING and SLAVE, once a master has
# been selected but the clock servo hasn't calibrated yet.
_TRANSITIONAL_STATES = {"UNCALIBRATED"}


def compute_jitter_ns(samples: Sequence[int]) -> Optional[float]:
    """Population standard deviation of the rolling offset window, in
    nanoseconds. Population (not sample) stdev because the window is
    treated as the complete set of "recent" samples being judged, not a
    sample drawn from a larger population -- and it keeps a 2-sample
    window well-defined without a separate n=1 special case."""
    if len(samples) < 2:
        return None
    return statistics.pstdev(samples)


def determine_state(
    port_state: Optional[str],
    gm_present: bool,
    sample_count: int,
    jitter_ns: Optional[float],
    timestamping_mode: str,
) -> str:
    """Requirement 4.8.4.1.2.2's five-way classification:
    正常(normal) / 同期中(syncing) / GM未検出(gm_not_found) /
    異常(abnormal). "不明"(unknown) is NOT decided here -- it is a
    read-time staleness override (see is_stale()/effective_leg_view()
    below), since it depends on wall-clock time, not on any single
    sample."""
    if not gm_present or port_state is None or port_state in _NOT_YET_SYNCING_STATES:
        return STATE_GM_NOT_FOUND
    if port_state in _TRANSITIONAL_STATES:
        return STATE_SYNCING
    if port_state != "SLAVE":
        # FAULTY/DISABLED/PASSIVE/PRE_MASTER/MASTER -- none are a healthy
        # path for a clientOnly single-port client (MASTER in particular
        # would itself violate requirement 4.3.5, independently guarded
        # against at the ptp4l-config level -- surfaced here too rather
        # than mislabeled "syncing" or "normal").
        return STATE_ABNORMAL
    if sample_count < MIN_SAMPLES_FOR_JITTER or jitter_ns is None:
        return STATE_SYNCING
    threshold = JITTER_THRESHOLD_NS.get(timestamping_mode, JITTER_THRESHOLD_NS["software"])
    return STATE_NORMAL if jitter_ns <= threshold else STATE_ABNORMAL


def is_stale(last_sample_at: Optional[str], now: Optional[datetime] = None) -> bool:
    """True if `last_sample_at` (an ISO-8601 timestamp, or None/absent) is
    old enough that the collector process should be presumed stopped."""
    if not last_sample_at:
        return True
    try:
        sample_time = datetime.fromisoformat(last_sample_at)
    except ValueError:
        return True
    if sample_time.tzinfo is None:
        sample_time = sample_time.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - sample_time).total_seconds() > STALE_THRESHOLD_SECONDS


def _empty_leg_view() -> dict[str, Any]:
    return {
        "interface": None,
        "timestamping_mode": None,
        "port_state": None,
        "gm_present": False,
        "gm_id": None,
        "offset_ns": None,
        "jitter_ns": None,
        "sample_count": 0,
        "state": STATE_UNKNOWN,
        "last_sample_at": None,
    }


def effective_leg_view(leg_status: Optional[dict[str, Any]]) -> dict[str, Any]:
    """What the dashboard should actually display for one leg: the stored
    fields, with `state` downgraded to "unknown" if the leg has never
    reported at all, or its last sample is older than
    STALE_THRESHOLD_SECONDS -- so the dashboard never keeps showing a
    frozen "正常" after the collector process has died (the requirement's
    explicit "古い状態をそのまま「正常」と表示しないこと")."""
    if leg_status is None:
        return _empty_leg_view()
    view = dict(leg_status)
    if is_stale(leg_status.get("last_sample_at"), now=None):
        view["state"] = STATE_UNKNOWN
    return view
