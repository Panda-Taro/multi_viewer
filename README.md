# MultiViewer

ST2110-20/-30 の受信・4分割合成・WebRTC配信・NMOS制御・WebGUI を備えたモニタリングシステム。

要件定義書（`MultiViewer要件定義書.pdf`、ローカル保管・本リポジトリには含めない）に基づき、
5ステップに分けて段階的に実装する。**本リポジトリの現在の内容はステップ1（WebGUIの表面と
OSネットワーク設定機能）＋ステップ2a（NMOS IS-04/IS-05、静的登録）＋ステップ2b（NMOSの
mDNS＆DNS-SD自動発見、静的登録との切替）**。
PTP同期/映像・音声の実受信（MTL）/合成・配信（FFmpeg・MediaMTX）は未実装。

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
- **IS-04 Node API（`/x-nmos/node/`）を追加実装**: 当初は「P2Pモードは今回のスコープ外」
  としていたが、実機検証中に他のNMOS対応機器の`/x-nmos/`ルートと比較し、
  channelmapping/connection/events/nodeの4つを揃えるよう要望があったため方針変更した。
  Node API自体はRegistration用に既に組み立てているリソースJSONを読み取り専用で返すだけ
  なので実装コストは小さく、副次的にP2Pモード（要件4.7.1.4）での発見にも対応する
- `/x-nmos/events/`（IS-07）・`/x-nmos/channelmapping/`（IS-08）は**存在確認のみの
  最小スタブ**（要件定義書にはどちらも登場しない、本システムのスコープ外の仕様）。
  他機器と同じ4API構成に揃えるためだけに用意し、実体（イベントソース・チャンネル
  マッピング）は空を返す。詳細は下記「NMOS実装」章参照

## ステップ2bのスコープ（今回・**完了**）

**ゴール: `rds_discovery`="auto"のとき、mDNS＆DNS-SD（`_nmos-register._tcp`）でRDSを
自動発見し、優先度に従って選択・登録・フェイルオーバーできること。**

mDNSは環境依存の不具合が出やすいため、依頼者の指示により3段階に分けて進めた。
**第1段階を実機で確認したところ問題が見つからなかったため（下記「mDNS discovery」章の
実機確認結果を参照）、依頼の条件（「環境固有の問題が見つかった場合は一時停止」）に
従い、その後の段階もそのまま実装した。**

- **第1段階: 発見のみのスパイク実装**。`webgui/app/nmos/mdns_discovery.py`
  （zeroconfライブラリで`_nmos-register._tcp`をブラウズし`DiscoveredRegistry`を返す）と
  `scripts/mdns_discovery_spike.py`。**実機でavahi-daemon不在／systemd-resolved mDNS
  無効の環境を確認の上、実際のnmos-cpp Registryを発見できることを確認済み**
  （この過程で`api_ver`がカンマ区切りリストであることに起因する不具合を発見・修正）
- **第2段階: `registration_client.py`への統合**。`rds_discovery`="auto"のとき、
  mDNS発見→`pri`最小（最高優先）のRDSを選択→登録・ハートビートを行う。ハートビート失敗時
  （またはそのRDSへの登録自体の失敗時）は、そのRDSを次の1回の発見・選択から除外して
  再発見し、次点のRDSへフェイルオーバーする。発見できるRDSが0件の場合はエラー状態を
  報告しつつバックグラウンドで再試行し続け、WebGUI・Connection APIはブロックしない
  （mDNSブラウズはスレッドプール上で実行し、イベントループを塞がない設計）
- **第3段階: WebGUI連携**。「PTP・NMOS設定」画面に登録状態・発見方式・発見できたRDS一覧
  （優先度付き）・選択中のRDSを表示するパネルを追加（5秒ごとポーリング）。ダッシュボードの
  既存NMOS状態表示にも発見方式を追加した。`static`⇔`auto`切替は、登録ループが
  設定を毎周期（ハートビート中は最大5秒間隔）再読込する既存の仕組みにより自動的に
  反映される（追加の実装は不要だった）

やらないこと（後続ステップ）:

