"""Stable IS-04 resource identifiers.

An NMOS Node must keep the same `id` across restarts -- registering with a
freshly generated UUID every time would make the RDS treat each restart as
a brand new Node (and orphan the old one until it expires), instead of
updating the existing registration. IDs are generated once with uuid4 and
persisted in config.json's "identity" section (see config_store.py).
"""
from __future__ import annotations

import uuid

from .. import config_store

RECEIVER_COUNT = {"video": 4, "audio": 1}


def ensure_identity(config: dict) -> dict:
    """Fill in any missing identity UUIDs and persist them. Returns the
    (possibly updated) config. Idempotent: a config that already has every
    ID is returned unchanged and not re-saved."""
    identity = config["identity"]
    changed = False

    if not identity.get("node_id"):
        identity["node_id"] = str(uuid.uuid4())
        changed = True
    if not identity.get("device_id"):
        identity["device_id"] = str(uuid.uuid4())
        changed = True

    video_ids = identity.get("video_receiver_ids") or [None] * RECEIVER_COUNT["video"]
    if len(video_ids) != RECEIVER_COUNT["video"]:
        video_ids = (video_ids + [None] * RECEIVER_COUNT["video"])[: RECEIVER_COUNT["video"]]
    for i, rid in enumerate(video_ids):
        if not rid:
            video_ids[i] = str(uuid.uuid4())
            changed = True
    identity["video_receiver_ids"] = video_ids

    audio_ids = identity.get("audio_receiver_ids") or [None] * RECEIVER_COUNT["audio"]
    if len(audio_ids) != RECEIVER_COUNT["audio"]:
        audio_ids = (audio_ids + [None] * RECEIVER_COUNT["audio"])[: RECEIVER_COUNT["audio"]]
    for i, rid in enumerate(audio_ids):
        if not rid:
            audio_ids[i] = str(uuid.uuid4())
            changed = True
    identity["audio_receiver_ids"] = audio_ids

    config["identity"] = identity
    if changed:
        config_store.save_config(config)
    return config


def load_identity() -> dict:
    """Convenience: load config, ensure identity, return just the identity
    section (with node_id/device_id/video_receiver_ids/audio_receiver_ids
    all guaranteed non-null)."""
    config = config_store.load_config()
    config = ensure_identity(config)
    return config["identity"]


def receiver_lookup(identity: dict) -> dict[str, tuple[str, int]]:
    """Map receiver UUID -> ("video"|"audio", 0-based index)."""
    lookup: dict[str, tuple[str, int]] = {}
    for idx, rid in enumerate(identity["video_receiver_ids"]):
        lookup[rid] = ("video", idx)
    for idx, rid in enumerate(identity["audio_receiver_ids"]):
        lookup[rid] = ("audio", idx)
    return lookup
