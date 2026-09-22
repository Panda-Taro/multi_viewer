"""Persistent configuration store for MultiViewer.

Step 1 only writes/reads settings here; later steps (NMOS, PTP, MTL,
compositor) read the same file to learn what the operator configured.
Storage is a single JSON file, written atomically (write to temp file +
os.replace) so a crash never leaves a half-written config behind.

Cross-process safety (step 2i): config.json is written by two independent
systemd services -- multiviewer-webgui.service and multiviewer-nmos.service
-- and step 4 is expected to add a third writer (the MTL bridge). Each does
its own read-modify-write: load the config, change one part of it, save the
whole thing back. A plain `threading.Lock` only serializes this within a
single process; it does nothing to stop two *processes* from interleaving
their read-modify-write cycles, which loses whichever side wrote first (a
classic lost-update race -- concretely: WebGUI loads config to save a PTP
domain change; before it writes, the NMOS process loads the same config,
applies an IS-05 activate, and saves; WebGUI then saves its own
now-stale copy, silently reverting the activate). This is the same class of
bug step 2d fixed for the in-memory `staged` cache, but at the file level.

All read-modify-write access MUST go through `locked_config()` below, which
uses a real cross-process file lock (the `filelock` package -- POSIX flock
under the hood on Linux) on a *dedicated* lock file, never on config.json
itself: `save_config()`'s atomic `os.replace()` swaps config.json's inode,
which would silently invalidate an flock held against the old inode if we
locked that file directly. `load_config()` also takes the same lock (briefly)
so a read never lands mid-write and sees a half-applied file; the code does
not distinguish shared/exclusive locking (filelock's `FileLock` is exclusive
-only) -- reads blocking other reads is a non-issue at this system's very low
config read/write frequency, and it keeps the locking logic in one simple
class rather than two.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator

from filelock import FileLock, Timeout

from . import log_store

CONFIG_DIR = Path(os.environ.get("MULTIVIEWER_CONFIG_DIR", "/etc/multiviewer"))
CONFIG_PATH = CONFIG_DIR / "config.json"
LOCK_PATH = CONFIG_DIR / "config.lock"

# How long to wait for the cross-process lock before giving up. Generous
# relative to how long a config write actually takes (milliseconds), but
# short enough that a stuck/dead lock holder doesn't hang a caller (in
# particular registration_client.py's async loop -- see its own comments
# on why its config_store calls are wrapped in asyncio.to_thread()) for
# an unreasonable amount of time.
LOCK_TIMEOUT_SECONDS = 5.0

_DEFAULT_ENDPOINT = {"source_ip": "", "group_ip": "", "port": 0}

_DEFAULT_VIDEO_RECEIVER = {
    "enabled": False,
    "payload_id": 96,
    # "59.94i" | "59.94p" -- always a concrete value, never a literal "sdp"
    # placeholder (removed per operator request: the field must always show
    # a real value, updated live from the SDP's actual scan type when
    # NMOS-driven -- see nmos/connection_api.py's _resolve_video_format()
    # and NOTES.md "video_format等のSDP選択肢廃止").
    "video_format": "59.94i",
    "color_format": "YCbCr4:2:2_10bit_SDR",
    "amber": dict(_DEFAULT_ENDPOINT),
    "blue": dict(_DEFAULT_ENDPOINT),
    "sdp_source": "manual",  # "manual" | "nmos"
    "nmos_sdp": None,
    # The IS-05 sender_id the controller last staged for this receiver
    # (None if never set, or if manually cleared). Persisted so the IS-04
    # Receiver resource's `subscription.sender_id` -- and the IS-05
    # `active.sender_id` -- reflect what this receiver is actually
    # subscribed to, instead of a hardcoded placeholder. See
    # nmos/resources.py's _receiver_common() and NOTES.md "subscription
    # の動的化・RDSへの再登録".
    "sender_id": None,
}

_DEFAULT_AUDIO_RECEIVER = {
    "enabled": False,
    "payload_id": 97,
    "sampling": "48kHz",  # the only rate this system supports; always concrete
    "packet_time": "1ms",  # "1ms" | "0.125ms" -- always concrete, see above
    "amber": dict(_DEFAULT_ENDPOINT),
    "blue": dict(_DEFAULT_ENDPOINT),
    "sdp_source": "manual",
    "nmos_sdp": None,
    "sender_id": None,
}

_DEFAULT_NIC = {"interface": "", "mode": "static", "address": "", "prefix": 24, "gateway": ""}

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "receivers": {
        "video": [dict(_DEFAULT_VIDEO_RECEIVER) for _ in range(4)],
        "audio": [dict(_DEFAULT_AUDIO_RECEIVER) for _ in range(1)],
    },
    "ptp": {
        "domain": 0,
    },
    "nmos": {
        "rds_discovery": "static",  # "static" | "auto"
        "rds_static": {"address": "", "port": 0, "api_version": "v1.3"},
        "common_port": 8080,  # channelmapping/connection/events/node
        "source_port_mode": "auto",  # "auto" | "manual"
        "source_port": None,
    },
    # Stable IS-04 resource identifiers. Generated once (uuid4) on first use
    # by webgui/app/nmos/identity.py and persisted here so the Node keeps
    # the same identity across restarts -- re-registering with a different
    # Node ID each time would create duplicate Nodes in the RDS instead of
    # updating the existing one.
    "identity": {
        "node_id": None,
        "device_id": None,
        "video_receiver_ids": [None, None, None, None],
        "audio_receiver_ids": [None],
    },
    "network": {
        "media_amber": dict(_DEFAULT_NIC),
        "media_blue": dict(_DEFAULT_NIC),
        "control": dict(_DEFAULT_NIC),
    },
    "streaming": {
        "bitrate_mbps": 20,
        "url_path": "/monitor01/",
    },
    "display": {
        "mode": "quad",  # "quad" | "single"
        "single_source": 1,
    },
}


def _ensure_lock_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# A single FileLock instance, reused across every call in this process.
# filelock's FileLock is thread-safe and supports reentrant acquisition by
# the same thread (nesting `with _file_lock:` doesn't deadlock); the
# underlying OS-level lock (flock on Linux) is what actually provides
# cross-*process* mutual exclusion. Constructing it here does not touch
# the filesystem yet (the lock file is created lazily on first acquire),
# so it is safe even before CONFIG_DIR exists.
_file_lock = FileLock(str(LOCK_PATH), timeout=LOCK_TIMEOUT_SECONDS)


@contextlib.contextmanager
def _acquired_lock() -> Iterator[None]:
    _ensure_lock_dir()
    try:
        with _file_lock:
            yield
    except Timeout as exc:
        # Timeout is a subclass of TimeoutError, itself a subclass of
        # OSError -- every existing `except OSError` around a config_store
        # write call already catches this the same way it catches a save
        # failure, so no caller-side changes were needed for this alone.
        log_store.log_event(
            "config_store",
            "error",
            f"設定ファイルのロック取得がタイムアウトしました({LOCK_TIMEOUT_SECONDS}秒): {exc}",
        )
        raise


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge overlay into base, keeping base's keys when overlay is missing them.

    Guards against older config files on disk missing keys that newer code
    added (e.g. after a schema addition in a later step).
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_unlocked() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, on_disk)


def _write_unlocked(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, CONFIG_PATH)


def load_config() -> dict[str, Any]:
    """Read-only load. Takes the cross-process lock briefly so a read never
    lands on a config.json that another process is mid-write on."""
    with _acquired_lock():
        return _read_unlocked()


def save_config(config: dict[str, Any]) -> None:
    """Atomically persist the given config dict to disk.

    Only safe to use on its own when the caller did not itself derive
    `config` from a `load_config()` call it needs to stay consistent with
    (e.g. writing a value that was fully computed beforehand). Any
    load-then-modify-then-save sequence must use `locked_config()` instead,
    so the whole read-modify-write is one atomic unit from other
    processes' point of view -- see the module docstring.
    """
    with _acquired_lock():
        _write_unlocked(config)


@contextlib.contextmanager
def locked_config() -> Iterator[dict[str, Any]]:
    """The read-modify-write primitive every caller that changes config.json
    must use:

        with config_store.locked_config() as config:
            config["ptp"]["domain"] = 1

    Holds the cross-process lock for the entire duration of the `with`
    block, so no other process's own load-modify-save cycle can interleave
    with this one. The config is written back automatically when the block
    exits normally; if the block raises, nothing is written (the file is
    left exactly as it was).
    """
    with _acquired_lock():
        config = _read_unlocked()
        yield config
        _write_unlocked(config)


def update_section(section: str, value: Any) -> dict[str, Any]:
    """Replace one top-level section (e.g. "ptp", "network") and save."""
    if section not in DEFAULT_CONFIG:
        raise KeyError(f"unknown config section: {section}")
    with locked_config() as config:
        config[section] = value
    return config


@contextlib.contextmanager
def locked_config_optional_write() -> Iterator[tuple[dict[str, Any], Callable[[], None]]]:
    """Like `locked_config()`, but does not write back automatically --
    the caller gets a `save()` callback and only calls it if it actually
    changed something.

    Written for identity.py's `ensure_identity()`/`load_identity()`: those
    are called on essentially every IS-05 request and registration cycle,
    but only ever need to write on first run (when UUIDs are generated) --
    every later call is a pure read that finds nothing to fill in.
    `locked_config()`'s unconditional write would turn every one of those
    reads into a full atomic rewrite of config.json, needlessly increasing
    disk I/O and cross-process lock contention. This variant still holds
    the lock for the whole read-plus-maybe-write, so it closes the same
    race window `locked_config()` does; it just leaves the "was anything
    actually changed" decision to the caller instead of assuming yes.
    """
    with _acquired_lock():
        config = _read_unlocked()

        def save() -> None:
            _write_unlocked(config)

        yield config, save
