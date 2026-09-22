"""Regression tests for the staged-cache staleness bug: connection_api.py's
in-memory `staged` cache, once seeded from config.json on first access,
used to keep serving that snapshot forever -- even after config.json was
changed by a manual WebGUI save (media.py). A later IS-05
`activate_immediate` PATCH that didn't itself re-specify `master_enable`
(a legitimate "just re-activate, nothing changed" re-sync -- the field is
simply absent from the PATCH body) would then silently overwrite the
manual change with the stale cached value.

The fix: media.py's manual-save endpoints now call
connection_api.invalidate_staged_for() after writing config.json, dropping
the cached staged entry so the next GET/PATCH re-seeds it from the value
just saved. These tests exercise both directions (manual disable
survives a stale re-activate, and manual enable survives a stale
re-deactivate) through the real HTTP routes, not by calling internals
directly, so they fail the same way an external NMOS controller +
WebGUI operator would trigger the bug.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def combined_client(isolated_dirs):
    from app import config_store
    from app.nmos import connection_api, identity as identity_module
    from app.routers import media

    connection_api.reset_staged_cache()
    identity = identity_module.load_identity()

    app = FastAPI()
    app.include_router(media.router)
    app.include_router(connection_api.router)
    client = TestClient(app)
    client.identity = identity
    client.video_id = identity["video_receiver_ids"][0]
    client.audio_id = identity["audio_receiver_ids"][0]
    client.config_store = config_store
    return client


def _activate_patch(enabled: bool) -> dict:
    """A full IS-05 activate PATCH, as a controller sends the first time
    it configures a receiver: explicit master_enable + transport_params."""
    return {
        "master_enable": enabled,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }


def _resync_patch() -> dict:
    """A minimal "just re-activate, nothing changed" PATCH -- exactly what
    a controller doing a periodic re-sync sends: no master_enable, no
    transport_params, relying entirely on whatever is already staged.
    This is the shape that exposed the bug."""
    return {"activation": {"mode": "activate_immediate"}}


def _manual_video_payload(enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "payload_id": 96,
        "video_format": "59.94i",
        "color_format": "YCbCr4:2:2_10bit_SDR",
        "amber": {"source_ip": "10.0.0.1", "group_ip": "239.9.9.1", "port": 6000},
        "blue": {"source_ip": "10.0.1.1", "group_ip": "239.9.9.2", "port": 6000},
    }


def test_manual_disable_survives_a_later_noop_nmos_reactivate(combined_client):
    video_path = f"/x-nmos/connection/v1.1/single/receivers/{combined_client.video_id}/staged/"

    # 1. NMOS activates the receiver (enabled=true).
    r1 = combined_client.patch(video_path, json=_activate_patch(True))
    assert r1.status_code == 200
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is True

    # 2. Operator manually disables it via the WebGUI.
    r2 = combined_client.put("/api/media/video/1", json=_manual_video_payload(False))
    assert r2.status_code == 200
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is False

    # 3. The NMOS controller re-sends a bare "re-activate" with no field
    #    changes (e.g. a periodic re-sync) -- it never said master_enable.
    r3 = combined_client.patch(video_path, json=_resync_patch())
    assert r3.status_code == 200

    # 4. The manual disable must still hold: config.json is the source of
    #    truth, and this PATCH never expressed an intent to re-enable it.
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is False


def test_manual_enable_survives_a_later_noop_nmos_reactivate(combined_client):
    """Reverse direction: NMOS deactivates, operator manually re-enables,
    NMOS re-sends the same (now stale) deactivate -- the manual enable
    must not be silently reverted."""
    video_path = f"/x-nmos/connection/v1.1/single/receivers/{combined_client.video_id}/staged/"

    # 1. NMOS deactivates (enabled=false).
    combined_client.patch(video_path, json=_activate_patch(False))
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is False

    # 2. Operator manually enables it via the WebGUI.
    combined_client.put("/api/media/video/1", json=_manual_video_payload(True))
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is True

    # 3. NMOS controller re-sends a bare "re-activate" (stale staged
    #    cache, if not invalidated, would still say master_enable=false).
    combined_client.patch(video_path, json=_resync_patch())

    # 4. The manual enable must still hold.
    assert combined_client.config_store.load_config()["receivers"]["video"][0]["enabled"] is True


def test_get_staged_reflects_manual_save_not_just_active(combined_client):
    """GET staged (not just active) must also reflect the manual save --
    proving the cache entry was actually dropped and re-seeded, rather
    than the config just happening to be overwritten again by coincidence."""
    video_path = f"/x-nmos/connection/v1.1/single/receivers/{combined_client.video_id}/staged/"

    combined_client.patch(video_path, json=_activate_patch(True))
    combined_client.put("/api/media/video/1", json=_manual_video_payload(False))

    staged = combined_client.get(video_path).json()
    assert staged["master_enable"] is False
    assert staged["transport_params"][0]["source_ip"] == "10.0.0.1"


def test_audio_receiver_manual_disable_survives_noop_reactivate(combined_client):
    """Same regression, audio side, to confirm the fix isn't video-only."""
    audio_path = f"/x-nmos/connection/v1.1/single/receivers/{combined_client.audio_id}/staged/"
    audio_payload = {
        "enabled": False,
        "payload_id": 97,
        "sampling": "48kHz",
        "packet_time": "1ms",
        "amber": {"source_ip": "10.0.0.5", "group_ip": "239.5.5.5", "port": 6100},
        "blue": {"source_ip": "10.0.1.5", "group_ip": "239.5.5.6", "port": 6100},
    }

    combined_client.patch(audio_path, json=_activate_patch(True))
    assert combined_client.config_store.load_config()["receivers"]["audio"][0]["enabled"] is True

    combined_client.put("/api/media/audio/1", json=audio_payload)
    assert combined_client.config_store.load_config()["receivers"]["audio"][0]["enabled"] is False

    combined_client.patch(audio_path, json=_resync_patch())
    assert combined_client.config_store.load_config()["receivers"]["audio"][0]["enabled"] is False


def test_invalidate_staged_for_unknown_index_is_a_noop(isolated_dirs):
    """A defensive check: an out-of-range index should not raise."""
    from app.nmos import connection_api

    connection_api.invalidate_staged_for("video", 99)  # must not raise


def test_nmos_then_manual_save_round_trip_video(combined_client):
    """Operator-confirmed expected behaviour, end to end:
    1. NMOS activates -> WebGUI shows "SDP" (video_format == "sdp").
    2. Operator manually fixes the format and presses Save (PUT) ->
       backend updates to that exact value and sdp_source flips back to
       "manual". Nothing changes in config.json before that PUT fires."""
    video_path = f"/x-nmos/connection/v1.1/single/receivers/{combined_client.video_id}/staged/"

    combined_client.patch(video_path, json=_activate_patch(True))
    receiver = combined_client.config_store.load_config()["receivers"]["video"][0]
    assert receiver["video_format"] == "sdp"
    assert receiver["sdp_source"] == "nmos"

    manual_payload = _manual_video_payload(True)
    manual_payload["video_format"] = "59.94p"
    combined_client.put("/api/media/video/1", json=manual_payload)

    receiver = combined_client.config_store.load_config()["receivers"]["video"][0]
    assert receiver["video_format"] == "59.94p"
    assert receiver["sdp_source"] == "manual"
