# MultiViewer

ST2110-20/-30 の受信・4分割合成・WebRTC配信・NMOS制御・WebGUI を備えたモニタリングシステム。

要件定義書（`MultiViewer要件定義書.pdf`、ローカル保管・本リポジトリには含めない）に基づき、
5ステップに分けて段階的に実装する。**本リポジトリの現在の内容はステップ1（WebGUIの表面と
OSネットワーク設定機能）のみ**。NMOS/PTP/映像受信/配信の実処理は未実装。

## ステップ1のスコープ

やったこと:

- WebGUI一式（ダッシュボード／メディアストリーム設定／PTP・NMOS設定／システム設定／ログ）
- 設定を永続化する設定ストア（JSON、後続ステップがそのまま読み書きできる構造）
- **NIC（10G×2・1G×1）のIPアドレス変更機能（OSのnetplan設定を実際に書き換える、本番動作）**
- 上記に必須の安全機構（変更前バックアップ／確認待ちタイムアウト／自動ロールバック）
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
    network_state.py    NIC変更の確認待ち状態機械（/etc/multiviewer/network-state.json）
    nic_ip_change.py    netplan書き換え・バックアップ・ロールバックの実装
    nic_state.py        OSから読み取るNIC状態（読み取り専用）
    routers/            各画面・APIのFastAPIルータ
    templates/, static/ Jinja2テンプレートとCSS/JS
  tests/               pytest
scripts/
  setup.sh                 初回セットアップスクリプト（要root）
  nic_rollback_check.py    ロールバック安全機構のチェックスクリプト（timerから起動）
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

## IPアドレス変更の安全機構（最重要）

前提: 過去の実装でOSネットワーク設定変更の不備によりSSHログイン不能になる事故が発生したため、
今回は以下の設計を必須要件として実装した。

### 設計

1. **ライブ変更をしない**: WebGUIから適用しても、その場で`netplan apply`は呼ばない。
   netplanファイルを書き換えて**再起動を予約**するだけ。新しいIPは起動時に
   systemd-networkd がnetplanを適用して初めて有効になる。動作中のSSH/WebGUIセッションを
   その場で壊すことがない（要件7.5.2「サーバー再起動を前提とする」に対応）。
2. **変更前バックアップ**: 適用前に、対象NICのnetplanファイル（存在しなければ「存在しなかった」
   というマーカー）を `/etc/multiviewer/netplan-backups/<UTCタイムスタンプ>/` にコピーする。
3. **構文検証**: 書き込み後、`netplan generate`（ライブのネットワークに触れないドライラン）で
   検証し、失敗したら即座に元のファイルへ戻し、再起動は予約しない。
4. **確認待ちタイムアウト**: 状態は `/etc/multiviewer/network-state.json` に記録される
   （`stable` → `pending_confirm` → `stable`（確認時）または `rolled_back`（タイムアウト時））。
   デフォルトのタイムアウトは**5分**（`network_state.DEFAULT_TIMEOUT_SECONDS`、画面から変更可）。
5. **自動ロールバック**: `multiviewer-nic-rollback.timer` が20秒ごとに
   `scripts/nic_rollback_check.py` を実行し、`pending_confirm` のままタイムアウトを超えていたら、
   バックアップからnetplanファイルを復元し、`rolled_back` に遷移して再度再起動する。
   このタイマーはWebGUIプロセスの生死に依存しない（WebGUI自体が制御NIC変更で
   到達不能になった場合でも、このタイマーは独立してOS起動時に動く）。
6. **確認操作**: 再起動後、操作者がWebGUI（新しいIPでアクセスできることを含めて確認）から
   「この設定を確定する」を押すと `pending_confirm` → `stable` に遷移し、ロールバックは
   発生しなくなる。バナーはどの画面でも常時表示され、残り時間を表示する。
7. **制御用1GNIC（WebGUI/SSHアクセス）の特別扱い**: `nic_ip_change.HIGH_RISK_TARGETS`
   に指定されており、`confirmed_risk=True` をAPIに渡さない限り変更を拒否する
   （サーバー側で強制、クライアント側のチェックボックスは補助）。画面上にも
   「メディア用10GNICより復旧が難しい」という警告を表示する。

### 動作確認の状況

- **動作確認済み**（`webgui/tests/test_nic_ip_change.py`、`test_network_state.py`
  でロジックをユニットテスト。`netplan`/`shutdown` コマンド不在の開発機でも、それらの
  呼び出しをモックまたはスキップして検証している）:
  - netplanファイルのバックアップ（存在時／不在時の両方）
  - 構文検証失敗時のファイル即時ロールバック
  - `pending_confirm` → `confirm()` → `stable` の遷移
  - タイムアウト経過後の `perform_rollback_if_expired()` によるファイル復元・状態遷移・
    再起動呼び出し
  - 制御NICは `confirmed_risk=True` なしでは拒否されること
  - WebGUI API経由（`/api/network/apply`, `/api/network/confirm`, `/api/network/state`）での
    一連の流れ（`webgui/tests/test_app_routes.py`）

- **未検証（実機での最終検証が必要）**:
  - 実際のUbuntu Server 24.04.4上での `netplan generate`/起動時のnetplan適用の実挙動
  - 実際にNICのIPアドレスを変更し、再起動を経て新しいアドレスでアクセスできること
    （要件9.9.3）
  - `multiviewer-nic-rollback.timer` が実際のsystemd環境で20秒間隔どおりに動作し、
    タイムアウト後に確実にロールバック・再起動を行うこと
  - 制御NIC変更失敗時に、本当にSSHから復旧不能になった場合でもロールバックタイマーが
    機能し、最終的にアクセスを回復できること（物理コンソールでの確認が望ましい）
  - `shutdown -r +1` による再起動タイミングと、WebGUIのHTTPレスポンス返却の競合状態がないこと

### 検証方法について（重要・必読）

**この安全機構自体の動作確認は、まず復旧が容易な環境（VM等、スナップショット/コンソール
アクセスが容易なもの）で行うこと。** 本番相当の物理機でテストする場合は、SSH以外の復旧手段
（物理コンソール、IPMI/BMC、シリアルコンソール等）を必ず確保した状態で行うこと。
制御NIC（1GNIC）の変更は特にリスクが高いため、最初は必ずメディア用10GNICで一連の動作
（適用→再起動→確認 or タイムアウトによるロールバック）を確認してから、制御NICで試すこと。

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

39件のユニット・APIテストで、設定ストア・ログストア・ネットワーク状態機械・
NIC変更ロジック（バックアップ／検証／ロールバック）・WebGUIの各画面とAPIを検証している。
UIのブラウザでの目視確認は `uvicorn app.main:app` をローカルで起動して行った
（Windows開発機のため `ip`/`netplan`/`psutil` 等OS依存機能は自動的にNo-op/N-A表示に
フォールバックする設計）。

## 既知の制約・注意事項

- 要件どおり、WebGUIへのログイン認証は設けていない（LAN内利用前提、要件5.4.1/7.3.2）
- HTTPS化は行っていない（要件8.3.2）
- ログの長期保存基盤は設けず、WebGUI上の表示とダウンロードのみ（要件8.5.1）
- config.json の `nmos_sdp` フィールドは、ステップ2でNMOSからSDPを取得した際に
  格納する想定の空きフィールドとして先行して用意した
