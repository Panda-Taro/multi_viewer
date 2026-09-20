import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from compose import build_video_audio_args


def make_config():
    return {
        "interfaces": [
            {"name": "amber0", "ip": "10.0.0.1"},
            {"name": "blue0", "ip": "10.0.1.1"},
        ],
        "rx_sessions": [
            {
                "ip": ["239.1.1.10", "239.2.1.10"],
                "interface": [0, 1],
                "video": [{"type": "frame", "start_port": 20000, "payload_type": 112}],
            },
            {
                "ip": ["239.1.1.11", "239.2.1.11"],
                "interface": [0, 1],
                "video": [{"type": "frame", "start_port": 20001, "payload_type": 112}],
            },
            {
                "ip": ["239.1.1.12", "239.2.1.12"],
                "interface": [0, 1],
                "video": [{"type": "frame", "start_port": 20002, "payload_type": 112}],
            },
            {
                "ip": ["239.1.1.13", "239.2.1.13"],
                "interface": [0, 1],
                "video": [{"type": "frame", "start_port": 20003, "payload_type": 112}],
            },
            {
                "ip": ["239.1.1.20", "239.2.1.20"],
                "interface": [0, 1],
                "audio": [{"type": "frame", "start_port": 20100, "payload_type": 111}],
            },
        ],
    }


def test_build_video_audio_args_uses_real_ips_not_placeholders():
    args, kinds, audio_index = build_video_audio_args(make_config())
    assert "AMBER_IP" not in args
    assert "10.0.0.1" in args
    assert "239.1.1.10" in args
    assert kinds.count("video") == 4
    assert kinds.count("audio") == 1
    assert audio_index == 4


def test_build_video_audio_args_includes_redundant_blue_leg():
    args, _, _ = build_video_audio_args(make_config())
    assert "10.0.1.1" in args  # blue local ip (r_sip)
    assert "239.2.1.10" in args  # blue multicast (r_rx_ip) for video1


def test_build_video_audio_args_requires_exactly_4_video_sessions():
    config = make_config()
    config["rx_sessions"] = [s for s in config["rx_sessions"] if "audio" not in s][:2] + [
        s for s in config["rx_sessions"] if "audio" in s
    ]
    with pytest.raises(ValueError):
        build_video_audio_args(config)


def test_build_video_audio_args_requires_audio_session():
    config = make_config()
    config["rx_sessions"] = [s for s in config["rx_sessions"] if "audio" not in s]
    with pytest.raises(ValueError):
        build_video_audio_args(config)
