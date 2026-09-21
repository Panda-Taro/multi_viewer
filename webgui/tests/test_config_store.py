def test_load_config_returns_defaults_when_no_file(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    config = config_store.load_config()
    assert len(config["receivers"]["video"]) == 4
    assert len(config["receivers"]["audio"]) == 1
    assert config["display"]["mode"] == "quad"


def test_save_then_load_roundtrips(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    config = config_store.load_config()
    config["ptp"]["domain"] = 42
    config_store.save_config(config)

    reloaded = config_store.load_config()
    assert reloaded["ptp"]["domain"] == 42


def test_save_is_atomic_no_partial_file_left_on_disk(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    config_store.save_config(config_store.load_config())
    assert config_store.CONFIG_PATH.exists()
    assert not config_store.CONFIG_PATH.with_suffix(".json.tmp").exists()


def test_load_config_merges_missing_keys_from_defaults(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    # Simulate an older on-disk config missing a key a later schema added.
    partial = {"ptp": {"domain": 5}}
    config_store.save_config(partial)

    config = config_store.load_config()
    assert config["ptp"]["domain"] == 5
    assert "receivers" in config
    assert len(config["receivers"]["video"]) == 4


def test_update_section_rejects_unknown_section(isolated_dirs):
    config_store = isolated_dirs["config_store"]
    try:
        config_store.update_section("not_a_real_section", {})
        assert False, "expected KeyError"
    except KeyError:
        pass
