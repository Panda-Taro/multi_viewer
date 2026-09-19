"""webgui/app/main.py

対応要件: ④-8 (WebGUI全体のエントリポイント)、⑦ (認証なし、LAN限定)

`/mgmt/` 配下に設定画面、`/monitor01/` (viewer_path設定可能) はMediaMTXの
WHEPエンドポイントへの簡易プロキシページを提供する。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .routers import dashboard, media, system, logs
from .config_store import store
from .log_store import log_store

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_store.add("webgui", "INFO", "WebGUIサービスを起動しました")
    yield


app = FastAPI(title="MultiViewer WebGUI", lifespan=lifespan)

app.mount("/mgmt/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(dashboard.router)
app.include_router(media.router)
app.include_router(system.router)
app.include_router(logs.router)

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/mgmt/")


@app.get("/monitor01/", response_class=HTMLResponse)
def viewer_page(request: Request):
    """④-6: 視聴ページ。埋め込みWHEPプレイヤー + 表示モードトグルボタン。

    実機ではMediaMTXが提供するWHEPエンドポイント (webrtcAddress:8889) に対し
    ブラウザのWebRTC APIで直接接続する。ここではそのJSを読み込む薄いHTML。
    """
    return templates.TemplateResponse(
        request,
        "viewer.html",
        {"viewer_path": store.viewer.viewer_path},
    )
