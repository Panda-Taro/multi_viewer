def test_ensure_identity_fills_in_missing_ids_without_saving(isolated_dirs):
    """ensure_identity() itself is a pure in-memory mutator now (step 2i);
    persistence is the caller's job -- see load_identity() below for the
    locked load+maybe-save wrapper every real caller actually uses."""
    config_store = isolated_dirs["config_store"]
    from app.nmos import identity as identity_module

    config = config_store.load_config()
    assert config["identity"]["node_id"] is None

    changed = identity_module.ensure_identity(config)
    assert changed is True
    assert config["identity"]["node_id"]
    assert config["identity"]["device_id"]
    assert all(config["identity"]["video_receiver_ids"])
    assert all(config["identity"]["audio_receiver_ids"])
    assert len(config["identity"]["video_receiver_ids"]) == 4
    assert len(config["identity"]["audio_receiver_ids"]) == 1

    # Not saved by ensure_identity() alone.
    reloaded = config_store.load_config()
    assert reloaded["identity"]["node_id"] is None

    assert identity_module.ensure_identity(config) is False


def test_load_identity_generates_and_persists_ids(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    from app.nmos import identity as identity_module

    config = config_store.load_config()
    assert config["identity"]["node_id"] is None

    identity = identity_module.load_identity()
    assert identity["node_id"]
    assert identity["device_id"]
    assert all(identity["video_receiver_ids"])
    assert all(identity["audio_receiver_ids"])
    assert len(identity["video_receiver_ids"]) == 4
    assert len(identity["audio_receiver_ids"]) == 1

    # Persisted: a fresh load sees the same IDs.
    reloaded = config_store.load_config()
    assert reloaded["identity"]["node_id"] == identity["node_id"]


def test_ensure_identity_is_idempotent(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    from app.nmos import identity as identity_module

    first = identity_module.load_identity()
    second = identity_module.load_identity()
    assert first == second


def test_receiver_lookup_maps_ids_to_kind_and_index(isolated_dirs):
    from app.nmos import identity as identity_module

    identity = identity_module.load_identity()
    lookup = identity_module.receiver_lookup(identity)

    assert lookup[identity["video_receiver_ids"][0]] == ("video", 0)
    assert lookup[identity["video_receiver_ids"][3]] == ("video", 3)
    assert lookup[identity["audio_receiver_ids"][0]] == ("audio", 0)
    assert len(lookup) == 5
