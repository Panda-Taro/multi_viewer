import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def nmos_client(isolated_dirs):
    from app import config_store
    from app.nmos import connection_api, identity as identity_module

    connection_api.reset_staged_cache()
    identity = identity_module.load_identity()

    app = FastAPI()
    app.include_router(connection_api.router)
    client = TestClient(app)
    client.identity = identity
    client.video_id = identity["video_receiver_ids"][0]
    client.audio_id = identity["audio_receiver_ids"][0]
    client.config_store = config_store
    return client


def test_connection_index_lists_supported_versions(nmos_client):
    response = nmos_client.get("/x-nmos/connection/")
    assert response.status_code == 200
    assert response.json() == ["v1.0/", "v1.1/"]


def test_unsupported_version_returns_404(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v9.9/")
    assert response.status_code == 404


def test_list_receivers_returns_all_5(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v1.1/single/receivers/")
    assert response.status_code == 200
    ids = response.json()
    assert len(ids) == 5
    assert f"{nmos_client.video_id}/" in ids


def test_unknown_receiver_id_returns_404(nmos_client):
    response = nmos_client.get("/x-nmos/connection/v1.1/single/receivers/not-a-real-id/staged/")
    assert response.status_code == 404


def test_get_constraints_is_unconstrained_2_legs(nmos_client):
    response = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/constraints/"
    )
    assert response.json() == [{}, {}]


def test_get_transport_type(nmos_client):
    response = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/transporttype/"
    )
    assert response.json() == "urn:x-nmos:transport:rtp.mcast"


