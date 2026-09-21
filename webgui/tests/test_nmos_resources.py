def test_build_node_has_required_fields(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    node = resources.build_node(config, identity)
    assert node["id"] == identity["node_id"]
    assert node["label"] == "MultiViewer"
    assert ":" in node["version"]  # "<seconds>:<nanoseconds>"
    assert node["api"]["versions"] == ["v1.1", "v1.2", "v1.3"]
    assert len(node["interfaces"]) == 2


def test_node_interfaces_chassis_and_port_id_match_is04_mac_pattern(isolated_dirs):
    """IS-04's node_interface schema requires colon-separated lowercase
    hex (`^([0-9a-f]{2}:){5}[0-9a-f]{2}$`); a dash-separated value here
    caused a real registry to reject registration with 400 Bad Request."""
    import re

    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    node = resources.build_node(config, identity)
    pattern = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
    for interface in node["interfaces"]:
        assert pattern.match(interface["chassis_id"]), interface["chassis_id"]
        assert pattern.match(interface["port_id"]), interface["port_id"]


def test_node_clock_does_not_claim_unimplemented_ptp(isolated_dirs):
    """ref_type "ptp" requires additional fields (traceable/version/gmid/
    locked) that only a real PTP client (step 3) can supply; declaring it
    without them is schema-invalid and was another cause of a real
    registry's 400 Bad Request."""
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    node = resources.build_node(config, identity)
    assert node["clocks"] == [{"name": "clk0", "ref_type": "internal"}]


def test_build_device_references_node_and_all_receivers(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    device = resources.build_device(config, identity)
    assert device["id"] == identity["device_id"]
    assert device["node_id"] == identity["node_id"]
    assert device["senders"] == []
    assert len(device["receivers"]) == 5
    assert set(device["receivers"]) == set(
        identity["video_receiver_ids"] + identity["audio_receiver_ids"]
    )
    assert len(device["controls"]) == 2  # v1.0 and v1.1 IS-05 controls


def test_build_all_receivers_returns_4_video_1_audio(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    receivers = resources.build_all_receivers(config, identity)
    assert len(receivers) == 5

    video = [r for r in receivers if r["format"] == "urn:x-nmos:format:video"]
    audio = [r for r in receivers if r["format"] == "urn:x-nmos:format:audio"]
    assert len(video) == 4
    assert len(audio) == 1

    for r in receivers:
        assert r["device_id"] == identity["device_id"]
        assert r["transport"] == "urn:x-nmos:transport:rtp.mcast"
        assert r["interface_bindings"] == ["media_amber", "media_blue"]

    assert audio[0]["caps"]["media_types"] == ["audio/L24"]
    assert video[0]["caps"]["media_types"] == ["video/raw"]


def test_receiver_ids_match_identity_order(isolated_dirs):
    from app import config_store
    from app.nmos import identity as identity_module
    from app.nmos import resources

    config = config_store.load_config()
    identity = identity_module.ensure_identity(config)["identity"]

    video_receivers = [resources.build_video_receiver(i, config, identity) for i in range(4)]
    for i, r in enumerate(video_receivers):
        assert r["id"] == identity["video_receiver_ids"][i]
