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
    # 2026-09実機ビルドで判明: `crop`フィルタはenable(timeline)オプションに
    # 対応していないため、overlayフィルタのみで表示切替する設計に変更した。
    c = DisplayModeController()
    c.set_mode(DisplayMode.SINGLE, selected_index=2)
    assert c.selected_index == 2
    cmds = c._build_zmq_commands()
    assert "overlay@single2 enable 1" in cmds
    assert "overlay@single0 enable 0" in cmds


def test_quad_mode_disables_mode_overlay_and_all_single_overlays():
    c = DisplayModeController()
    cmds = c._build_zmq_commands()
    assert "overlay@mode enable 0" in cmds
    assert all(f"overlay@single{i} enable 0" in cmds for i in range(4))


def test_single_mode_enables_mode_overlay():
    c = DisplayModeController()
    c.set_mode(DisplayMode.SINGLE, selected_index=0)
    cmds = c._build_zmq_commands()
    assert "overlay@mode enable 1" in cmds


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


def test_build_filter_complex_embeds_zmq_filter_not_cli_flag():
    # 2026-09実機ビルドで判明: FFmpegに `-zmq_bind_addr` というグローバル
    # CLIオプションは存在せず、filter_complex内に `zmq` フィルタノードとして
    # 組み込む必要がある (zmqctl.pyがREQ/REPで送るコマンド宛先はfilter名)。
    # また、bind_addressをインライン指定するとバックスラッシュ/シングル
    # クォートいずれのエスケープでもFFmpegのフィルタグラフ構文解析と衝突して
    # 失敗することを実機で確認したため、コンパイル時デフォルト(tcp://*:5555。
    # ちょうど本システムが使うポートと一致)をそのまま使い、bind_addressは
    # 一切指定しない裸の`zmq`フィルタとして埋め込む方式にした。
    c = DisplayModeController()
    fc = c.build_filter_complex()
    assert "]zmq[vout]" in fc
    assert "bind_address" not in fc
    assert fc.endswith("[vout]")


def test_build_filter_complex_without_zmq_still_valid():
    c = DisplayModeController()
    fc = c.build_filter_complex(enable_zmq=False)
    assert "zmq" not in fc
    assert fc.endswith("[vout]")


def test_build_filter_complex_does_not_use_crop_enable():
    # 2026-09実機ビルドで判明: cropフィルタはenable(timeline)オプション非対応
    # (`Timeline ('enable' option) not supported with filter 'crop'`)。
    c = DisplayModeController()
    fc = c.build_filter_complex()
    assert "crop" not in fc


def test_build_filter_complex_overlay_filters_have_exactly_two_inputs():
    # 2026-09実機ビルドで判明: overlayフィルタは入力を2つしか取れないため、
    # `[a][b][c][d]overlay=...` のような4入力指定は構文エラーになる。
    # 各overlayインスタンスの直前のパッドラベルが常にちょうど2個であることを
    # 検証し、同種の回帰を防ぐ。
    import re

    c = DisplayModeController()
    fc = c.build_filter_complex()
    for chain in fc.split(";"):
        m = re.match(r"((?:\[[^\]]+\])+)overlay@", chain)
        if m:
            labels = re.findall(r"\[[^\]]+\]", m.group(1))
            assert len(labels) == 2, f"overlayへの入力が2つでない: {chain}"


def test_history_tracks_mode_changes():
    c = DisplayModeController()
    c.toggle()
    c.set_mode(DisplayMode.QUAD)
    assert c._history == ["single", "quad"]
