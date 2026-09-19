# webgui/ — WebGUI (`/mgmt/`)

対応要件: ④-8, ⑤(ログ・監視), ⑦(認証なし)

FastAPI + Jinja2 + Vanilla JS によるダークグレー・Grafana/Zabbyxライクな
管理画面。認証機能は要件により**意図的に実装しない**。

## 構成

- `app/main.py` — FastAPIエントリポイント。`/mgmt/` 配下に画面を提供し、
  `/monitor01/` はMediaMTXへのリバースプロキシ (簡易実装、実機ではnginx等の
  前段プロキシに置換可能)。
- `app/config_store.py` — 全設定 (Receiver/PTP/NMOS/NIC/視聴配信) の
  読み書き・バリデーション・保存失敗時のロールバック (④-8「保存失敗時は
  エラー表示し前の値を保持」に対応)。
- `app/nic_ip_change.py` — NIC IP変更の確認/ロールバック機構
  (④-8, ⑤「自己ロックアウト防止」「変更には再起動が必要」に対応)。
- `app/nic_state.py` — OSから実NIC状態(`ip -j addr show`)を読み取る
  (④-8「実際のNIC状態を読み取りGUIに反映」に対応、ポータビリティ要件⑦)。
- `app/status.py` — ダッシュボード用のシステム状態集約 (CPU/帯域/PTP/Receiver LED)。
- `app/log_store.py` — ログの追記・一覧・エクスポート。
- `app/routers/` — 画面・APIルータ (dashboard, media, system, logs)。
- `app/templates/`, `app/static/` — Jinja2テンプレートとダークテーマCSS/JS。

## 起動方法 (開発時)

```bash
cd webgui
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

実機では 80番ポートで `/mgmt/` を提供する (systemd/multiviewer-webgui.service)。

## テスト

```bash
cd webgui
python -m pytest tests/
```
