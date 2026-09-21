# MultiViewer

ST2110-20/-30 の受信・4分割合成・WebRTC配信・NMOS制御・WebGUI を備えたモニタリングシステム。

要件定義書（`MultiViewer要件定義書.pdf`、ローカル保管・本リポジトリには含めない）に基づき、
5ステップに分けて段階的に実装する。**本リポジトリの現在の内容はステップ1（WebGUIの表面と
OSネットワーク設定機能）＋ステップ2a（NMOS IS-04/IS-05、静的登録のみ）**。
PTP同期/映像・音声の実受信（MTL）/合成・配信（FFmpeg・MediaMTX）、およびNMOSのmDNS自動発見
（ステップ2b）は未実装。

## ステップ1のスコープ（完了）

- WebGUI一式（ダッシュボード／メディアストリーム設定／PTP・NMOS設定／システム設定／ログ）
- 設定を永続化する設定ストア（JSON、後続ステップがそのまま読み書きできる構造）
- **NIC（10G×2・1G×1）のIPアドレス変更機能（OSのnetplan設定を実際に書き換える、本番動作）**。
  適用すると確認ポップアップの後すぐにサーバーを再起動する。自動ロールバックは行わない
  （運用方針の変更について詳細は下記「IPアドレス変更の挙動」を参照）
- ログ収集の仕組み、systemdユニット定義、初回セットアップスクリプト

## ステップ2aのスコープ（今回・完了）

**ゴール: 外部RDS（NMOS Registry）に、本システムが静的登録方式でNode・Device・
Receiver×5（映像4＋音声1）を登録できること。**

- IS-04リソースモデル（Node/Device/Receiver×5）の実装、Registration APIクライアント
  （静的登録・5秒間隔ハートビート・404時の自動再登録）
- IS-05 Connection API（Receiver専用: constraints/staged/active/transporttype）の実装。
  `activate_immediate`によりSDPパラメータを設定ストアへ反映し、WebGUIにほぼリアルタイムで
  反映表示する（`sdp_source`="nmos"のとき「NMOS」バッジを表示、5秒ごとにポーリング）
- **方針変更: nmos-cppは使わず、WebGUIと同じPython/FastAPIで自前実装**（詳細は下記「要件
  定義書からの逸脱」参照）
- mDNS＆DNS-SD自動発見（`rds_discovery`="auto"）は未実装（ステップ2b）。その間は
  ダッシュボードに「無効」として表示される
- Node API（P2Pモード）は今回のスコープ外

やらないこと（後続ステップ）:

- NMOSのmDNS自動発見（ステップ2b）、PTPクライアント実装（ステップ3）
- MTLによるST2110-20/-30受信、ST2022-7冗長マージ、IGMP Join/Leaveの実処理（ステップ4）
- FFmpegによる4分割合成、MediaMTXによるWebRTC配信（ステップ5）
- 上記に対応するWebGUI画面はレイアウトのみ存在し、裏側の実処理には未接続

## ディレクトリ構成

```
webgui/            FastAPI製WebGUI本体・NMOSサービス本体（同一Pythonパッケージ）
  app/
    config_store.py    設定ストア（/etc/multiviewer/config.json）
    log_store.py        イベントログ（/var/log/multiviewer/events.log）
    nic_ip_change.py    netplan書き換え・即時再起動の実装
    nic_state.py        OSから読み取るNIC状態（読み取り専用）
    routers/            WebGUI各画面・APIのFastAPIルータ
    templates/, static/ Jinja2テンプレートとCSS/JS
    nmos_main.py         NMOSサービスのエントリポイント（uvicorn起動）
    nmos/
      identity.py         Node/Device/Receiverの安定UUID管理
      resources.py         IS-04リソースJSON（Node/Device/Receiver）組み立て
      sdp.py                transport_file（SDP）の簡易パーサー
      registration_client.py  IS-04 Registration APIクライアント（静的登録・ハートビート）
      connection_api.py    IS-05 Connection API（Receiver専用）
      status_store.py      NMOS登録状態をWebGUIプロセスへ橋渡しする状態ファイル
      service.py            NMOSサービスのFastAPIアプリ（Connection API + 登録クライアント常駐）
  tests/               pytest（mock_rds.pyは結合テスト用の自作モックRDS）
scripts/
  setup.sh                 初回セットアップスクリプト（要root）
systemd/               systemdユニット定義（webgui / nmos の2サービス）
```

