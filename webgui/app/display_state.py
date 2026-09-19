"""webgui/app/display_state.py

対応要件: ④-4 (WebGUI・視聴ページ双方から表示モードを切替可能にする)

compositor.layout.DisplayModeController をWebGUIプロセス内で共有し、
WebGUI (`/mgmt/` ダッシュボード) と視聴ページ (`/monitor01/` に埋め込む
トグルボタン、実際にはこのWebGUIが提供する軽量APIをJSから叩く) の
両方から同じ状態を切り替えられるようにする。

本番ではFFmpegプロセスへのzmqコマンド送出 (`compositor.zmqctl`) を
実際に行うが、pyzmq/FFmpeg実行環境がない開発時はコマンド生成のみ確認する。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "compositor"))

from layout import DisplayModeController  # noqa: E402

# アプリ全体で共有する表示モード状態
display_controller = DisplayModeController()