- PTPクライアント実装（ステップ3）
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
      node_api.py           IS-04 Node API（自己記述・読み取り専用、P2Pモード用）
      connection_api.py    IS-05 Connection API（Receiver専用）
      events_api.py         IS-07 Events API（存在確認のみの最小スタブ）
      channelmapping_api.py IS-08 Channel Mapping API（存在確認のみの最小スタブ）
      status_store.py      NMOS登録状態をWebGUIプロセスへ橋渡しする状態ファイル
      service.py            NMOSサービスのFastAPIアプリ（Connection API + 登録クライアント常駐）
      mdns_discovery.py     mDNS発見（ステップ2b第1段階。登録フローへは未統合）
  tests/               pytest（mock_rds.pyは結合テスト用の自作モックRDS）
scripts/
  setup.sh                 初回セットアップスクリプト（要root）
  mdns_discovery_spike.py  mDNS発見スパイクスクリプト（実機で手動実行して確認する用）
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

### `/x-nmos/`ルート: channelmapping/connection/events/node の4API構成

要件4.8.4.3.2.2.1が`("channelmapping","connection","events","node")`を1つの共通ポートで
扱うとしている点、および実機検証中に他のNMOS対応機器（放送機器Node）の`/x-nmos/`と
見比べた結果を踏まえ、`GET /x-nmos/`が常にこの4つを返すようにした
（`["channelmapping/", "connection/", "events/", "node/"]`）。ただし実装の中身は
2種類に分かれる:

- **`node/`（`nmos/node_api.py`）: 実体のある読み取り専用IS-04 Node API**。
  Registration用に組み立てているのと同じNode/Device/Receiver×5のリソースJSONを
  `self`/`devices`/`receivers`（および空の`senders`/`sources`/`flows`）として返す。
  当初「P2Pモードは今回のスコープ外」としていたが、既存のリソース組み立てコードを
  再利用するだけで実装コストが低く、副次的に要件4.7.1.4のP2Pモード発見にも対応できる
  ため追加した（方針変更。NOTES.md参照）
- **`events/`（IS-07）・`channelmapping/`（IS-08）: 存在確認のみの最小スタブ
  （`nmos/events_api.py`, `nmos/channelmapping_api.py`）**。要件定義書はIS-07/IS-08に
  一切言及しておらず、本システムのスコープには含まれない。バージョン一覧・空の
  リソースコレクション（`sources`/`flows`/`io`/`map/activations`）を返すのみで、
  実際のイベント配信やチャンネルルーティング機能は無い

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
  - IS-04 Node API（self/devices/receivers/空のsenders・sources・flows）
  - IS-07/IS-08スタブの`/x-nmos/`ルート構成・各バージョン一覧・空コレクション応答

- **実機RDS（nmos-cpp）での検証で判明した不具合と修正（2026-09-21〜22）**:
  実際のRDSへ登録したところ`400 Bad Request`が発生。修正は2回に分かれた:
  1回目: Node clockを`ref_type: "internal"`に修正（PTP未実装のため`"ptp"`は不正。これは
  正しい修正）。同時にNode interfaceの`chassis_id`/`port_id`をコロン区切りに変更したが、
  **これは誤りだった**（依然400）。AMWA公式のIS-04 v1.3 JSON Schemaを直接取得して
  照合した結果、`port_id`はダッシュ区切り（`^([0-9a-f]{2}-){5}[0-9a-f]{2}$`）固定で
  自由形式フォールバックが無いことが判明し、ダッシュ区切りに再修正した（2回目）。
  詳細な経緯はNOTES.md「追記2」参照。**この再修正後、実際のRDSへの再登録成功はまだ
  確認できていない**（ローカル開発機から実機に到達できないため。次回のログ確認が必要）。

- **未検証（実機・実NMOSコントローラでの検証が必要）**:
  - 上記再修正後、実際のRDS（172.17.201.192:3210、nmos-cpp）への登録が成功し、
    Query APIで5リソースが見えることの再確認（最優先）
  - 実機で`http://<制御NIC IP>:<common_port>/x-nmos/`にアクセスし、
    channelmapping/connection/events/nodeの4つが表示されること、`node/v1.3/self`等が
    正しく応答することの確認
  - **実際のAMWA公式nmos-cpp Registry、または市販/OSSのNMOS Registry製品との相互接続**
  - **実際のNMOSコントローラ（Blackmagic Video Hub Automation、Riedel、Lawo等）からの
    IS-05 activate要求の受信・解釈**
  - IS-04リソースJSONの、バージョンごとの公式JSON Schemaに対する厳密な検証
    （NMOS Testing Toolでの合否確認）
  - 複数系統・複数クライアントからの同時アクセス時の`staged`状態の競合・整合性
  - `multiviewer-nmos.service`の実機systemd環境での起動・再起動・ポート競合の確認
  - `nmos.common_port`変更後、NMOSサービスの手動再起動が実際に必要であることの運用上の
    影響（自動追従しない既知の制約）