def test_staged_initially_mirrors_active_config(nmos_client):
    response = nmos_client.get(f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/")
    staged = response.json()
    assert staged["master_enable"] is False
    assert len(staged["transport_params"]) == 2


def test_patch_staged_without_activation_does_not_touch_config(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200
    staged = response.json()
    assert staged["master_enable"] is True
    assert staged["transport_params"][0]["source_ip"] == "192.168.10.1"

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["video"][0]["enabled"] is False  # unchanged: not activated yet


def test_patch_staged_with_activate_immediate_applies_to_config(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200
    assert response.json()["activation"]["activation_time"] is not None

    config = nmos_client.config_store.load_config()
    receiver = config["receivers"]["video"][0]
    assert receiver["enabled"] is True
    assert receiver["amber"]["source_ip"] == "192.168.10.1"
    assert receiver["amber"]["group_ip"] == "239.1.1.1"
    assert receiver["amber"]["port"] == 5004
    assert receiver["blue"]["source_ip"] == "192.168.20.1"
    assert receiver["sdp_source"] == "nmos"
    # No transport_file/SDP was given here, only bare transport_params, so
    # there is no scan-type info to derive from -- an already-valid
    # video_format is left as-is (never reverted to a placeholder).
    assert receiver["video_format"] == "59.94i"

    active = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/active/"
    ).json()
    assert active["master_enable"] is True
    assert active["transport_params"][0]["source_ip"] == "192.168.10.1"


def test_patch_staged_with_transport_file_parses_sdp_and_activates(nmos_client):
    sdp_text = (
        "v=0\r\n"
        "o=- 1 1 IN IP4 192.168.10.1\r\n"
        "s=Video Sender\r\n"
        "t=0 0\r\n"
        "m=video 5004 RTP/AVP 96\r\n"
        "c=IN IP4 239.5.5.5/32\r\n"
        "a=source-filter: incl IN IP4 239.5.5.5 192.168.10.9\r\n"
    )
    patch = {
        "master_enable": True,
        "transport_file": {"data": sdp_text, "type": "application/sdp"},
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 200

    config = nmos_client.config_store.load_config()
    receiver = config["receivers"]["video"][0]
    assert receiver["amber"]["group_ip"] == "239.5.5.5"
    assert receiver["amber"]["source_ip"] == "192.168.10.9"
    assert receiver["payload_id"] == 96
    assert receiver["nmos_sdp"] == sdp_text
    # This SDP has no fmtp "interlace" keyword, so there is no scan-type
    # info to derive -- the field keeps its already-valid default.
    assert receiver["video_format"] == "59.94i"


def test_nmos_activate_derives_video_format_from_sdp_interlace_flag(nmos_client):
    """Operator-confirmed expected behaviour: the field always shows a
    concrete value (never a literal "SDP" placeholder), updated live from
    the SDP's actual content when NMOS drives the receiver. Here the
    receiver was previously fixed to "59.94p" and the incoming SDP marks
    the stream interlaced -- the real value must win."""
    config = nmos_client.config_store.load_config()
    config["receivers"]["video"][0]["video_format"] = "59.94p"
    nmos_client.config_store.save_config(config)

    sdp_text = (
        "v=0\r\no=- 1 1 IN IP4 192.168.10.1\r\ns=Video Sender\r\nt=0 0\r\n"
        "m=video 5004 RTP/AVP 96\r\nc=IN IP4 239.5.5.5/32\r\n"
        "a=source-filter: incl IN IP4 239.5.5.5 192.168.10.9\r\n"
        "a=fmtp:96 sampling=YCbCr-4:2:2; width=1920; height=1080; interlace; exactframerate=30000/1001\r\n"
    )
    patch = {
        "master_enable": True,
        "transport_file": {"data": sdp_text, "type": "application/sdp"},
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )

    receiver = nmos_client.config_store.load_config()["receivers"]["video"][0]
    assert receiver["video_format"] == "59.94i"


def test_nmos_activate_without_sdp_text_leaves_valid_video_format_unchanged(nmos_client):
    """A controller that PATCHes only bare transport_params (no
    transport_file) has given us no format info -- an already-valid value
    must be left exactly as it was, not reset to any default."""
    config = nmos_client.config_store.load_config()
    config["receivers"]["video"][0]["video_format"] = "59.94p"
    nmos_client.config_store.save_config(config)

    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )

    receiver = nmos_client.config_store.load_config()["receivers"]["video"][0]
    assert receiver["video_format"] == "59.94p"


def test_nmos_activate_derives_packet_time_from_sdp_ptime(nmos_client):
    config = nmos_client.config_store.load_config()
    config["receivers"]["audio"][0]["packet_time"] = "0.125ms"
    nmos_client.config_store.save_config(config)

    sdp_text = (
        "v=0\r\no=- 1 1 IN IP4 192.168.10.2\r\ns=Audio Sender\r\nt=0 0\r\n"
        "m=audio 6000 RTP/AVP 97\r\nc=IN IP4 239.9.9.9/32\r\n"
        "a=source-filter: incl IN IP4 239.9.9.9 10.0.0.1\r\n"
        "a=ptime:1\r\n"
    )
    patch = {
        "master_enable": True,
        "transport_file": {"data": sdp_text, "type": "application/sdp"},
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.audio_id}/staged/", json=patch
    )

    receiver = nmos_client.config_store.load_config()["receivers"]["audio"][0]
    assert receiver["packet_time"] == "1ms"
    assert receiver["sampling"] == "48kHz"


def test_nmos_activate_without_sdp_text_leaves_valid_packet_time_unchanged(nmos_client):
    config = nmos_client.config_store.load_config()
    config["receivers"]["audio"][0]["packet_time"] = "0.125ms"
    nmos_client.config_store.save_config(config)

    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "10.0.0.1", "multicast_ip": "239.9.9.9", "destination_port": 6000},
            {"source_ip": "10.0.1.1", "multicast_ip": "239.9.9.10", "destination_port": 6000},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.audio_id}/staged/", json=patch
    )

    receiver = nmos_client.config_store.load_config()["receivers"]["audio"][0]
    assert receiver["packet_time"] == "0.125ms"


def test_scheduled_activation_mode_is_rejected(nmos_client):
    patch = {"activation": {"mode": "activate_scheduled_absolute", "requested_time": "10:0"}}
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 400


def test_transport_params_must_have_two_legs(nmos_client):
    patch = {"transport_params": [{"source_ip": "1.2.3.4"}]}
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )
    assert response.status_code == 400


