import subprocess

from app.ptp import timestamping

ETHTOOL_HW_OUTPUT = """Time stamping parameters for eth0:
Capabilities:
\thardware-transmit
\tsoftware-transmit
\thardware-receive
\tsoftware-receive
\thardware-raw-clock
PTP Hardware Clock: 0
Hardware Transmit Timestamp Modes:
\toff
\ton
Hardware Receive Filter Modes:
\tnone
\tall
"""

# The actual capability-flag names ethtool -T prints (distinct from the
# human-readable "hardware-transmit" lines above, which some driver
# versions print instead of / in addition to the SOF_TIMESTAMPING_* flag
# names this module actually checks for).
ETHTOOL_HW_OUTPUT_WITH_FLAGS = ETHTOOL_HW_OUTPUT + (
    "SOF_TIMESTAMPING_TX_HARDWARE\nSOF_TIMESTAMPING_RX_HARDWARE\nSOF_TIMESTAMPING_RAW_HARDWARE\n"
)

ETHTOOL_SW_ONLY_OUTPUT = """Time stamping parameters for eth1:
Capabilities:
\tsoftware-transmit
\tsoftware-receive
\tsoftware-system-clock
SOF_TIMESTAMPING_TX_SOFTWARE
SOF_TIMESTAMPING_RX_SOFTWARE
SOF_TIMESTAMPING_SOFTWARE
PTP Hardware Clock: none
"""


class _FakeResult:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_detect_timestamping_mode_hardware_when_flags_present(monkeypatch):
    monkeypatch.setattr(timestamping.shutil, "which", lambda name: "/usr/sbin/ethtool")
    monkeypatch.setattr(
        timestamping.subprocess, "run", lambda *a, **k: _FakeResult(ETHTOOL_HW_OUTPUT_WITH_FLAGS)
    )
    assert timestamping.detect_timestamping_mode("eth0") == timestamping.TIMESTAMPING_HARDWARE


def test_detect_timestamping_mode_software_when_flags_absent(monkeypatch):
    monkeypatch.setattr(timestamping.shutil, "which", lambda name: "/usr/sbin/ethtool")
    monkeypatch.setattr(timestamping.subprocess, "run", lambda *a, **k: _FakeResult(ETHTOOL_SW_ONLY_OUTPUT))
    assert timestamping.detect_timestamping_mode("eth1") == timestamping.TIMESTAMPING_SOFTWARE


def test_detect_timestamping_mode_software_when_ethtool_missing(monkeypatch):
    monkeypatch.setattr(timestamping.shutil, "which", lambda name: None)
    assert timestamping.detect_timestamping_mode("eth0") == timestamping.TIMESTAMPING_SOFTWARE


def test_detect_timestamping_mode_software_when_ethtool_fails(monkeypatch):
    monkeypatch.setattr(timestamping.shutil, "which", lambda name: "/usr/sbin/ethtool")
    monkeypatch.setattr(timestamping.subprocess, "run", lambda *a, **k: _FakeResult("", returncode=1))
    assert timestamping.detect_timestamping_mode("eth0") == timestamping.TIMESTAMPING_SOFTWARE


def test_detect_timestamping_mode_software_on_subprocess_error(monkeypatch):
    monkeypatch.setattr(timestamping.shutil, "which", lambda name: "/usr/sbin/ethtool")

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ethtool", timeout=5)

    monkeypatch.setattr(timestamping.subprocess, "run", _raise)
    assert timestamping.detect_timestamping_mode("eth0") == timestamping.TIMESTAMPING_SOFTWARE
