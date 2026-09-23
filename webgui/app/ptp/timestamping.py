"""Hardware vs software PTP timestamping detection (requirement 5-1-4, 7-1-1).

Uses `ethtool -T <interface>` to check whether the NIC driver reports
hardware timestamping support; falls back to software timestamping when
ethtool is unavailable (e.g. the Windows dev machine this project is
edited on) or the NIC doesn't support it -- the same
degrade-gracefully-on-non-Linux pattern nic_state.py already uses.
"""
from __future__ import annotations

import shutil
import subprocess

from .config_gen import TIMESTAMPING_HARDWARE, TIMESTAMPING_SOFTWARE

# `ethtool -T <iface>` prints a "Capabilities:" block listing
# SOF_TIMESTAMPING_* flags supported by the driver/hardware. Hardware
# timestamping (what ptp4l's time_stamping=hardware mode needs) requires
# both TX and RX hardware timestamping support.
_HW_TX_FLAG = "SOF_TIMESTAMPING_TX_HARDWARE"
_HW_RX_FLAG = "SOF_TIMESTAMPING_RX_HARDWARE"

_TIMEOUT_SECONDS = 5


def detect_timestamping_mode(interface: str) -> str:
    if shutil.which("ethtool") is None:
        return TIMESTAMPING_SOFTWARE
    try:
        result = subprocess.run(
            ["ethtool", "-T", interface],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return TIMESTAMPING_SOFTWARE
    if result.returncode != 0:
        return TIMESTAMPING_SOFTWARE
    output = result.stdout
    if _HW_TX_FLAG in output and _HW_RX_FLAG in output:
        return TIMESTAMPING_HARDWARE
    return TIMESTAMPING_SOFTWARE