## mDNS discovery（ステップ2b）

要件④-7-1-2/⑥-3-2-1-4「RDS発見方式: mDNS＆DNS-SD（サービスタイプ
`_nmos-register._tcp`）」に対応する。mDNSは環境依存の不具合が出やすいため、依頼者の
指示で3段階（発見のみ→登録統合→WebGUI連携）に分割して進めた。第1段階を実機で確認して
問題がなかったため、そのまま第2・第3段階まで実装した。

### 第1段階: 発見のみのスパイク実装 -- 実機確認済み（2026-09-22）

対象サーバーでの確認結果:

```
$ systemctl status avahi-daemon
Unit avahi-daemon.service could not be found.        # avahi-daemon未インストール
$ resolvectl mdns
Global: no
Link 2 (eth0): no                                     # systemd-resolvedのmDNSは無効
```

**avahi-daemonが存在せず、systemd-resolvedのmDNSも無効**という、このサーバーにとって
最も衝突リスクの低い状態だった。この状態で`scripts/mdns_discovery_spike.py`を実行し、
LAN上のnmos-cpp Registry（172.17.201.11:3210）を実際に発見できることを確認した:

```
Found 1 registrie(s):
  name='nmos-cpp_registration_172-17-201-11_3210._nmos-register._tcp.local.'
    server='nmos-controller.local.' addresses=['172.17.201.11', 'fe80::...'] port=3210
    priority(pri)=100 txt={'api_proto': 'http', 'api_ver': 'v1.0,v1.1,v1.2,v1.3', 'api_auth': 'false', 'pri': '100'}
    registration_base_url=http://172.17.201.11:3210/x-nmos/registration/v1.3/
```

**このテストで、実装上の不具合を1件発見・修正した**: `api_ver`はTXTレコードに
「カンマ区切りの対応バージョン一覧」（`"v1.0,v1.1,v1.2,v1.3"`）として入っており、
単一バージョン文字列ではなかった。修正前の実装はこの文字列をそのままURLパスへ
埋め込んでおり（`.../registration/v1.0,v1.1,v1.2,v1.3/`）、不正なURLになっていた。
カンマで分割し、対応バージョンの中から`v1.3 > v1.2 > v1.1`の優先順で選択するよう
修正した（`DiscoveredRegistry.supported_api_versions`/`registration_base_url`、
回帰テスト`webgui/tests/test_nmos_mdns_discovery.py`に追加）。

avahi-daemonが有効な環境での競合有無は未確認だが、**このサーバー（本番相当機）では
そもそもavahi-daemonが存在しないため、確認する必要自体がなくなった。**

### 第2段階: 登録フローへの統合（`registration_client.py`）

`config.nmos.rds_discovery`が`"auto"`のとき、既存の登録ループ（`run_forever()`）は
以下のように動く（`"static"`のときの挙動・コードはそのまま変更していない）:

1. `mdns_discovery.discover_registries()`を別スレッド（`asyncio.to_thread`）で実行し、
   イベントループ（Connection API・WebGUIと共有）をブロックしない
2. 見つかったRDSから`mdns_discovery.select_best_registry()`で`pri`最小（最高優先）の
   ものを選び、そのRegistration API URLへ登録・5秒間隔でハートビート（ステップ2aの
   ロジックをそのまま再利用）
3. **フェイルオーバー**: ハートビート失敗（RDS無応答・RDSが本ノードを忘れた404）、
   または登録自体の失敗が起きると、そのRDSの名前を「次の1回の発見・選択でだけ除外する」
   よう記録し、再度mDNS発見をやり直す。除外により次点（2番目に優先度の高い）RDSが
   選ばれる。除外しても他に候補がなければ、同じRDSを再選択する（間欠的な問題からの
   自然な回復を優先）
4. 発見できるRDSが0件の場合は`status_store`に`error`状態と理由を記録し、5秒後に
   再試行し続ける。例外を投げてプロセスを落とすことはない
