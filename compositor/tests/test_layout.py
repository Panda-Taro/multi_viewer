import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from layout import DisplayModeController, DisplayMode, LayoutError, ALARM_TEXT


def test_default_mode_is_quad():
    c = DisplayModeController()
    assert c.mode == DisplayMode.QUAD


def test_toggle_switches_quad_to_single():
    c = DisplayModeController()
    c.toggle()
    assert c.mode == DisplayMode.SINGLE


def test_toggle_twice_returns_to_quad():
    c = DisplayModeController()
    c.toggle()
    c.toggle()
    assert c.mode == DisplayMode.QUAD


def test_set_mode_single_requires_valid_index():
    c = DisplayModeController()
    with pytest.raises(LayoutError):
        c.set_mode(DisplayMode.SINGLE, selected_index=9)


def test_set_mode_single_selects_correct_stream():
    c = DisplayModeController()
    c.set_mode(DisplayMode.SINGLE, selected_index=2)
    assert c.selected_index == 2
    cmds = c._build_zmq_commands()
    assert "crop@single2 enable 1" in cmds
    assert "crop@single0 enable 0" in cmds


def test_quad_mode_enables_quad_overlay_disables_all_single_crops():
    c = DisplayModeController()
    cmds = c._build_zmq_commands()
    assert "overlay@quad enable 1" in cmds
    assert all(f"crop@single{i} enable 0" in cmds for i in range(4))


def test_format_alarm_toggle():
    c = DisplayModeController()
    cmds = c.set_format_alarm(True)
    assert "drawtext@alarm enable 1" in cmds
    cmds = c.set_format_alarm(False)
    assert "drawtext@alarm enable 0" in cmds


def test_build_filter_complex_contains_alarm_text():
    c = DisplayModeController()
    fc = c.build_filter_complex()
    assert ALARM_TEXT in fc
    assert "hstack" in fc and "vstack" in fc


def test_history_tracks_mode_changes():
    c = DisplayModeController()
    c.toggle()
    c.set_mode(DisplayMode.QUAD)
    assert c._history == ["single", "quad"]
