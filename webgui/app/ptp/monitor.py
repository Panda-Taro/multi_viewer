"""PTP status polling loop (step 3a). Every ~1s, queries the locally
running ptp4l instance via pmc, maintains a rolling window of offset
samples per leg, computes jitter, judges the leg's state, and writes the
result to ptp-status.json (status_store.py) for the WebGUI dashboard to
read.

Runs inside app/ptp_main.py alongside (not instead of) the ptp4l
subprocess it polls -- see that module's docstring for why both live in
one systemd unit. This module only ever *reads* PTP state; it never
touches the OS system clock (that is phc2sys's job, stage 2 of step 3a,
intentionally not started yet).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, List, Optional

from .. import log_store
from . import judgement, pmc_client, status_store

POLL_INTERVAL_SECONDS = 1.0
WINDOW_SIZE = 60


class LegMonitor:
    """Tracks one leg's rolling offset window and reports state
    transitions to the event log, so requirement 5-3-1's "ロック状態の
    変化等、主要イベントをログに記録する" covers per-sample lock-state
    changes, not just the (step 3b) Amber/Blue systemwide switchover."""

    def __init__(self, leg: str, interface: str, timestamping_mode: str, uds_address: str) -> None:
        self.leg = leg
        self.interface = interface
        self.timestamping_mode = timestamping_mode
        self.uds_address = uds_address
        self._window: Deque[int] = deque(maxlen=WINDOW_SIZE)
        self._last_state: Optional[str] = None
        self._last_poll_failed = False

    def poll_once(self, domain: int) -> None:
        time_status = pmc_client.get_time_status(self.uds_address)
        port_state = pmc_client.get_port_state(self.uds_address)
        if time_status is None or port_state is None:
            if not self._last_poll_failed:
                log_store.log_event(
                    "ptp",
                    "warning",
                    f"{self.leg}系統のPTP状態取得に失敗しました（pmc応答なし）",
                    interface=self.interface,
                )
                self._last_poll_failed = True
            return
        self._last_poll_failed = False

        offset = time_status["master_offset_ns"]
        if port_state == "SLAVE" and offset is not None:
            self._window.append(offset)
        elif port_state != "SLAVE":
            # A pre-lock offset figure (LISTENING/UNCALIBRATED) isn't a
            # meaningful "locked" sample -- clear the window so a stale
            # pre-reacquisition jitter figure isn't reported as current
            # once the port re-locks.
            self._window.clear()

        jitter = judgement.compute_jitter_ns(list(self._window))
        state = judgement.determine_state(
            port_state=port_state,
            gm_present=time_status["gm_present"],
            sample_count=len(self._window),
            jitter_ns=jitter,
            timestamping_mode=self.timestamping_mode,
        )

        status_store.write_leg_status(
            self.leg,
            domain=domain,
            interface=self.interface,
            timestamping_mode=self.timestamping_mode,
            port_state=port_state,
            gm_present=time_status["gm_present"],
            gm_id=time_status["gm_id"],
            offset_ns=offset,
            jitter_ns=jitter,
            sample_count=len(self._window),
            state=state,
        )

        if state != self._last_state:
            log_store.log_event(
                "ptp",
                "info",
                f"{self.leg}系統のPTP状態が変化しました: {self._last_state} -> {state}",
                interface=self.interface,
                port_state=port_state,
                gm_id=time_status["gm_id"],
            )
            self._last_state = state


def run_forever(
    monitors: List[LegMonitor],
    domain: int,
    should_continue: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Polls every monitor once per POLL_INTERVAL_SECONDS until
    should_continue() returns False (ptp_main.py checks this against the
    supervised ptp4l subprocess's liveness plus a SIGTERM flag)."""
    while should_continue():
        for mon in monitors:
            mon.poll_once(domain)
        sleep(POLL_INTERVAL_SECONDS)
