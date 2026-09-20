"""compositor/layout.py

対応要件: ④-4 (4分割/シングル表示切替), ④-1 (フォーマット不統一アラーム)

FFmpegプロセスを再起動せずに1秒以内で表示モードを切り替えるため、
「常時4分割+シングルの両レイアウトを構築しておき、enable式をzmq経由で
切り替える」という設計 (README.md参照) のロジック部分。
ハードウェア/FFmpegバイナリに依存しないため、pytestで完全にテストできる。

【2026-09 実機ビルドで判明したフィルタグラフ設計の修正】
当初の実装には以下2つの構造的な誤りがあり、実機で
`Timeline ('enable' option) not supported with filter 'crop'` および
(修正後に判明したはずの) overlayフィルタへの入力過多という2つの問題が
あった。
1. `crop` フィルタは `enable` (timeline) オプションに対応していない
   (FFmpeg 7.0.3で実機確認)。ランタイムでの表示/非表示切替には
   `overlay` フィルタ(timeline対応)のみを使う設計に変更した。
2. `overlay` フィルタは入力を厳密に2つ(base + overlay)しか取れないため、
   `[single0][single1][single2][single3]overlay@quad2=...` のように
   4入力を1つのoverlayに渡す記述は構文として成立しない。また
   `[quadbase]overlay@quad=...[quadout]` も入力が1つしかなく無効だった。
   正しくは、(a) 4分割合成(quadout)はhstack/vstackの結果をそのまま使い
   overlay不要、(b) シングル表示(singleout)は黒背景に対しoverlay0..3を
   順にチェーンし、選択中の1本だけenable=1にする、(c) 最後にquadoutと
   singleoutを1つのoverlay(2入力)で合成し、そのenableで表示モードを
   切り替える、という3段構成に書き直した。
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

        フィルタ構成 (build_filter_complex参照):
          - `overlay@single0`..`overlay@single3`: シングル表示ブランチで
            どの入力を黒背景に重ねるかを個別に選択 (同時に有効なのは高々1つ)。
          - `overlay@mode`: 4分割(quadout)の上にシングル映像(singleout)を
            重ねるかどうかで表示モードを切り替える。
          - `drawtext@alarm`: フォーマット不統一アラームのOSD表示。
        """
        cmds = []
        mode_enable = "1" if self.mode == DisplayMode.SINGLE else "0"
        cmds.append(f"overlay@mode enable {mode_enable}")
        for i in range(4):
            en = "1" if (self.mode == DisplayMode.SINGLE and i == self.selected_index) else "0"
            cmds.append(f"overlay@single{i} enable {en}")
        cmds.append(f"drawtext@alarm enable {'1' if self.format_alarm else '0'}")
        return cmds

    def build_filter_complex(self, alarm_text: str = ALARM_TEXT, enable_zmq: bool = True) -> str:
        """初回起動時にFFmpegへ渡す filter_complex 全体を構築する。

        入力: [0:v][1:v][2:v][3:v] (4映像), 出力ラベル [vout]
        4分割は2x2 (0=左上,1=右上,2=左下,3=右下) と決定 (NOTES.md参照)。

        グラフ構成:
          1. quadout: 4入力をscale+hstack+vstackで2x2合成 (常時静的、
             enable切替は不要)。
          2. singleout: 1920x1080の黒背景に対し、4入力を`overlay@single0..3`
             で順にチェーンする。同時にenable=1になるのは選択中の1本のみ
             (他は enable=0 でパススルー) なので、結果的に選択中の1本だけが
             全画面表示される。
          3. merged: `overlay@mode` でquadoutを土台にsingleoutを重ね、
             enableでモードを切り替える (SINGLE時のみsingleoutが可視化される)。
          4. drawtext@alarm: フォーマット不統一アラームのOSD焼き込み。
          5. zmq (enable_zmq時): ランタイムコマンド受信用フィルタ。
             bind_addressはFFmpegのコンパイル時デフォルト(`tcp://*:5555`。
             libavfilter/f_zmq.c参照)をそのまま使う。理由:
             `bind_address`をfilter_complex内にインライン指定すると、
             バックスラッシュエスケープ・シングルクォートのいずれの方法でも
             FFmpegのフィルタグラフ構文解析と衝突して
             `No option name near '//...'` になることを実機で確認したため。
        """
        parts = []
        # 1. quadout: 各入力を1920x1080相当のハーフサイズにスケールして2x2に並べる
        parts.append(
            "[0:v]scale=960:540[q0];[1:v]scale=960:540[q1];"
            "[2:v]scale=960:540[q2];[3:v]scale=960:540[q3];"
            "[q0][q1]hstack=inputs=2[qtop];[q2][q3]hstack=inputs=2[qbot];"
            "[qtop][qbot]vstack=inputs=2[quadout]"
        )

        # 2. singleout: 黒背景に対し4入力をoverlayでチェーン(overlayは2入力のみ
        #    受け付けるため、4入力を1つのoverlayにまとめることはできない)。
        parts.append("color=c=black:s=1920x1080[sbase]")
        prev = "sbase"
        for i in range(4):
            out_label = "singleout" if i == 3 else f"sov{i}"
            parts.append(f"[{prev}][{i}:v]overlay@single{i}=x=0:y=0:enable=0[{out_label}]")
            prev = out_label

        # 3. merged: quadoutを土台にsingleoutを重ね、モードに応じて表示を切替
        parts.append("[quadout][singleout]overlay@mode=x=0:y=0:enable=0[merged]")

        # 4. アラームOSD
        alarm_out = "vout_pre" if enable_zmq else "vout"
        parts.append(
            f"[merged]drawtext@alarm=text='{alarm_text}':"
            f"fontcolor=red:fontsize=48:x=(w-text_w)/2:y=h-100:enable=0[{alarm_out}]"
        )

        # 5. zmq (ランタイムコマンド受信)
        if enable_zmq:
            parts.append("[vout_pre]zmq[vout]")

        return ";".join(parts)
