"""Lightweight system stats for the dashboard (requirement 4.8.4.1.2.1 /
5.3.2.1). Uses psutil when available and degrades to None fields
otherwise, so the dashboard still renders on a dev machine without it."""
from __future__ import annotations

from typing import Optional

try:
    import psutil
except ImportError:  # pragma: no cover - exercised only when psutil is absent
    psutil = None


def cpu_percent() -> Optional[float]:
    if psutil is None:
        return None
    return psutil.cpu_percent(interval=None)


def memory_percent() -> Optional[float]:
    if psutil is None:
        return None
    return psutil.virtual_memory().percent
