"""Entrypoint for the NMOS service (multiviewer-nmos.service).

Reads the common port from config.json at startup and serves the NMOS
service app on it. If no port is configured (0), logs and exits rather
than looping forever with nothing listening; systemd (Restart=on-failure)
will retry periodically, which is harmless and picks up the port as soon
as the operator sets one from the WebGUI and the service is restarted.

Run as: python -m app.nmos_main   (see systemd/multiviewer-nmos.service)
"""
from __future__ import annotations

import sys

import uvicorn

from . import config_store, log_store
from .nmos.service import app


def main() -> int:
    config = config_store.load_config()
    port = config["nmos"]["common_port"]
    if not port:
        message = (
            "NMOS共通ポートが未設定です (nmos.common_port)。"
            "WebGUIの「PTP・NMOS設定」画面でポートを設定してから、"
            "multiviewer-nmos.service を再起動してください。"
        )
        log_store.log_event("nmos", "error", message)
        print(message, file=sys.stderr)
        return 1

    uvicorn.run(app, host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