## 設定ストアの構造（後続ステップ向け）

`/etc/multiviewer/config.json`（本番）/ `MULTIVIEWER_CONFIG_DIR` 環境変数で変更可（開発・テスト用）。
スキーマは `webgui/app/config_store.py` の `DEFAULT_CONFIG` を正とする。後続ステップは
`config_store.load_config()` で読み込み、必要な部分（`receivers.video[i]`、`ptp`、`nmos` 等）を
そのまま消費してよい。書き込みは `config_store.save_config(config)`（アトミック書き込み）を使うこと。

トップレベルのキー:

- `receivers.video[0..3]`: 映像Receiver4系統。`enabled`/`payload_id`/`video_format`
  （"sdp"|"59.94i"|"59.94p"）/`color_format`/`amber`・`blue`（`source_ip`/`group_ip`/`port`）/
  `sdp_source`（"manual"|"nmos"）/`nmos_sdp`（IS-05 activate時、受信したSDP全文。ステップ2aで
  実際に書き込まれるようになった）
- `receivers.audio[0]`: 音声Receiver1系統。`sampling`（"sdp"|"48kHz"）/`packet_time`
  （"sdp"|"1ms"|"0.125ms"）/その他は映像と同様
- `ptp.domain`: PTPドメイン番号
- `nmos`: `rds_discovery`（"static"|"auto"）/`rds_static`（address/port/api_version）/
  `common_port`（channelmapping・connection・events・nodeの共通待受ポート。ステップ2aで
  デフォルトを0から8080に変更した。0のままだとNMOSサービスは起動しない）/
  `source_port_mode`（"auto"|"manual"）/`source_port`
- `identity`（ステップ2aで追加）: `node_id`/`device_id`/`video_receiver_ids`（4件）/
  `audio_receiver_ids`（1件）。初回起動時に `webgui/app/nmos/identity.py` がuuid4で生成し
  永続化するNMOSリソースの安定ID。**このIDは再起動やコード変更をまたいで変わらない**
  （RDS側で別ノードとして重複登録されるのを防ぐため）
- `network.{control,media_amber,media_blue}`: `interface`/`mode`（"static"|"dhcp"）/
  `address`/`prefix`/`gateway`。**この値はOSへ適用済みとは限らない**（再起動待ちの場合がある）。
  OS側の実際の状態は `nic_state.list_interfaces()` を使うこと。
- `streaming.bitrate_mbps`（10〜50）/`streaming.url_path`（視聴用URL、デフォルト `/monitor01/`）
- `display.mode`（"quad"|"single"）/`display.single_source`（1〜4）

## NMOS（IS-04/IS-05）実装（ステップ2a）

### アーキテクチャ: WebGUIとは別プロセス

NMOS機能（IS-04 Registrationクライアント＋IS-05 Connection API）は、WebGUI（port 80,
`/mgmt/`）とは**別のFastAPIアプリ・別のsystemdサービス**（`multiviewer-nmos.service`）として
実装した。要件4.8.4.3.2.2.1「channelmapping/connection/events/nodeは1つの共通ポート」を
満たすには、WebGUIの固定ポート80とは別の、操作者が設定変更できるポートで待ち受ける必要が
あるため。同じ`webgui/app`パッケージ（`config_store`/`log_store`/`nic_state`等）を共有する
ことで、コード全体としては1つのPythonコードベースにまとまっている。

- WebGUIプロセス: `uvicorn app.main:app --port 80`
- NMOSプロセス: `python -m app.nmos_main`（内部で `uvicorn.run(..., port=<nmos.common_port>)`）
  起動時に一度だけ`common_port`を読む。WebGUIでポートを変更した場合は
  `systemctl restart multiviewer-nmos.service` が必要（既知の制約。下記参照）

