"""compositor/zmqctl.py

対応要件: ④-4 (1秒以内の表示モード反映)

FFmpegの `zmq` フィルタ (ffmpeg が `--enable-libzmq` でビルドされている場合に
利用可能。REQ/REPソケットでフィルタパラメータをランタイム変更できる) に対して
TCP経由でコマンドを送信するクライアント。WebGUIバックエンド・視聴ページ用
JSからのHTTPリクエストを、このモジュール経由でFFmpegプロセスに伝達する。

pyzmqへの依存を避けるため、生ソケットでZMQ REQの最小限のフレーミングは行わず、
FFmpeg zmqフィルタは実際には zmq の REP ソケットとして動作するため、本番では
`pyzmq` が必要。本モジュールは依存を薄くするため、pyzmqが利用可能な場合のみ
実送信し、無い場合は例外を投げる設計とし、コマンド生成部分 (`layout.py`) は
zmqに一切依存しない形にしてテスト容易性を確保した。
"""
from __future__ import annotations


class ZmqNotAvailableError(RuntimeError):
    pass


class FfmpegZmqClient:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:5555"):
        self.endpoint = endpoint
        self._socket = None

    def _ensure_socket(self):
        if self._socket is not None:
            return
        try:
            import zmq  # type: ignore
        except ImportError as e:
            raise ZmqNotAvailableError(
                "pyzmq がインストールされていません。実機では `pip install pyzmq` "
                "してください。"
            ) from e
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.connect(self.endpoint)
        self._socket = sock

    def send_commands(self, commands: list[str]) -> list[str]:
        """layout.py が生成したコマンド列をFFmpegへ順次送信する。"""
        self._ensure_socket()
        replies = []
        for cmd in commands:
            self._socket.send_string(cmd)
            replies.append(self._socket.recv_string())
        return replies
