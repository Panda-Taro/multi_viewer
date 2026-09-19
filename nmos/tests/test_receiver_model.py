import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from receiver_model import (
    NodeResourceSet,
    ConnectionResource,
    NmosModelError,
    derive_receiver_id,
    supported_is04_versions,
    supported_is05_versions,
    VIDEO_RECEIVER_COUNT,
    AUDIO_RECEIVER_COUNT,
)


def test_exactly_4_video_and_1_audio_receiver():
    rs = NodeResourceSet.build("seed-1")
    rs.validate_receiver_only()
    assert sum(1 for r in rs.receivers if r.kind == "video") == 4
    assert sum(1 for r in rs.receivers if r.kind == "audio") == 1
    assert len(rs.receivers) == 5


def test_no_sender_kind_ever_present():
    rs = NodeResourceSet.build("seed-1")
    assert all(r.kind in ("video", "audio") for r in rs.receivers)


def test_ids_stable_across_rebuild_with_same_seed():
    rs1 = NodeResourceSet.build("seed-42")
    rs2 = NodeResourceSet.build("seed-42")
    assert rs1.ids_are_stable(rs2)
    for r1, r2 in zip(rs1.receivers, rs2.receivers):
        assert r1.id == r2.id


def test_ids_differ_across_different_seeds():
    rs1 = NodeResourceSet.build("seed-a")
    rs2 = NodeResourceSet.build("seed-b")
    assert not rs1.ids_are_stable(rs2)


def test_derive_receiver_id_is_valid_uuid():
    import uuid

    rid = derive_receiver_id("seed-x", "video", 0)
    uuid.UUID(rid)  # raises if invalid


def test_is04_versions_cover_v1_1_to_v1_3():
    assert supported_is04_versions() == ["v1.1", "v1.2", "v1.3"]


def test_is05_versions_cover_v1_0_to_v1_1():
    assert supported_is05_versions() == ["v1.0", "v1.1"]


def test_validate_raises_when_video_count_wrong():
    rs = NodeResourceSet.build("seed-1")
    rs.receivers.pop()  # remove the audio receiver, leaving 4 video only... but let's break video count
    rs.receivers.pop()  # now 3 video receivers
    with pytest.raises(NmosModelError):
        rs.validate_receiver_only()


def test_connection_resource_activate_copies_staged_to_active():
    conn = ConnectionResource(receiver_id="r1")
    conn.patch_staged({"master_enable": True, "sender_id": "sender-123"})
    active = conn.activate()
    assert active["master_enable"] is True
    assert active["sender_id"] == "sender-123"
    assert conn.active == conn.staged


def test_connection_resource_rejects_unknown_activation_mode():
    conn = ConnectionResource(receiver_id="r1")
    with pytest.raises(NmosModelError):
        conn.activate(activation_mode="not_a_real_mode")


def test_default_counts_match_requirements():
    assert VIDEO_RECEIVER_COUNT == 4
    assert AUDIO_RECEIVER_COUNT == 1