2つのプロセス間の状態共有は、ステップ1のNIC変更機構と同じ「状態ファイル」パターンを踏襲した:
`webgui/app/nmos/status_store.py` が `/etc/multiviewer/nmos-status.json` にNMOS登録状態
（`registration_status`/`rds_url`/最終ハートビート時刻/直近エラー）を書き、WebGUIの
ダッシュボードAPI（`/api/dashboard/status`）がそれを読んで表示する。

### IS-04 Registration API クライアント（`nmos/registration_client.py`）

- 起動時（および5秒ごとのループ内）に`config.json`の`nmos`セクションを再読込するため、
  WebGUIから`rds_static`やポートを変更しても、NMOSサービスを再起動せず追従する
  （`common_port`自体の変更を除く。上記アーキテクチャ節参照）
- `rds_discovery`が`"static"`以外（つまり`"auto"`＝mDNS）の場合は、ダッシュボードに
  「無効（mDNS自動発見は未実装）」と表示するだけで、実際の登録動作は行わない
- 登録順序: Node → Device → 映像Receiver×4 → 音声Receiver×1（`POST /x-nmos/registration/
  {version}/resource`）。成功後、5秒間隔で`POST .../health/nodes/{node_id}`を送信し続ける
- ハートビートが404（RDSがこのNodeを認識していない＝RDSの再起動等で登録が失われた）を
  返した場合、または通信エラーの場合は、Node/Device/Receiver全件を再登録する
- 対応バージョン: 画面（PTP・NMOS設定）で選択した`rds_static.api_version`（v1.1〜v1.3、
  要件4.7.1.3）をそのままRegistration APIのURLパスに使う。ただし**リソースJSONの形は
  v1.3相当のものを常に送っており、バージョンごとのスキーマ差分（例:
  v1.1にはNode.interfacesが存在しない等）には対応していない**（判断根拠はNOTES.md）

### IS-05 Connection API（`nmos/connection_api.py`）

Receiver専用（本システムはSender機能を持たないため、Senderリソース・APIは実装していない）。

| エンドポイント | メソッド | 内容 |
|---|---|---|
| `/x-nmos/connection/{version}/single/receivers/` | GET | Receiver一覧（5件） |
| `.../receivers/{id}/constraints/` | GET | 制約なし（`[{}, {}]`、2レグ分） |
| `.../receivers/{id}/staged/` | GET/PATCH | ステージング中のパラメータ |
| `.../receivers/{id}/active/` | GET | 現在有効なパラメータ（config.jsonから算出） |
| `.../receivers/{id}/transporttype/` | GET | `"urn:x-nmos:transport:rtp.mcast"` |

対応バージョン: v1.0, v1.1（要件6.3.2.1）。`transport_params`は**2要素の配列固定**
（インデックス0=Amber系、1=Blue系）とし、本システムのST2022-7二重化受信設計に合わせた
（要件6.3.2.3「AmberおよびBlue両方でIGMPv3 Joinを実行する」の受け皿として、この段階では
値を保存するところまで）。

`staged`へのPATCHで`activation.mode == "activate_immediate"`が指定されると、その場で
config.jsonへ反映する（`enabled`＝`master_enable`、`amber`/`blue`＝`transport_params`、
`payload_id`＝SDPまたはtransport_paramsから、`sdp_source`＝"nmos"、`nmos_sdp`＝SDP全文）。
`transport_params`を直接指定する方式と、`transport_file`（SDP全文）を指定する方式の両方に
対応しており、後者は`nmos/sdp.py`の簡易SDPパーサーで`m=`/`c=`/`a=source-filter:`行から
ポート・マルチキャストグループ・ソースIP・ペイロードタイプを抽出する（RFC4566の完全な
実装ではない。判断根拠はNOTES.md）。

**スケジュール起動（`activate_scheduled_absolute`/`_relative`）は未対応（400エラー）**。
`activate_immediate`のみサポートする。

### 結合テストについて

`webgui/tests/mock_rds.py`に、Registration API（`POST resource`, `POST health/nodes/{id}`）と
Query API（`GET /x-nmos/query/{version}/{nodes|devices|receivers}`）の最小限を実装した
**自作のモックRDS**を用意し、`webgui/tests/test_nmos_integration.py`で以下を確認した
（`httpx.ASGITransport`によるプロセス内呼び出し。実ポートは使わない）:

