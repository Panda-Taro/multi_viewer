"""Step 2i regression test: config.json must survive concurrent
read-modify-write from two independent OS *processes* without losing
either side's changes.

Deliberately uses `multiprocessing`, not `threading`: two threads in one
process would already be serialized by config_store's old
`threading.Lock()`, so a threading-based version of this test would pass
on the pre-fix code too and never actually catch the bug this step fixes
(two separate systemd services -- multiviewer-webgui.service and
multiviewer-nmos.service -- doing their own load-modify-save cycles with
no shared in-process lock at all). See config_store.py's module docstring
for the full lost-update scenario this closes.
"""
from __future__ import annotations

import importlib
import multiprocessing

from config_store_mp_worker import hammer_ptp_domain, hammer_video_receiver

ITERATIONS = 300


def _init_config_dir(tmp_path, monkeypatch) -> str:
    config_dir = tmp_path / "etc-multiviewer"
    config_dir.mkdir()
    monkeypatch.setenv("MULTIVIEWER_CONFIG_DIR", str(config_dir))

    from app import config_store

    importlib.reload(config_store)
    # Snapshot the defaults to disk so both workers start from known
    # values (ptp.domain=127, video[0].payload_id=96, video[0].enabled=False)
    # and the expected final values below are exact, not "whatever the
    # default happened to be".
    config_store.save_config(config_store.load_config())
    return str(config_dir)


def test_concurrent_processes_do_not_lose_updates_to_different_sections(tmp_path, monkeypatch):
    config_dir = _init_config_dir(tmp_path, monkeypatch)

    from app import config_store

    starting_domain = config_store.load_config()["ptp"]["domain"]

    proc_ptp = multiprocessing.Process(target=hammer_ptp_domain, args=(config_dir, ITERATIONS))
    proc_video = multiprocessing.Process(target=hammer_video_receiver, args=(config_dir, ITERATIONS))
    proc_ptp.start()
    proc_video.start()
    proc_ptp.join(timeout=120)
    proc_video.join(timeout=120)

    assert proc_ptp.exitcode == 0, "hammer_ptp_domain worker process crashed"
    assert proc_video.exitcode == 0, "hammer_video_receiver worker process crashed"

    importlib.reload(config_store)
    final = config_store.load_config()

    # Every one of the 300 increments from the OTHER process's concurrent
    # read-modify-write cycles must still be reflected here -- a lost
    # update would leave this short of starting_domain + ITERATIONS.
    assert final["ptp"]["domain"] == starting_domain + ITERATIONS

    receiver = final["receivers"]["video"][0]
    assert receiver["payload_id"] == 96 + ITERATIONS
    assert receiver["enabled"] == (ITERATIONS % 2 == 1)