5. 稼働中に`rds_discovery`を`"auto"`から外す（`"static"`に変更する等）と、
   ハートビートループが最大5秒以内にそれを検知して抜け、`run_forever()`が新しい設定で
   再評価する

### 第3段階: WebGUI連携

「PTP・NMOS設定」画面（`/mgmt/ptp-nmos`）に「NMOS登録・発見状態」パネルを追加した
（`GET /api/nmos/status`を5秒ごとにポーリング）。表示内容: 登録状態
（無効/発見中/登録中/登録済み/エラー）・発見方式・登録先RDS URL・最終ハートビート時刻・
直近のエラー、および`auto`モード時のみ「発見したRDS一覧」（名前・アドレス:ポート・
優先度、選択中のものをLEDで表示）。ダッシュボードの既存NMOS状態表示にも発見方式
（`[auto]`/`[static]`）を追加した。

`static`⇔`auto`の切替が即座に反映されることは、既存の「登録ループが毎周期config.jsonを
再読込する」設計（ステップ2aから存在）だけで自動的に満たされており、追加のコードは
不要だった。

### 実装したもの

- `webgui/app/nmos/mdns_discovery.py`: `discover_registries()`（ブラウズ）、
  `select_best_registry()`（優先度選択、除外リスト対応）
- `webgui/app/nmos/registration_client.py`: `_resolve_static`/`_resolve_auto`/
  `_heartbeat_loop`のフェイルオーバー対応
- `webgui/app/nmos/status_store.py`: `discovery_mode`/`discovered_registries`/
  `selected_registry`フィールドを追加
- `webgui/app/routers/ptp_nmos.py`: `GET /api/nmos/status`
- `webgui/app/templates/ptp_nmos.html` / `static/js/ptp_nmos.js`: 発見状態パネル
- `scripts/mdns_discovery_spike.py`: 第1段階の実機確認に使用（上記の通り確認済み）

### 動作確認の状況

- **動作確認済み**:
  - ユニットテスト（`DiscoveredRegistry`への変換・`priority`パース・
    `registration_base_url`組み立て・`select_best_registry`の優先度選択と除外ロジック。
    実際のzeroconf `ServiceInfo`オブジェクトを使用）
  - **実機・実LANでのmDNS発見（2026-09-22）**: avahi-daemon不在・systemd-resolved
    mDNS無効の環境で、実際のnmos-cpp Registryを`_nmos-register._tcp`経由で発見できた
  - `registration_client.py`の`auto`モード統合ロジック（単一RDSでの発見→登録、
    複数RDS間の優先度選択、ハートビート失敗時のフェイルオーバー、RDSが1件も見つからない
    場合の継続リトライ）をモックhttpxトランスポート＋注入可能な`discover_fn`でユニット
    テスト。WebGUIの`/api/nmos/status`エンドポイントとページ描画
- **未検証（実機での確認が必要）**:
  - **実際に`rds_discovery`を`"auto"`に設定した状態での、実機RDSへの登録成功
    （第1段階のスパイクでは発見のみを確認しており、統合後の登録・ハートビートは
    実機で未確認）**
  - 複数RDSが実際にLAN上に存在する環境での優先度選択・フェイルオーバーの実地確認
    （開発機ではモックによるユニットテストのみ）
  - avahi-daemonが稼働している環境での競合有無（このサーバーでは発生しない設定のため
    優先度は低い）
  - `registration_base_url`は`addresses[0]`を使う。zeroconfの`parsed_addresses()`は
    IPv4を常にIPv6より前に返すことを確認済み（アナウンス順序に関わらず）ので、IPv4/IPv6
    両方が広報されている場合はIPv4が選ばれる設計だが、**IPv4アドレスの広報が無い
    （IPv6のみの）RDS環境での接続性は未検証**（判断根拠はNOTES.md）
  - WebGUIの発見状態パネルを、実際にブラウザで見た目を確認すること（開発機では
    TestClient経由でHTMLの断片一致のみ確認）

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

103件のユニット・API・結合テストで、設定ストア・ログストア・NIC変更ロジック・
WebGUIの各画面とAPI・NMOS（IS-04リソース生成/Registrationクライアント/Node API/
IS-05 Connection API/IS-07・IS-08スタブ/自作モックRDSとの結合テスト/mDNS発見の
パース・優先度選択・フェイルオーバー・`auto`モード統合ロジック）を検証している。
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