- Node・Device・Receiver×5（映像4＋音声1）がRDSへ登録され、Query APIで正しく見えること
- ハートビートが受理されること
- RDSがNodeを忘れた場合（404）、再登録で復旧できること

**これはAMWA公式のnmos-cpp RegistryでもNMOS Testing Toolでもない**（この実行環境には
インターネット経由でのビルド・取得ができなかったため）。実際の公式実装・実際の
NMOSコントローラとの相互接続は未検証。

### 動作確認の状況

- **動作確認済み**（pytest、下記「テスト」参照）:
  - IS-04リソースJSON生成（Node/Device/Receiver×5、ID安定性）
  - Registration APIクライアントのロジック（登録順序、ハートビート成功/404/エラー、
    `run_forever`ループの設定追従・再登録）
  - IS-05 staged/active/constraints/transporttypeの各エンドポイント、
    `activate_immediate`によるconfig.json反映、SDP直接指定とtransport_file(SDP)指定の両方
  - 自作モックRDSに対する結合テスト（登録・Query API・404後の再登録）
  - WebGUIダッシュボードへのNMOS登録状態表示、メディア設定画面へのNMOSバッジ・ポーリング反映

- **未検証（実機・実NMOSコントローラでの検証が必要）**:
  - **実際のAMWA公式nmos-cpp Registry、または市販/OSSのNMOS Registry製品との相互接続**
  - **実際のNMOSコントローラ（Blackmagic Video Hub Automation、Riedel、Lawo等）からの
    IS-05 activate要求の受信・解釈**
  - IS-04リソースJSONの、バージョンごとの公式JSON Schemaに対する厳密な検証
    （NMOS Testing Toolでの合否確認）
  - 複数系統・複数クライアントからの同時アクセス時の`staged`状態の競合・整合性
  - `multiviewer-nmos.service`の実機systemd環境での起動・再起動・ポート競合の確認
  - `nmos.common_port`変更後、NMOSサービスの手動再起動が実際に必要であることの運用上の
    影響（自動追従しない既知の制約）

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
`multiviewer-webgui.service`と`multiviewer-nmos.service`の配置と有効化を行う。
NICのIPアドレスそのものは一切変更しない（WebGUIから明示的に適用するまで、既存の
ネットワーク設定はそのまま）。

WebGUI: `http://<1GNIC IPアドレス>/mgmt/`
視聴画面（プレースホルダー）: `http://<1GNIC IPアドレス>/monitor01/`
NMOS Connection API: `http://<1GNIC IPアドレス>:<nmos.common_port>/x-nmos/connection/`
（`common_port`はデフォルト8080。WebGUIの「PTP・NMOS設定」画面で変更可能）

## テスト

```bash
cd webgui
pip install -r requirements.txt pytest httpx pytest-asyncio
pytest -q
```

66件のユニット・API・結合テストで、設定ストア・ログストア・NIC変更ロジック・
WebGUIの各画面とAPI・NMOS（IS-04リソース生成/Registrationクライアント/IS-05
Connection API/自作モックRDSとの結合テスト）を検証している。
UIのブラウザでの目視確認は `uvicorn app.main:app` をローカルで起動して行った
（Windows開発機のため `ip`/`netplan`/`psutil` 等OS依存機能は自動的にNo-op/N-A表示に
フォールバックする設計）。

## 既知の制約・注意事項

- 要件どおり、WebGUIへのログイン認証は設けていない（LAN内利用前提、要件5.4.1/7.3.2）
- HTTPS化は行っていない（要件8.3.2）
- ログの長期保存基盤は設けず、WebGUI上の表示とダウンロードのみ（要件8.5.1）
- `nmos.common_port`をWebGUIから変更しても、`multiviewer-nmos.service`は自動的には
  再起動されない（起動時に一度だけ読み込む設計のため）。ポート変更後は手動で
  `sudo systemctl restart multiviewer-nmos.service`が必要
- IS-04のNode API（P2Pモード）は未実装。RDSを介さない直接接続には対応しない
  （ステップ2b以降で必要になれば追加検討）
- NMOSのmDNS＆DNS-SD自動発見（`rds_discovery`="auto"）は未実装（ステップ2b）
