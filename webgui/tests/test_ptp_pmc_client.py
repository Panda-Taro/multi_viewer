from app.ptp import pmc_client

# Field formatting (name and value on an indented line, two-tab prefix per
# linuxptp's pmc_show()/IFMT) verified against the linuxptp source
# (pmc.c); the header line above the fields is deliberately reproduced
# with a slightly different (single-tab) indentation here specifically to
# confirm the parser does not depend on that line's exact format.
TIME_STATUS_NP_LOCKED = """sending: GET TIME_STATUS_NP
\tc4:70:bd.ff:fe:12:34:56-0 seq 0 RESPONSE MANAGEMENT TIME_STATUS_NP
\t\tmaster_offset              283
\t\tingress_time               1234567890
\t\tcumulativeScaledRateOffset +0.000000000
\t\tscaledLastGmPhaseChange    0
\t\tgmTimeBaseIndicator        0
\t\tlastGmPhaseChange          0x0000\\'0000000000000000.0000
\t\tgmPresent                  true
\t\tgmIdentity                 00b058.feef.0b448a
"""

TIME_STATUS_NP_NO_GM = """sending: GET TIME_STATUS_NP
\tc4:70:bd.ff:fe:12:34:56-0 seq 0 RESPONSE MANAGEMENT TIME_STATUS_NP
\t\tmaster_offset              0
\t\tingress_time               0
\t\tcumulativeScaledRateOffset +0.000000000
\t\tscaledLastGmPhaseChange    0
\t\tgmTimeBaseIndicator        0
\t\tlastGmPhaseChange          0x0000\\'0000000000000000.0000
\t\tgmPresent                  false
\t\tgmIdentity                 000000.0000.000000
"""

PORT_DATA_SET_SLAVE = """sending: GET PORT_DATA_SET
\tc4:70:bd.ff:fe:12:34:56-0 seq 0 RESPONSE MANAGEMENT PORT_DATA_SET
\t\tportIdentity            c4:70:bd.ff:fe:12:34:56-0
\t\tportState               SLAVE
\t\tlogMinDelayReqInterval  -3
\t\tpeerMeanPathDelay       0
\t\tlogAnnounceInterval     0
\t\tannounceReceiptTimeout  3
\t\tlogSyncInterval         -3
\t\tdelayMechanism          1
\t\tlogMinPdelayReqInterval 0
\t\tversionNumber           2
"""

PORT_DATA_SET_LISTENING = PORT_DATA_SET_SLAVE.replace("portState               SLAVE", "portState               LISTENING")


def test_parse_fields_extracts_indented_key_value_pairs():
    fields = pmc_client.parse_fields(TIME_STATUS_NP_LOCKED)
    assert fields["master_offset"] == "283"
    assert fields["gmPresent"] == "true"
    assert fields["gmIdentity"] == "00b058.feef.0b448a"


def test_parse_fields_ignores_non_indented_header_lines():
    fields = pmc_client.parse_fields(TIME_STATUS_NP_LOCKED)
    assert "sending:" not in fields


def test_get_time_status_parses_locked_output(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: TIME_STATUS_NP_LOCKED)
    result = pmc_client.get_time_status("/tmp/ptp4l.sock")
    assert result == {"master_offset_ns": 283, "gm_present": True, "gm_id": "00b058.feef.0b448a"}


def test_get_time_status_parses_no_gm_output(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: TIME_STATUS_NP_NO_GM)
    result = pmc_client.get_time_status("/tmp/ptp4l.sock")
    assert result == {"master_offset_ns": 0, "gm_present": False, "gm_id": "000000.0000.000000"}


def test_get_time_status_returns_none_when_pmc_unreachable(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: None)
    assert pmc_client.get_time_status("/tmp/ptp4l.sock") is None


def test_get_port_state_parses_slave(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: PORT_DATA_SET_SLAVE)
    assert pmc_client.get_port_state("/tmp/ptp4l.sock") == "SLAVE"


def test_get_port_state_parses_listening(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: PORT_DATA_SET_LISTENING)
    assert pmc_client.get_port_state("/tmp/ptp4l.sock") == "LISTENING"


def test_get_port_state_returns_none_when_pmc_unreachable(monkeypatch):
    monkeypatch.setattr(pmc_client, "_run_pmc", lambda uds, query, timeout=3.0: None)
    assert pmc_client.get_port_state("/tmp/ptp4l.sock") is None
