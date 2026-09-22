"""Worker functions for the cross-process config_store lock regression
test (test_config_store_cross_process_lock.py).

These must live in their own plain, importable module -- not inside the
test file itself -- because multiprocessing's 'spawn' start method (the
only one available on Windows, where this whole project is developed) has
to pickle a *reference* to the target function (module name + qualified
name) and re-import that module in the freshly started child process. A
function defined inside a test file, or a closure/lambda, either isn't
reliably importable by name in the child or isn't picklable at all.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_importable() -> None:
    """Put webgui/ on sys.path so `import app...` works in the child
    process, exactly like tests/conftest.py does for the main pytest
    process. multiprocessing's 'spawn' start method boots a fresh
    interpreter for the child; it does not reliably inherit whatever
    sys.path surgery pytest's collection did in the parent."""
    webgui_dir = str(Path(__file__).resolve().parent.parent)
    if webgui_dir not in sys.path:
        sys.path.insert(0, webgui_dir)


def hammer_ptp_domain(config_dir: str, iterations: int) -> None:
    """Repeatedly load-increment-save config.ptp.domain through the public
    locked_config() read-modify-write primitive, `iterations` times. If
    the whole read-modify-write is really serialized across processes (not
    just the final save), the field's value after this AND a concurrently
    running hammer_video_receiver() finish must be exactly `iterations`
    higher than when this started -- any lost update leaves it short."""
    _ensure_importable()
    os.environ["MULTIVIEWER_CONFIG_DIR"] = config_dir
    from app import config_store

    for _ in range(iterations):
        with config_store.locked_config() as config:
            config["ptp"]["domain"] += 1


def hammer_video_receiver(config_dir: str, iterations: int) -> None:
    """Same as hammer_ptp_domain(), but for a completely different config
    section (receivers.video[0]) -- the pairing this test needs to prove
    that two *different* processes updating two *different* parts of
    config.json don't stomp on each other's read-modify-write cycles."""
    _ensure_importable()
    os.environ["MULTIVIEWER_CONFIG_DIR"] = config_dir
    from app import config_store

    for _ in range(iterations):
        with config_store.locked_config() as config:
            receiver = config["receivers"]["video"][0]
            receiver["payload_id"] += 1
            receiver["enabled"] = not receiver["enabled"]
