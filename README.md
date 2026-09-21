# MultiViewer

ST2110-20/-30 の受信・4分割合成・WebRTC配信・NMOS制御・WebGUI を備えたモニタリングシステム。

要件定義書（`MultiViewer要件定義書.pdf`、ローカル保管・本リポジトリには含めない）に基づき、
5ステップに分けて段階的に実装する。**本リポジトリの現在の内容はステップ1（WebGUIの表面と
OSネットワーク設定機能）のみ**。NMOS/PTP/映像受信/配信の実処理は未実装。

## ステップ1のスコープ

やったこと:

- WebGUI一式（ダッシュボード／メディアストリーム設定／PTP・NMOS設定／システム設定／ログ）
- 設定を永続化する設定ストア（JSON、後続ステップがそのまま読み書きできる構造）
- **NIC（10G×2・1G×1）のIPアドレス変更機能（OSのnetplan設定を実際に書き換える、本番動作）**。
  適用すると確認ポップアップの後すぐにサーバーを再起動する。自動ロールバックは行わない
  （運用方針の変更について詳細は下記「IPアドレス変更の挙動」を参照）
- ログ収集の仕組み、systemdユニット定義、初回セットアップスクリプト

やらないこと（後続ステップ）:

- NMOS（IS-04/IS-05）実装、PTPクライアント実装
- MTLによるST2110-20/-30受信、ST2022-7冗長マージ
- FFmpegによる4分割合成、MediaMTXによるWebRTC配信
- 上記に対応するWebGUI画面はレイアウトのみ存在し、裏側の実処理には未接続

## ディレクトリ構成

```
webgui/            FastAPI製WebGUI本体
  app/
    config_store.py    設定ストア（/etc/multiviewer/config.json）
    log_store.py        イベントログ（/var/log/multiviewer/events.log）
    nic_ip_change.py    netplan書き換え・即時再起動の実装
    nic_state.py        OSから読み取るNIC状態（読み取り専用）
    routers/            各画面・APIのFastAPIルータ
    templates/, static/ Jinja2テンプレートとCSS/JS
  tests/               pytest
scripts/
  setup.sh                 初回セットアップスクリプト（要root）
systemd/               systemdユニット定義
```

## 設定ストアの構造（後続ステップ向け）

`/etc/multiviewer/config.json`（本番）/ `MULTIVIEWER_CONFIG_DIR` 環境変数で変更可（開発・テスト用）。
スキーマは `webgui/app/config_store.py` の `DEFAULT_CONFIG` を正とする。後続ステップは
`config_store.load_config()` で読み込み、必要な部分（`receivers.video[i]`、`ptp`、`nmos` 等）を
そのまま消費してよい。書き込みは `config_store.save_config(config)`（アトミック書き込み）を使うこと。

トップレベルのキー:

- `receivers.video[0..3]`: 映像Receiver4系統。`enabled`/`payload_id`/`video_format`
  （"sdp"|"59.94i"|"59.94p"）/`color_format`/`amber`・`blue`（`source_ip`/`group_ip`/`port`）/
  `sdp_source`（"manual"|"nmos"）/`nmos_sdp`（NMOS実装後、SDP全体をここに格納する想定の空きフィールド）
- `receivers.audio[0]`: 音声Receiver1系統。`sampling`（"sdp"|"48kHz"）/`packet_time`
  （"sdp"|"1ms"|"0.125ms"）/その他は映像と同様
- `ptp.domain`: PTPドメイン番号
- `nmos`: `rds_discovery`（"static"|"auto"）/`rds_static`（address/port/api_version）/
  `common_port`（channelmapping・connection・events・nodeの共通待受ポート）/
  `source_port_mode`（"auto"|"manual"）/`source_port`
- `network.{control,media_amber,media_blue}`: `interface`/`mode`（"static"|"dhcp"）/
  `address`/`prefix`/`gateway`。**この値はOSへ適用済みとは限らない**（再起動待ちの場合がある）。
  OS側の実際の状態は `nic_state.list_interfaces()` を使うこと。
- `streaming.bitrate_mbps`（10〜50）/`streaming.url_path`（視聴用URL、デフォルト `/monitor01/`）
- `display.mode`（"quad"|"single"）/`display.single_source`（1〜4）

## IPアドレス変更の挙動

**注意（2026-09-21改訂）**: 当初は変更前バックアップ・確認待ちタイムアウト・自動ロールバックの
安全機構を実装していたが、操作者からの明示的な指示により、この安全機構（確認待ち状態機械・
自動ロールバック・関連するsystemdタイマー）は撤去した。以前の設計は本ファイルのgit履歴
（コミット `739b636`）に残っている。

