"""Entrypoint for multiviewer-ptp.service (step 3a).

Generates the ptp4l config from config.json, launches ptp4l as a
subprocess, and runs the PTP status monitor loop (app/ptp/monitor.py)
alongside it for as long as ptp4l stays up. If ptp4l exits, this process
exits too, so systemd's Restart=on-failure relaunches the whole thing
(fresh config generation included) rather than leaving a monitor loop
polling a dead ptp4l.

Single systemd unit for both ptp4l and the monitor loop is a deliberate
choice, not a shortcut: requirement 4.3.3/4.3.4's BMCA-driven Amber/Blue
failover (step 3b) is handled by ONE ptp4l process with two [iface]
sections in its config, not two separate ptp4l processes -- BMCA
operates across a single daemon's own ports, not between independent
daemons. Keeping the Python side that generates that config and watches
its status in the same unit avoids ever having two independently
restarting units whose config/process could drift out of sync.

Stage 1 of step 3a (per the implementation request): this only ever
*reads* PTP state via pmc. phc2sys, which would actually step/slew the OS
system clock, is intentionally not started here -- that is step 3a stage
2, gated on an explicit real-hardware confirmation step.

Run as: python -m app.ptp_main   (see systemd/multiviewer-ptp.service)
"""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from pathlib import Path
from types import FrameType
from typing import Optional

from . import config_store, log_store
from .ptp import config_gen, monitor, timestamping

PTP4L_CONF_PATH = Path(config_store.CONFIG_DIR) / "ptp4l.conf"
UDS_ADDRESS = str(Path(config_store.CONFIG_DIR) / "ptp4l.sock")

_stop_requested = False


def _handle_sigterm(signum: int, frame: Optional[FrameType]) -> None:
    global _stop_requested
    _stop_requested = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_sigterm)

    config = config_store.load_config()
    domain = config["ptp"]["domain"]
    interface = config["network"]["media_amber"]["interface"]

    if not interface:
        # Same graceful-degradation pattern as nmos_main.py's "port not
        # configured" case: log, exit non-zero, let systemd's
        # Restart=on-failure retry harmlessly until the operator sets an
        # interface from the WebGUI (requirement note 5 in the request:
        # ptp4l needs an IP-bearing interface for IPv4 multicast, so an
        # unset interface must not crash-loop noisily or hang).
        message = (
            "メディアNIC(Amber)のインターフェースが未設定です (network.media_amber.interface)。"
            "WebGUIの「システム設定」画面でインターフェースを設定してから、"
            "multiviewer-ptp.service を再起動してください。"
        )
        log_store.log_event("ptp", "error", message)
        print(message, file=sys.stderr)
        return 1

    if shutil.which("ptp4l") is None:
        message = "ptp4lコマンドが見つかりません。linuxptpパッケージがインストールされているか確認してください。"
        log_store.log_event("ptp", "error", message)
        print(message, file=sys.stderr)
        return 1

    mode = timestamping.detect_timestamping_mode(interface)
    log_store.log_event("ptp", "info", f"PTPタイムスタンプモード: {mode}", interface=interface, domain=domain)

    try:
        config_gen.write_ptp4l_config(
            PTP4L_CONF_PATH,
            interface=interface,
            domain=domain,
            timestamping_mode=mode,
            uds_address=UDS_ADDRESS,
        )
    except (OSError, RuntimeError) as exc:
        message = f"ptp4l設定ファイルの生成に失敗しました: {exc}"
        log_store.log_event("ptp", "error", message)
        print(message, file=sys.stderr)
        return 1

    # Final defense-in-depth check (requirement 4.3.5): re-read the file
    # we just wrote and refuse to launch ptp4l at all if it is somehow
    # missing `clientOnly 1`. This system must never risk starting as a
    # PTP master.
    written_text = PTP4L_CONF_PATH.read_text(encoding="utf-8")
    if not config_gen.validate_client_only(written_text):
        message = "重大: 生成されたptp4l設定にclientOnly 1が含まれていません。起動を中止します。"
        log_store.log_event("ptp", "critical", message)
        print(message, file=sys.stderr)
        return 1

    log_store.log_event(
        "ptp", "info", "ptp4lを起動します", interface=interface, domain=domain, config=str(PTP4L_CONF_PATH)
    )
    # -m: also log to stdout, which -- since we don't redirect it -- flows
    # into this unit's own journal stream alongside our own log_store
    # events, useful for debugging without hunting through syslog's
    # separate "ptp4l" identifier.
    process = subprocess.Popen(["ptp4l", "-f", str(PTP4L_CONF_PATH), "-m"])

    leg_monitor = monitor.LegMonitor(
        "amber", interface=interface, timestamping_mode=mode, uds_address=UDS_ADDRESS
    )

    def should_continue() -> bool:
        if _stop_requested:
            return False
        return process.poll() is None

    try:
        monitor.run_forever([leg_monitor], domain=domain, should_continue=should_continue)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    exit_code = process.returncode
    if exit_code not in (0, None) and not _stop_requested:
        log_store.log_event("ptp", "error", f"ptp4lが予期せず終了しました (exit code {exit_code})")
    return exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
