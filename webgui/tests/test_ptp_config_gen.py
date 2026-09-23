from app.ptp import config_gen


def test_generated_config_always_contains_client_only():
    text = config_gen.generate_ptp4l_config(
        interface="eth0", domain=127, timestamping_mode="hardware", uds_address="/etc/multiviewer/ptp4l.sock"
    )
    assert config_gen.validate_client_only(text)
    assert "clientOnly              1" in text


def test_generated_config_reflects_domain_and_interface():
    text = config_gen.generate_ptp4l_config(
        interface="eth3", domain=42, timestamping_mode="software", uds_address="/etc/multiviewer/ptp4l.sock"
    )
    assert "domainNumber            42" in text
    assert "[eth3]" in text


def test_generated_config_selects_hardware_or_software_time_stamping():
    hw_text = config_gen.generate_ptp4l_config(
        interface="eth0", domain=127, timestamping_mode="hardware", uds_address="/tmp/ptp4l.sock"
    )
    sw_text = config_gen.generate_ptp4l_config(
        interface="eth0", domain=127, timestamping_mode="software", uds_address="/tmp/ptp4l.sock"
    )
    assert "time_stamping           hardware" in hw_text
    assert "time_stamping           software" in sw_text


def test_generate_ptp4l_config_rejects_unknown_timestamping_mode():
    try:
        config_gen.generate_ptp4l_config(
            interface="eth0", domain=127, timestamping_mode="quantum", uds_address="/tmp/ptp4l.sock"
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_generate_ptp4l_config_rejects_empty_interface():
    try:
        config_gen.generate_ptp4l_config(
            interface="", domain=127, timestamping_mode="hardware", uds_address="/tmp/ptp4l.sock"
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_validate_client_only_rejects_missing_or_altered_directive():
    assert not config_gen.validate_client_only("[global]\ndomainNumber 127\n")
    assert not config_gen.validate_client_only("[global]\nclientOnly              0\n")
    assert not config_gen.validate_client_only("[global]\n# clientOnly              1\n")


def test_write_ptp4l_config_writes_file_that_validates(tmp_path):
    path = tmp_path / "ptp4l.conf"
    config_gen.write_ptp4l_config(
        path, interface="eth0", domain=127, timestamping_mode="hardware", uds_address="/tmp/ptp4l.sock"
    )
    written = path.read_text(encoding="utf-8")
    assert config_gen.validate_client_only(written)
    assert "[eth0]" in written


def test_write_ptp4l_config_always_regenerates_from_scratch(tmp_path):
    """A stale/hand-edited file on disk must never survive a regeneration
    -- requirement 4.3.5's clientOnly guarantee depends on this."""
    path = tmp_path / "ptp4l.conf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[global]\nclientOnly              0\ndomainNumber 999\n", encoding="utf-8")

    config_gen.write_ptp4l_config(
        path, interface="eth0", domain=127, timestamping_mode="hardware", uds_address="/tmp/ptp4l.sock"
    )
    written = path.read_text(encoding="utf-8")
    assert config_gen.validate_client_only(written)
    assert "domainNumber            127" in written