def test_master_enable_false_disables_receiver_on_activation(nmos_client):
    enable_patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=enable_patch
    )

    disable_patch = {"master_enable": False, "activation": {"mode": "activate_immediate"}}
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=disable_patch
    )

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["video"][0]["enabled"] is False


class TestNoTrailingSlashUrls:
    """Regression tests for the 307-redirect bug: a real NMOS controller
    requests the canonical (no trailing slash) IS-05 URLs per the AMWA
    RAML spec, e.g. PATCH .../staged, not .../staged/. An earlier
    revision only registered the trailing-slash form, so FastAPI's
    default redirect_slashes behaviour returned a 307 for these -- which
    the controller's PATCH did not follow, and which never reached this
    module's handlers at all (so nothing was logged, and config.json was
    never touched). `follow_redirects=False` here makes sure the request
    is served directly, not merely reachable via an intermediate hop."""

    def test_patch_staged_without_trailing_slash_is_served_directly(self, nmos_client):
        patch = {"master_enable": True, "activation": {"mode": "activate_immediate"}}
        response = nmos_client.patch(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged",
            json=patch,
            follow_redirects=False,
        )
        assert response.status_code == 200
        config = nmos_client.config_store.load_config()
        assert config["receivers"]["video"][0]["enabled"] is True

    def test_get_active_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/active",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_get_staged_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_get_constraints_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/constraints",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_get_transporttype_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/transporttype",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_list_receivers_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            "/x-nmos/connection/v1.1/single/receivers", follow_redirects=False
        )
        assert response.status_code == 200

    def test_receiver_index_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get(
            f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_single_index_without_trailing_slash_is_served_directly(self, nmos_client):
        response = nmos_client.get("/x-nmos/connection/v1.1/single", follow_redirects=False)
        assert response.status_code == 200


def test_audio_receiver_activation(nmos_client):
    patch = {
        "master_enable": True,
        "transport_params": [
            {"source_ip": "10.0.0.1", "multicast_ip": "239.9.9.9", "destination_port": 6000},
            {"source_ip": "10.0.1.1", "multicast_ip": "239.9.9.10", "destination_port": 6000},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    response = nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.audio_id}/staged/", json=patch
    )
    assert response.status_code == 200

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["audio"][0]["enabled"] is True
    assert config["receivers"]["audio"][0]["amber"]["group_ip"] == "239.9.9.9"


def test_activate_persists_sender_id(nmos_client):
    """Regression test: sender_id staged by the controller must be
    persisted, so both IS-04's subscription.sender_id and IS-05's
    active.sender_id reflect what this receiver is actually subscribed
    to, instead of a hardcoded None (see resources.py's _receiver_common
    and NOTES.md)."""
    patch = {
        "master_enable": True,
        "sender_id": "773372d9-b6e1-45d0-9b7a-593ae4317a0d",
        "transport_params": [
            {"source_ip": "192.168.10.1", "multicast_ip": "239.1.1.1", "destination_port": 5004},
            {"source_ip": "192.168.20.1", "multicast_ip": "239.1.2.1", "destination_port": 5004},
        ],
        "activation": {"mode": "activate_immediate"},
    }
    nmos_client.patch(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/staged/", json=patch
    )

    config = nmos_client.config_store.load_config()
    assert config["receivers"]["video"][0]["sender_id"] == "773372d9-b6e1-45d0-9b7a-593ae4317a0d"

    active = nmos_client.get(
        f"/x-nmos/connection/v1.1/single/receivers/{nmos_client.video_id}/active/"
    ).json()
    assert active["sender_id"] == "773372d9-b6e1-45d0-9b7a-593ae4317a0d"

    from app.nmos import identity as identity_module, resources

    identity = identity_module.load_identity()
    node_receiver = resources.build_video_receiver(0, config, identity)
    assert node_receiver["subscription"] == {
        "sender_id": "773372d9-b6e1-45d0-9b7a-593ae4317a0d",
        "active": True,
    }
