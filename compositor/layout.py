"""compositor/layout.py

対応要件: ④-4 (4分割/シングル表示切替), ④-1 (フォーマット不統一アラーム)

FFmpegプロセスを再起動せずに1秒以内で表示モードを切り替えるため、
「常時4分割+シングルの両レイアウトを構築しておき、enable式をzmq経由で
切り替える」という設計 (README.md参照) のロジック部分。
ハードウェア/FFmpegバイナリに依存しないため、pytestで完全にテストできる。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DisplayMode(str, Enum):
    QUAD = "quad"       # 4分割
    SINGLE = "single"   # シングル全画面


ALARM_TEXT = "映像フォーマットが4系統で非統一です"


class LayoutError(ValueError):
    pass


@dataclass
class DisplayModeController:
    """④-4: 表示モードの状態機械。WebGUI/視聴ページ双方からの切替要求を受ける。"""

    mode: DisplayMode = DisplayMode.QUAD
    selected_index: int = 0  # SINGLEモード時にフルスクリーン表示するReceiver (0-3)
    format_alarm: bool = False
    _history: list[str] = field(default_factory=list)

    def set_mode(self, mode: DisplayMode, selected_index: int | None = None) -> list[str]:
        if mode == DisplayMode.SINGLE:
            idx = self.selected_index if selected_index is None else selected_index
            if not (0 <= idx < 4):
                raise LayoutError(f"selected_indexは0-3の範囲でなければならない: {idx}")
            self.selected_index = idx
        self.mode = mode
        cmds = self._build_zmq_commands()
        self._history.append(mode.value)
        return cmds

    def toggle(self) -> list[str]:
        """視聴ページ/WebGUIの「クリックでトグル」操作 (④-4)。"""
        next_mode = DisplayMode.SINGLE if self.mode == DisplayMode.QUAD else DisplayMode.QUAD
        return self.set_mode(next_mode)

    def set_format_alarm(self, active: bool) -> list[str]:
        self.format_alarm = active
        return self._build_zmq_commands()

    def _build_zmq_commands(self) -> list[str]:
        """FFmpeg zmqフィルタへ送るコマンド列を生成する。

        コマンド形式は FFmpeg `zmq` フィルタの仕様
        (`<filter_name>@<index> <option> <value>`) に準拠。
        """
        cmds = []
        quad_enable = "1" if self.mode == DisplayMode.QUAD else "0"
        single_enable = "1" if self.mode == DisplayMode.SINGLE else "0"
        cmds.append(f"overlay@quad enable {quad_enable}")
        for i in range(4):
            en = "1" if (self.mode == DisplayMode.SINGLE and i == self.selected_index) else "0"
            cmds.append(f"crop@single{i} enable {en}")
        cmds.append(f"drawtext@alarm enable {'1' if self.format_alarm else '0'}")
        return cmds

    def build_filter_complex(self, alarm_text: str = ALARM_TEXT, enable_zmq: bool = True) -> str:
        """初回起動時にFFmpegへ渡す filter_complex 全体を構築する。

        入力: [0:v][1:v][2:v][3:v] (4映像), 出力ラベル [vout]
        4分割は2x2 (0=左上,1=右上,2=左下,3=右下) と決定 (NOTES.md参照)。

        【2026-09 実機ビルドで判明した修正】
        1. FFmpegには `-zmq_bind_addr` というグローバルCLIオプションは存在
           しない(起動直後に`Unrecognized option`で失敗する)。`zmq`フィルタは
           filter_complex内にフィルタノードとして組み込む必要がある
           (FFmpeg公式ドキュメントのzmq/azmqフィルタ仕様に準拠)。
        2. `zmq`フィルタの`bind_address`オプションにアドレスを明示指定する際、
           バックスラッシュエスケープ(`tcp\\://...\\:5555`)・シングルクォート
           (`bind_address='tcp://...'`)のいずれの方法でも、FFmpegの
           フィルタグラフ構文解析が`:`をオプション区切りとして扱ってしまい
           `[AVFilterGraph] No option name near '//...'`で失敗することを実機で
           確認した(FFmpeg 7.0.3で検証。既知のエスケープの複雑さに起因する
           もので、本プロジェクト固有のバグではない可能性が高い)。
           `zmq`フィルタのコンパイル時デフォルト値が`tcp://*:5555`
           (libavfilter/f_zmq.c参照)であり、ちょうど本システムが使いたい
           5555番ポートと一致するため、`bind_address`オプションを一切指定せず
           デフォルトのまま`zmq`フィルタを裸で追加する方式に変更し、
           エスケープ問題そのものを回避した。`compositor/zmqctl.py`の
           接続先(`tcp://127.0.0.1:5555`)は、`tcp://*:5555`でbindされた
           ソケットへループバック経由で問題なく接続できる。
        """
        parts = []
        # 各入力を1920x1080相当のハーフサイズにスケールして2x2に並べる
        parts.append(
            "[0:v]scale=960:540[q0];[1:v]scale=960:540[q1];"
            "[2:v]scale=960:540[q2];[3:v]scale=960:540[q3];"
            "[q0][q1]hstack=inputs=2[qtop];[q2][q3]hstack=inputs=2[qbot];"
            "[qtop][qbot]vstack=inputs=2[quadbase]"
        )
        parts.append(
            f"[quadbase]overlay@quad=x=0:y=0:enable=1[quadout]"
        )
        for i in range(4):
            parts.append(f"[{i}:v]crop@single{i}=1920:1080:0:0:enable=0[single{i}]")
        # シングルモードでは選択中の入力のみ表示 (enableはランタイムでzmq切替)
        parts.append(
            "[single0][single1][single2][single3]"
            "overlay@quad2=x=0:y=0:enable=0[singleout]"
        )
        if enable_zmq:
            parts.append(
                f"[quadout]drawtext@alarm=text='{alarm_text}':"
                "fontcolor=red:fontsize=48:x=(w-text_w)/2:y=h-100:enable=0[vout_pre]"
            )
            parts.append("[vout_pre]zmq[vout]")
        else:
            parts.append(
                f"[quadout]drawtext@alarm=text='{alarm_text}':"
                "fontcolor=red:fontsize=48:x=(w-text_w)/2:y=h-100:enable=0[vout]"
            )
        return ";".join(parts)