### 現在の設計

1. WebGUIの「システム設定」画面でNICのIP設定を入力し、「適用して再起動」を押すと、
   確認ポップアップが表示される。
2. ポップアップで続行すると、netplanファイルを書き換え、`netplan generate`（ライブの
   ネットワークに触れないドライラン）で構文検証する。検証に失敗した場合は即座に元の
   ファイル内容へ戻し、エラーを表示する（再起動はしない）。
3. 検証に成功したら、**その場ですぐにサーバーを再起動する**（要件7.5.2「サーバー再起動を
   前提とする」に対応。ただし予約や猶予時間は設けていない）。
4. 再起動後、新しい設定はそのまま維持される。**自動的なロールバックは行わない。**
   誤った設定を適用した場合、操作者自身が物理コンソール等から手動で復旧する必要がある。
5. 制御用1GNIC（WebGUI/SSHアクセス）の変更は `nic_ip_change.HIGH_RISK_TARGETS` に
   指定されており、`confirmed_risk=True` をAPIに渡さない限り変更を拒否する
   （サーバー側で強制、クライアント側のチェックボックスは補助）。画面上にも
   「メディア用10GNICより復旧が難しい」という警告を表示する。

### リスクについて（重要・必読）

自動ロールバックがないため、**制御用1GNICの設定を誤ると、SSH/WebGUIともに到達不能になり、
自動的には復旧しない。** 変更前に必ず以下を行うこと。

- 物理コンソール、IPMI/BMC、シリアルコンソール等、SSH以外の復旧手段を確保しておくこと
- 入力したIPアドレス・プレフィックス・ゲートウェイに誤りがないか、適用前に必ず再確認すること
- 可能であれば、まず復旧が容易な環境（VM等）で一連の動作（適用→再起動→アクセス確認）を
  確認してから、本番相当の物理機で行うこと
- 制御NIC（1GNIC）は特にリスクが高いため、最初は必ずメディア用10GNICで動作を確認してから
  試すこと

### 動作確認の状況

- **動作確認済み**（`webgui/tests/test_nic_ip_change.py` でロジックをユニットテスト。
  `netplan`/`reboot` コマンド不在の開発機でも、それらの呼び出しをモックまたはスキップして
  検証している）:
  - netplanファイルの書き込みと即時reboot呼び出し
  - 構文検証失敗時のファイル即時ロールバック（バックアップからではなく、書き込み前の
    内容をメモリ上に保持しておいて書き戻すだけの、同期的なもの）
  - 制御NICは `confirmed_risk=True` なしでは拒否されること
  - WebGUI API経由（`/api/network/apply`）での一連の流れ（`webgui/tests/test_app_routes.py`）

- **未検証（実機での最終検証が必要）**:
  - 実際のUbuntu Server 24.04.4上での `netplan generate`/起動時のnetplan適用の実挙動
  - 実際にNICのIPアドレスを変更し、再起動を経て新しいアドレスでアクセスできること
    （要件9.9.3）
  - `reboot` コマンドの呼び出しタイミングと、WebGUIのHTTPレスポンス返却の競合状態がないこと

## セットアップ

```bash
sudo scripts/setup.sh
```

Ubuntu Server 24.04.4 を対象に、Python仮想環境の作成・依存パッケージインストール・
systemdユニットの配置と有効化を行う。NICのIPアドレスそのものは一切変更しない
（WebGUIから明示的に適用するまで、既存のネットワーク設定はそのまま）。

WebGUI: `http://<1GNIC IPアドレス>/mgmt/`
視聴画面（プレースホルダー）: `http://<1GNIC IPアドレス>/monitor01/`

## テスト

```bash
cd webgui
pip install -r requirements.txt pytest httpx
pytest -q
```

30件のユニット・APIテストで、設定ストア・ログストア・NIC変更ロジック（netplan書き込み・
構文検証失敗時の復元・即時reboot呼び出し）・WebGUIの各画面とAPIを検証している。
UIのブラウザでの目視確認は `uvicorn app.main:app` をローカルで起動して行った
（Windows開発機のため `ip`/`netplan`/`psutil` 等OS依存機能は自動的にNo-op/N-A表示に
フォールバックする設計）。

## 既知の制約・注意事項

- 要件どおり、WebGUIへのログイン認証は設けていない（LAN内利用前提、要件5.4.1/7.3.2）
- HTTPS化は行っていない（要件8.3.2）
- ログの長期保存基盤は設けず、WebGUI上の表示とダウンロードのみ（要件8.5.1）
- config.json の `nmos_sdp` フィールドは、ステップ2でNMOSからSDPを取得した際に
  格納する想定の空きフィールドとして先行して用意した
