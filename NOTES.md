# 実装メモ（ステップ1・ステップ2a）

要件定義書に明記されていない実装レベルの判断について、判断内容と理由を記録する。

## アーキテクチャ

- **言語・フレームワーク**: Python 3 / FastAPI + Jinja2。要件⑦-2-2の主要ソフトウェアスタック
  （MTL/FFmpeg/MediaMTX/nmos-cpp）と相性がよく、後続ステップでのプロセス間連携（設定ストア共有、
  ログ連携）をシンプルに保てるため。要件⑦-2-3「ハードウェア非依存」とも整合する。
- **設定ストア**: 軽量DBではなく単一JSONファイル（`/etc/multiviewer/config.json`）を採用。
  設定項目数が少なく、後続ステップ（NMOS/PTP等の別プロセス）からも `json.load` だけで読める
  ことを優先した。将来的に書き込み頻度・同時アクセスが増えるようなら再検討が必要。
- **NIC状態の分離**: 「設定した値」（config.json内）と「OSの実際の状態」（`nic_state.py` で
  都度取得）を明確に分離した。要件4.8.4.4.1.1「NICの状態は本システムがOSから取得してGUIに
  反映する」を素直に満たすには、設定値をキャッシュせず毎回OSに問い合わせるのが安全と判断。

## NIC IPアドレス変更の安全機構

- **当初（初回実装時）の設計**: netplanファイルをターゲットごとに分離、変更前バックアップ、
  デフォルト5分の確認待ちタイムアウト、systemdタイマーによる常時稼働の自動ロールバック、
  ライブ適用を避けて再起動ベースにする、という設計にしていた（要件5.4.3「ロールバック手段」
  を字義通り実装したもの）。判断根拠の詳細はgit履歴（コミット `739b636`）のNOTES.md参照。
- **2026-09-21改訂**: 操作者からの明示的な指示により、この安全機構（確認待ち状態機械・
  自動ロールバック・関連するsystemdタイマー、`network_state.py`）を撤去した。
  「設定を変更したらこのままとする」（自動復旧は不要、手動確認ポップアップ後に即座に
  再起動して確定する）という運用方針への変更。要件5.4.3の「確認・ロールバック手段」を
  満たさなくなる変更であることは操作者に確認済み。netplanファイルをターゲットごとに
  分離する設計（制御NICとメディアNICの独立性）自体は維持し、構文検証失敗時の即時ファイル
  復元（ディスク再起動を伴わない、書き込み前の内容をメモリに保持しておく同期的な復元）
  のみ残した。

## WebGUI

- **表示モード切替のプレビュー**: 実際の映像合成・配信が未実装のため、ダッシュボードの
  プレビュー枠は「CH1〜CH4」のラベルのみを表示するプレースホルダーとした。表示モード
  切替のAPI・設定保存自体は実装済みで、後続ステップで実際の映像に差し替えるだけで
  動作する設計。
- **視聴用URL（`/monitor01/`）**: 要件4.6.2の固定パスをデフォルトにしつつ、システム設定
  画面から変更可能にした（要件4.8.4.4.2.2.1）。ただし実際のルーティング切り替え
  （設定したパスで実際にWebRTCを配信する処理）はMediaMTX実装後（ステップ5）に行う。
  ステップ1では `/monitor01/` 固定のプレースホルダー画面のみ存在する。
- **NMOSからの自動反映（要件4.8.4.2.1.3）**: NMOS実装がステップ2以降のため、
  `sdp_source`（"manual"|"nmos"）と `nmos_sdp` フィールドを設定ストアに先行して
  用意した。ステップ2実装時にNMOS側がこのフィールドを書き込み、GUIがポーリングまたは
  プッシュで表示すれば要件を満たせる構造にしてある。

## GitHubリポジトリの扱い

- 「リポジトリの中身を全て削除」という指示について、`git push --force` による履歴の
  書き換えではなく、**通常のコミットで旧ファイルの削除＋新規ファイルの追加を行う**方針を
  取った。理由: 強制pushは共有リポジトリに対して取り返しのつかない操作であり、
  「HEADの内容をクリーンにする」という実質的な目的は通常コミットで十分達成できるため。
  履歴に過去の失敗した実装が残ること自体は実害がないと判断した。

## 要件定義書からの逸脱（ステップ1範囲）

- 特になし。不明点は上記の判断に従い、要件の記載範囲内で合理的な実装レベルの判断を
  行った。要件定義書の記載同士が明確に矛盾する箇所は見つからなかった。

---

# ステップ2a: NMOS（IS-04/IS-05）実装

## 要件定義書からの逸脱: nmos-cppを使わない（③システム構成）

- **指示による明示的な逸脱**: 要件定義書③「NMOS制御層：nmos-cpp」に対し、今回の依頼で
  「nmos-cppは使わず、WebGUIと同じPython/FastAPIスタックでIS-04/IS-05のREST APIを
  自前実装する」という方針変更が明示された。機能要件・外部インターフェース仕様
  （④-7、⑥-3）自体は満たす前提で、ソフトウェアスタックの選定のみを変更したもの。
  理由（指示に基づく）: 設定ストアとの連携の単純化、C++の追加ビルド依存の回避、
  後続ステップ（IS-05⇔MTL連携のNMOSブリッジ）を同一コードベースで書きやすくするため。
- 要件⑤-5-1「使用するソフトウェアスタックはバージョンを明記し管理する」との関係:
  nmos-cppの代わりに何を使っているかを明記する必要があるため、README.mdに
  「NMOS（IS-04/IS-05）実装」章として明記した。

## アーキテクチャ: NMOSを別プロセス・別ポートにした理由

- 要件4.8.4.3.2.2.1は「channelmapping/connection/events/nodeを1つの共通ポート」とし、
  WebGUIの固定ポート80とは別に運用することを前提としている。1つのFastAPIプロセス
  （uvicorn）は1ポートしか自然には待ち受けられないため、選択肢は (a) WebGUIプロセス内で
  2つ目のuvicorn.Serverを非同期タスクとして併走させる、(b) 完全に別プロセス・別systemd
  ユニットにする、の2つだった。(b)を選んだ理由: systemdによる個別の再起動・障害分離が
  素直にでき（要件⑤-5-2「障害発生時の復旧手順を明確にする」とも相性がよい）、
  「同一プロセス内で書きやすくする」という依頼の意図は「同一Pythonパッケージ・
  同一コードベースで書けること」で十分満たせると判断した。
- **既知の制約として残った副作用**: `nmos.common_port`を変更しても、NMOSサービスは
  起動時に一度だけポートを読むため、自動的には追従しない（手動再起動が必要）。
  動的にuvicorn.Serverを再バインドする実装も検討したが、複雑さに見合わないと判断し、
  ステップ1のNIC変更と同様「設定変更は手動での確認的操作を伴う」という運用に寄せた。

## IS-04リソースJSONの簡略化

- AMWA公式のIS-04 JSON Schema（v1.1〜v1.3それぞれ）に対するバイト単位の検証は行って
  いない。バージョンごとのスキーマ差分（例: `interfaces`フィールドはv1.2以降で追加）を
  無視し、常にv1.3相当の形を送信している。理由: この実行環境ではインターネット経由で
  公式スキーマファイル一式を取得できず、また実機のRDS製品でスキーマの厳密さがどこまで
  要求されるか確認する手段もなかったため、「動作する現実的な形」を優先した。
  この点はREADME.mdの「未検証」リストに明記し、NMOS Testing Toolでの検証を今後の
  課題とした。
- Node APIは実装していない（依頼で明示的にスコープ外とされたため）。ただしNode
  リソースの`href`/`api.endpoints`フィールドはIS-04スキーマ上必須のため、実際には
  応答しないNode API相当のURLを自己参照として埋めている（形式的な充足）。

## IS-05 Connection APIの設計判断

- **`transport_params`を2要素固定（Amber/Blue）にした**: 要件6.3.2.3が
  「Amber/Blue両方のNICでIGMPv3 Joinを実行する」としており、本システムのST2022-7
  二重化受信という前提と対応させるため、IS-05の一般的な「1レグ or 冗長2レグ」の
  選択肢のうち、常に2レグ固定とした。単一レグ（非冗長）のSDP/transport_paramsが
  来た場合は、leg1にもleg0の値を複製する形でパースする（`sdp.py`のダブル処理）。
- **`activate_scheduled_absolute`/`_relative`は未対応（400エラー）**: 実際のNMOS
  コントローラがスケジュール起動をどう使うか検証する手段（NMOS Testing Tool等）が
  この環境になく、中途半端な実装を「動く」ことにして出荷するリスクを避けた。
  `activate_immediate`のみサポートし、未対応であることを明示的にエラーで返す設計とした。
- **SDPパーサーは簡易実装**: RFC4566の完全なパーサーではなく、`m=`/`c=`/
  `a=source-filter:`の3種類の行だけを見て、ポート・マルチキャストグループ・
  送信元IP・ペイロードタイプを抽出する。ST2110のSDPで一般的に使われる形式のみを
  対象とし、汎用SDPパーサーの実装コストを避けた。

## 結合テスト: 自作モックRDSを使った理由

- 依頼では「AMWA公式のnmos-cpp Registry（またはNMOS Testing Tool、もしくは簡易な
  モックRDS実装）」のいずれかで結合テストを行うことを求められていた。この実行環境は
  インターネット経由でnmos-cpp（C++、CMakeビルド、複数の外部依存ライブラリ）を
  取得・ビルドする手段がなく、NMOS Testing Tool（Python製だが多数の依存関係と
  設定を要する）も同様の理由で導入しなかった。よって「簡易なモックRDS実装」の
  選択肢を採用し、`webgui/tests/mock_rds.py`にRegistration API・Query APIの
  最小限を自作した。**実際の公式実装との相互接続は必ず実機で確認する必要がある**
  （README.md「実機検証が必要な項目」参照）。

## config_store.pyのデフォルト値変更

- `nmos.common_port`のデフォルトを`0`（ステップ1時点の値）から`8080`に変更した。
  ステップ1時点では「未設定」を表す意図で0にしていたが、ステップ2aでNMOSサービスが
  実際に動くようになったため、初回セットアップ後すぐに動作する現実的なデフォルト値
  （NMOS実装で慣習的に使われることの多い8080番）に変更した。WebGUIから変更可能。

## 要件定義書からの逸脱まとめ（ステップ2a）

- ③システム構成「NMOS制御層：nmos-cpp」→ 自前FastAPI実装に変更（指示による、上記参照）
- それ以外の④-7・⑥-3の機能要件・外部インターフェース仕様は、実機未検証の部分を除き
  満たす実装とした

## 追記: 実機RDSでの動作確認により判明したIS-04スキーマ不備の修正（2026-09-21）

操作者がローカルサーバーで実際のRDS（172.17.201.192:3210）に対して登録を実行したところ、
`POST .../resource`が`400 Bad Request`で継続的に失敗する事象が発生した。原因は「自作
モックRDSでの結合テストは通るが、公式のJSON Schema検証をしていない」という上記の
既知の制約（README.md「未検証」）が実際に顕在化したもので、以下2点を修正した。

- **Node interfaceの`chassis_id`/`port_id`のフォーマット誤り（当初の誤った推測）**:
  最初はコロン区切り（`00:11:22:...`）が正しいと推測して修正したが、これは**誤りだった**。
- **Node clockの`ref_type: "ptp"`宣言が不完全**: IS-04の`clock_ptp`スキーマは
  `ref_type: "ptp"`を指定する場合、`traceable`/`version`/`gmid`/`locked`の
  追加フィールドを要求するが、PTPクライアント未実装（ステップ3）のためこれらの値を
  持っておらず、`ref_type`のみを送っていたためスキーマ検証エラーになっていたと考えられる。
  `ref_type: "internal"`（実態に即した値）に変更した。これは正しい修正だった
  （`clock_internal.json`で`name`パターン`^clk[0-9]+$`・`ref_type`は`"internal"`固定と確認済み）。
- 併せて、Registration APIクライアントのエラーログにRDSからのレスポンスボディ
  （schema検証エラーの詳細を含む）を出力するよう改善した（従来はHTTPステータスコード
  のみで、実際の検証エラー内容が分からなかった）。この改善により、実機での再テストで
  nmos-cppからの実際の検証エラーメッセージ（`"schema validation failed at root -
  no subschema has succeeded..."`）が見えるようになり、下記の再修正につながった。

## 追記2: chassis_id/port_idの修正が誤りだったことが判明・再修正（2026-09-22）

上記の修正をデプロイしても実機RDS（172.17.201.192:3210、nmos-cpp）への登録が
`400 Bad Request`のまま解消しなかった。ログに出力されるようになったRDSの検証エラー
メッセージ自体は`"no subschema has succeeded"`という汎用的なもので原因を特定できな
かったため、AMWA公式のIS-04 v1.3 JSON Schema（`node.json`等）をGitHubから直接取得して
照合した。

結果、**`chassis_id`/`port_id`は実際にはダッシュ区切り
（`^([0-9a-f]{2}-){5}[0-9a-f]{2}$`）が正しい形式であり、当初の実装（ダッシュ区切り）が
正しく、最初の修正（コロン区切りへの変更）が誤りだったことが判明した**。特に`port_id`
は`chassis_id`と異なり自由形式文字列へのフォールバック（`anyOf`でのフリーフォーム
許容）が無く、厳密にこのMACアドレス形式のみを受け付けるため、コロン区切りは確実に
スキーマ検証エラーになる。ダッシュ区切りに戻した（再修正）。

**教訓**: 実装時に一次情報（AMWA公式スキーマ）を確認せず記憶・推測でスキーマ形式を
決め打ちしたことが、誤った修正を生んだ直接の原因。この再修正時は
`https://raw.githubusercontent.com/AMWA-TV/nmos-discovery-registration/v1.3.x/
APIs/schemas/node.json`ほか`resource_core.json`/`device.json`/`receiver.json`/
`receiver_video.json`/`receiver_core.json`/`clock_internal.json`を実際に取得し、
Node/Device/Receiverの各必須フィールド・パターン制約を全て突き合わせて確認した上で
修正している。

- **確認事項（実機未検証）**: この再修正により実機RDSへの登録が成功するはずだが、
  ローカル開発機から実機（172.17.201.192）に直接アクセスできないため、この場では
  未確認。次回のデプロイ後、`/etc/multiviewer/nmos-status.json`の
  `registration_status`が`"registered"`になること、またはWebGUIダッシュボードの
  「NMOS登録状態」表示、あるいはRDS（nmos-cpp）側のQuery APIで本システムのNode・
  Device・Receiver×5が実際に見えることの確認が必要。

## 追記3: `/x-nmos/`の4API構成（node/events/channelmapping）を追加（2026-09-22）

操作者が実機で`http://172.17.201.198:3333/x-nmos/`にアクセスしたところ`connection/`
しか無く、他の放送機器Node（比較用にスクリーンショットで提示）が
`channelmapping/, connection/, events/, node/`の4つを揃えて返していることと異なる、
という指摘を受けた。要件4.8.4.3.2.2.1もこの4つを1つの共通ポートで扱う前提の書き方に
なっているため、方針を変更しこの4つを揃えることにした。

- **IS-04 Node API（`node/`）は実体を実装した**: 当初ステップ2aの依頼文で「Node API
  （P2Pモード）は今回のスコープ外としてよい」と明示されていたが、`resources.py`に
  Registration用のNode/Device/Receiver JSON組み立てが既にあり、それを読み取り専用で
  返すだけなので実装コストがほぼ無かったこと、要件4.7.1.4（RDSが無い環境でのP2P
  モード対応）にも自然に応えられることから、スコープを広げて実装した。
- **IS-07 Events API（`events/`）・IS-08 Channel Mapping API（`channelmapping/`）は
  要件定義書に一切登場しない**（本システムのスコープには本来含まれない）。実装コストと
  実利益のバランスから、フルの仕様準拠（IS-07はWebSocket/MQTTでのpub-sub配信、
  IS-08は入出力チャンネルのルーティング管理）は行わず、バージョン一覧と空の
  リソースコレクションを返すだけの**存在確認のみのスタブ**とした。これらのAPIを
  探索するNMOSコントローラ・監視ツールが「未実装のエンドポイント」として404を
  返されるより、「対応しているが現状何も無い」ことを示す方が、実際の放送機器の
  挙動に近く親切だろうという判断。将来的に音声チャンネルマッピングやイベント
  配信が必要になった場合は、この段階のスタブを本実装に差し替える。
- 要件定義書との関係を明確にするため、この2つのAPIが要件外であることをREADME.mdにも
  明記した。

---

# ステップ2b（第1段階）: mDNS発見

## ライブラリ選定: `zeroconf`（python-zeroconf）を採用

- 候補は主に2つ: (a) `zeroconf`（純Python実装、自前でマルチキャストソケットを開く）、
  (b) `python-avahi` + D-Bus経由でavahi-daemonのブラウズ機能を利用する方式。
- `zeroconf`を選んだ理由:
  - pip一発でインストールでき、システムパッケージ（`python3-avahi`等）やD-Busへの
    依存が無い。`webgui/requirements.txt`にそのまま追加でき、venv内で完結する
  - avahi-daemonが動いていない環境（依頼者の指示どおり、このサーバー専用機では
    無効化する可能性がある）でも単体で動作する。avahi D-Bus方式だとavahi-daemonの
    存在が前提になり、無効化する選択肢と矛盾する
  - Python向けNMOS実装（AMWA公式のリファレンス実装を含む）でも`zeroconf`が
    実質的な標準として使われている実績がある
- リスクとして、`zeroconf`は自前でUDP 5353にバインドするため、avahi-daemon/
  systemd-resolvedのmDNS機能と同時に稼働させた場合にポート競合が起きないか、という
  懸念がある。`zeroconf`は`SO_REUSEADDR`・（プラットフォームが対応していれば）
  `SO_REUSEPORT`を付けてソケットを開く設計になっており、設計上は共存可能なはずだが、
  **これは実際のOS・カーネル挙動に依存するため、この開発環境（Windows）では検証
  できない。** これが「第1段階のスパイク実装を実機で確認するまで統合を進めない」という
  依頼者の指示の核心であり、その通りに従っている。

## 段階分けの徹底

- 依頼の「一度に発見→登録まで作り切ろうとしない」という指示に従い、今回のコミットでは
  `webgui/app/nmos/mdns_discovery.py`（発見・パース・優先度算出）と
  `scripts/mdns_discovery_spike.py`（手動実行用CLI）のみを追加し、
  **`registration_client.py`には一切手を入れていない**。`rds_discovery`="auto"は
  従来通り「未実装（disabled）」のまま。
- 優先度による選択（`pri`が最小のものを選ぶ）・フェイルオーバー・WebGUI表示は、
  依頼で明示された第2段階・第3段階として意図的に実装していない。これはサボりではなく、
  「発見自体が実機で動くかどうか分からない段階で、その上に統合ロジックを積むのは
  手戻りリスクが高い」という依頼者の判断に従ったもの。

## avahi-daemon / systemd-resolvedの無効化判断について

- 依頼で「本サーバーはMultiViewer専用機であり他用途への影響を心配する必要がない」
  ことが明示されているため、実機でのスパイクスクリプト実行結果次第では、
  `avahi-daemon`の停止・無効化（`systemctl disable --now avahi-daemon`）や
  `systemd-resolved`のmDNS機能の無効化（`resolvectl mdns <interface> no`、または
  `/etc/systemd/resolved.conf`の`MulticastDNS=no`）を行う判断はこちらで自由に
  行ってよいとされている。
- **ただし、このコミットの時点では実機での確認結果がまだ無いため、これらの無効化操作は
  一切行っていない。** 次回、依頼者から共有されるスパイクスクリプトの実行結果
  （avahi-daemon/systemd-resolvedの状態、発見できたか否か）を見て、競合が実際に
  確認された場合にのみ、どちらをどう無効化するかを判断し、その内容と理由をここに
  追記する。

## 追記: 実機確認結果と、第2・第3段階への続行判断（2026-09-22）

対象サーバーでの確認結果: `avahi-daemon`ユニット自体が存在しない
（`Unit avahi-daemon.service could not be found`）、かつ`resolvectl mdns`は
Global/eth0とも`no`（systemd-resolvedのmDNSも無効）。**この時点で「avahi-daemonを
無効化するかどうか判断する」という当初想定していた作業自体が不要になった**
（無効化ではなく、そもそも入っていなかった）。この状態で`mdns_discovery_spike.py`を
実行し、実際のnmos-cpp Registry（172.17.201.11:3210）を問題なく発見できた。

依頼の指示は「第1段階（スパイク検証）で環境固有の問題が見つかった場合は、そこで
一度立ち止まり、対処方針を報告してから第2段階に進んでください」というもので、
一時停止は「問題が見つかった場合」の条件付きだった。今回は問題が見つからなかった
（avahi-daemon不在・systemd-resolved mDNS無効という、むしろ最も衝突しにくい状態
だった）ため、依頼の条件に従い、追加の確認を待たずにその場で第2・第3段階まで
実装を続行した。この判断が誤りであれば、差し戻してもらって構わない。

## 第2段階: フェイルオーバーの実装判断

- **「除外は1回の発見試行だけ」という設計にした**: ハートビートに失敗したRDSを
  完全にブラックリストするのではなく、次の1回の`select_best_registry`呼び出しでのみ
  除外する（`registration_client.py`の`exclude_registry_name`は使用後すぐ`None`に
  戻る）。理由: 恒久的なブラックリストだと、一時的なネットワーク不調から回復した
  最優先RDSに二度と戻れなくなる。除外は「今まさに落ちているものを一旦避けて次点へ
  切り替える」ためのものであり、次のサイクルでは再び全候補（元の最優先RDSを含む）
  から選び直すのが、要件の「フェイルオーバー」の趣旨（永続的な降格ではなく、一時的な
  切り替え）に合うと判断した。
- **除外した結果、候補が0件になった場合は除外を無視して全候補から選び直す**
  （`mdns_discovery.select_best_registry`の`exclude_names`パラメータの仕様）。
  唯一発見できているRDSが不安定でも、登録を試み続ける方が「登録先が無い」より
  望ましいと判断した。
- **登録自体の失敗（`register_all`の例外）もハートビート失敗と同様に除外対象とした**:
  依頼文の「ハートビート失敗等」の「等」を、初回登録の失敗も含むと解釈した。

## `registration_base_url`のアドレス選択順序について

- `DiscoveredRegistry.addresses`は`zeroconf`の`ServiceInfo.parsed_addresses()`が
  返す順序をそのまま使い、`addresses[0]`を採用している。ローカルで検証したところ、
  `parsed_addresses()`はアナウンス時のアドレス順序に関わらず**常にIPv4をIPv6より前に
  返す**ことを確認した（`IPVersion.All`のデフォルト動作）。実機での発見結果
  （`addresses=['172.17.201.11', 'fe80::...']`）もこれと一致する。よって
  IPv4/IPv6両方を広報するRDSに対しては意図通りIPv4が選ばれるが、**IPv4を広報しない
  （IPv6のみの）RDS環境は未検証**（この要件定義書のシステムがIPv4前提の設計である
  ため、優先度は低いと判断し深追いしなかった）。

---

# ステップ2d: `staged`キャッシュ不整合バグの修正

## バグの内容（依頼のコードレビューで指摘）

`webgui/app/nmos/connection_api.py`の`_staged`（Receiverごとの`staged`リソースの
インメモリキャッシュ）は`_get_or_init_staged()`で初回アクセス時のみconfig.jsonから
初期化され、以後はプロセス終了までメモリ上の値を使い続ける設計だった。一方、
`webgui/app/routers/media.py`のWebGUI手動保存API（`PUT /api/media/video/{index}`・
`/audio/{index}`）はconfig.jsonのみを更新し、`_staged`キャッシュには一切反映
していなかった。

このため「NMOSがactivate → オペレーターがWebGUIで手動変更 → NMOSコントローラが
値を変えずに`activation: activate_immediate`だけを再送信（フィールドを省略した
再同期パターン）」という現実的なシーケンスで、`_activate()`が古いキャッシュの
`master_enable`等を使ってconfig.jsonを上書きし、**オペレーターの手動変更が本人の
知らないところで取り消される**バグがあった。

## 採用した設計: ターゲット無効化（キャッシュ invalidation）

依頼で提示された2方針（(1) 特定Receiverのstagedキャッシュだけを無効化する関数を
追加、(2) stagedをconfig.jsonからの都度マージ方式に再設計）のうち、**(1)の
ターゲット無効化を採用した**。理由:

- IS-05のstaged/activeの意味論（stagedはコントローラの「未確定の編集途中」を
  保持するためのバッファであり、activeと常に同期している必要はない）を壊さずに
  済む。(2)の「未PATCHフィールドは都度config.jsonから補完する」設計は、
  「どのフィールドがコントローラによって明示的にPATCH済みで、どれがまだ未編集か」
  を継続的に追跡する必要があり、実装・テストのコストに見合う追加の正しさを
  今回のバグには必要としなかった
- 依頼文が挙げていた実装例（「特定のreceiver_idのstagedキャッシュだけを破棄する
  関数」）をそのまま採用すれば、要求されているゴール（「config.jsonの`enabled`・
  エンドポイント値が常にsource of truthである」）を過不足なく満たせると判断した
- config.jsonの受信機設定を書き込むのは現状`media.py`（WebGUI手動保存）と
  `connection_api.py`の`_activate()`自身（NMOS経由、これは自分のキャッシュと
  一貫性があるため無効化不要）の2箇所のみであり、無効化を呼ぶべき箇所を
  取りこぼすリスクは低いと判断した（将来MTLブリッジ等が新たにconfig.jsonの
  受信機設定を書き込むようになった場合は、そこにも同様の呼び出しが必要になる。
  `connection_api.py`のモジュールdocstringにこの注意点を明記した）

## 実装

- `connection_api.py`に`invalidate_staged(receiver_id)`（低レベル、1件だけ破棄）と
  `invalidate_staged_for(kind, index)`（`media.py`が持っているreceiverの位置情報から
  IDを解決して呼び出す便利関数）を追加。既存の`reset_staged_cache()`（全件クリア、
  テスト用）とは別物とし、他のReceiverの正当な編集中stagedを巻き込まないようにした
- `media.py`の2つの手動保存エンドポイントで、`config_store.save_config()`成功後に
  対応する`invalidate_staged_for()`を呼ぶよう変更

## 副次的な判断: NMOSの未確定編集より手動保存を優先する

もしNMOSコントローラがReceiverのstagedを編集中（PATCHしたがまだactivateしていない）
の最中に、オペレーターが同じReceiverをWebGUIから手動保存した場合、この修正により
その未確定の編集はキャッシュごと破棄される（次回のGET/PATCH staged は手動保存後の
config.jsonから再初期化される）。恒久化されていない、コントローラ側のin-flightな
編集より、物理コンソールでの人間による明示的な操作を優先する方が安全だと判断し、
意図的な挙動とした。

## 回帰テストの検証方法

追加した回帰テスト（`webgui/tests/test_nmos_media_staged_sync.py`）が実際にこの
バグを検出できることを、修正コードを一時的に無効化して確認した
（`media.py`の`invalidate_staged_for`呼び出しをコメントアウトして再実行したところ、
5件中4件が実際に失敗することを確認し、その後修正を元に戻した）。単に「テストが
通る」だけでなく、「テストが正しくこのバグを再現・検出できる」ことまで検証済み。

---

# ステップ2e: IS-05 PATCH /stagedが307になり実機NMOSコントローラから失敗するバグの修正

## バグの内容（実機の別NMOSコントローラのログから発覚）

実際のNMOSコントローラから本システムへIS-05のactivate（Join指示）を出したところ
失敗した。コントローラ側のログには`PATCH .../staged - 307 Temporary Redirect`と
記録されていたが、**本システム側にはエラーログが一切残らず、config.jsonも
変化しなかった**。

## 原因

`connection_api.py`のIS-05エンドポイント（`staged`/`active`/`constraints`/
`transporttype`、および`single`/`single/receivers`/`single/receivers/{id}`）を
すべて**末尾スラッシュ付き**（例: `.../staged/`）でFastAPIに登録していた。

しかしAMWA公式のIS-05 RAML定義（`nmos-device-connection-management`
`ConnectionAPI.raml`、GitHub上で実際に取得して確認）では、これらの末端リソースの
正規URLに末尾スラッシュは**付かない**（例: 409応答の`Location`ヘッダー例が
`.../staged`であり`.../staged/`ではない）。実機のNMOSコントローラは仕様通り
末尾スラッシュ無しでPATCHしてきており、これに対しFastAPI/Starletteのデフォルト
挙動（`redirect_slashes=True`）が307を返していた。多くのHTTPクライアント
（特にPATCHのような非冪等メソッド）は307を自動的に追従しないため、コントローラ側は
失敗として扱っていた。

「本システム側にログが残らない」理由: Starletteの末尾スラッシュ・リダイレクト処理は
ルーティングの段階で完結し、実際のハンドラ関数（`patch_staged()`等、
`log_store.log_event()`の呼び出しがある場所）には一切到達しない。そのため
本システムからは何も異常が見えなかった。

自分でこの実装をした際、JSONレスポンスのボディ内に返す「ディレクトリ一覧」の
文字列（例: `["staged/", "active/"]`）と、そのリソース自体を取得するための
URLパスを混同していたことが根本原因（ボディの文字列は正しく末尾スラッシュ付きで
問題ない。混同していたのはURLパスの方）。

## 修正

`connection_api.py`・`node_api.py`・`channelmapping_api.py`の該当ルートを、
**末尾スラッシュあり・なしの両方で登録**するよう修正した（`@router.get(...)`を
2つ重ねて同じハンドラにマッピング）。片方だけを正規化して他方をリダイレクトに
任せる方式ではなく両対応にしたのは、PATCHのような非冪等メソッドでリダイレクトに
依存するのが根本的に脆弱（多くのクライアントが追従しない）と判断したため。
`events_api.py`は元々すでに両対応で実装していたため変更不要だった。

`/x-nmos/connection/`・`/x-nmos/connection/{version}/`（と各APIの相当する
バージョン一覧・ルート）は、RAML上でも実際に末尾スラッシュ付きの正規URLだった
（ディレクトリ一覧を返す「一覧の一覧」的な位置づけのリソースのため）ため変更していない。

## 検証

`fastapi.testclient.TestClient`で実際に、末尾スラッシュ付きのみ登録したルートに
対し末尾スラッシュ無しでPATCHすると`307 Temporary Redirect`が返ることを再現して
から修正した（`follow_redirects=False`で直接確認）。修正後は同じリクエストが
`307`を経由せず直接`200`を返すことを、新規回帰テスト
（`test_nmos_connection_api.py::TestNoTrailingSlashUrls`、
`test_nmos_node_api.py`・`test_nmos_stub_apis.py`の追加ケース）で確認した。

---

# ステップ2f: NMOS activate時にフォーマット表示が「SDP」にならない不具合の修正

## 確認手順（コード修正前に依頼された調査）

依頼「NMOSコントローラーから制御した場合、映像・音声のフォーマット表示は
GUI上で「SDP」になるべきでは」という質問に対し、コード修正を行わず現状を
まず調査した。`connection_api.py`の`_activate()`を読んだ結果、
`enabled`・`amber`/`blue`エンドポイント・`payload_id`（SDPに含まれていれば）・
`sdp_source`・`nmos_sdp`は更新するが、**`video_format`（映像）・
`sampling`/`packet_time`（音声）はどこにも更新していない**ことを確認した。

実際に（コード変更なしで）`TestClient`から本物のPATCH（`transport_file`に
実SDPを含む）を送って検証: activate前後で`video_format`は`59.94i`のまま
変化せず、音声側も手動で`48kHz`等に固定していた場合その値が残り続けることを
再現した。`config_store.py`の`video_format`フィールドには当初から
`# "sdp" | "59.94i" | "59.94p" -- when "sdp", the value from NMOS SDP is used`
というコメントがあり、この値自体を`"sdp"`にする設計意図がステップ2a実装時に
未実装のまま抜け落ちていたことが根本原因と判断した。

## 期待値の確認

上記調査結果を報告した上で、依頼者に期待値を確認した:
1. 外部NMOSコントローラーから制御された場合、映像・音声とも表示が「SDP」になり、
   ペイロードIDはSDPから取得した数値が即時反映される
2. 本システムで手動変更した場合は、「保存」ボタンを押した時点でのみバックエンドが
   更新され、WebGUIもその値になる。保存を押さない限りバックエンドは変化しない

2は既存の実装（`media.py`のPUTエンドポイントは明示的な呼び出し時のみ動作し、
`sdp_source`を無条件に`"manual"`にする）で既に満たされていたため変更不要。
1のみ修正が必要と判断し、期待値の確認が取れたことを受けて実装した。

## 修正

`connection_api.py`の`_activate()`の末尾で、`sdp_source`を`"nmos"`に設定する
のと同じタイミングで、映像Receiverなら`video_format`を、音声Receiverなら
`sampling`・`packet_time`を無条件で`"sdp"`にセットするよう追加した。

- **`sdp_source`と同じトリガーに紐付けた**理由: 依頼の2つの期待値
  （NMOS制御時は問答無用でSDP表示、手動保存時のみ手動値が反映される）を素直に
  読むと、「フォーマット表示が"SDP"かどうか」は実質的に「`sdp_source`が
  `"nmos"`かどうか」と同じ意味であるべきと判断した。activateがSDPファイル
  （`transport_file`）経由か直接の`transport_params`指定かは区別せず、
  いずれの場合もactivateが起きた時点で`"sdp"`にする（`transport_params`のみの
  activateでも、そのReceiverは「もはや手動固定値ではなくNMOSが指定した値で
  動いている」ことに変わりはないため）
- ペイロードIDについては、既存の実装（SDPから`payload_type`が取得できた場合のみ
  上書き）で既に要件を満たしていたため変更していない

## 検証

修正前の状態を一時的に再現（該当コードを一時的にコメントアウト）した上で
新規回帰テストを実行し、5件が実際に失敗することを確認してから修正を復元した。
追加したテスト:
- `test_nmos_activate_forces_sdp_display_even_if_previously_fixed_manually`
  （映像、事前に`59.94p`固定していてもactivate後は`"sdp"`になる）
- `test_nmos_activate_forces_sdp_display_for_audio_even_if_previously_fixed`
  （音声、事前に`48kHz`/`0.125ms`固定していても`"sdp"`になる）
- `test_nmos_then_manual_save_round_trip_video`（NMOS activate→SDP表示→
  手動保存→手動値に戻り`sdp_source`も`"manual"`に戻ることをエンドツーエンドで確認）
- 既存の`test_patch_staged_with_activate_immediate_applies_to_config`・
  `test_patch_staged_with_transport_file_parses_sdp_and_activates`にも
  `video_format == "sdp"`のアサーションを追加

---

# ステップ2g: video_format等の「SDP」選択肢を廃止し、常に実値を表示するよう変更

## 依頼内容

ステップ2fで「NMOS制御時はフォーマット表示を"SDP"にする」という実装をしたところ、
依頼者から方針変更の依頼があった。「SDP」という選択肢自体を廃止し、常に具体的な
数値（59.94i/59.94p、48kHz、1ms/0.125ms）を表示するようにし、NMOSがIS-05で
制御した際は**実際にSDPが示す値**でリアルタイムに更新してほしい、という内容
（対象: 音声のサンプリング・パケット間隔、映像4系統全ての映像フォーマット）。

これは要件定義書④-8-4-2-1-1.1/2.1が定めるオリジナルの選択肢定義
（「SDP or 59i or 59p」「SDP or 48kHz」「SDP or 1ms or 0.125ms」）からの
明確な逸脱（依頼者の指示による）。

## 実装

### SDPパーサーの拡張（`nmos/sdp.py`）

従来はport/payload_type/group_ip/source_ipのみ抽出していたが、以下を追加した:
- `a=ptime:<value>` 行から`packet_time_ms`（音声のパケット化間隔、ミリ秒）
- `a=fmtp:<pt> ...` 行に`interlace`キーワードが含まれるか否かから`interlaced`
  （RFC4175準拠。映像のfmtpパラメータに`interlace`キーワードがあればインター
  レース、無ければプログレッシブという判定方法。走査線数や正確なフレームレート
  までは今回パースしていない＝本システムの`video_format`フィールドが元々
  「59.94i/59.94p」の2値しか持たない設計だったため、それに合わせた最小限の
  拡張にとどめた）

### 概念値の解決ロジック（`connection_api.py`）

`_resolve_video_format()`/`_resolve_packet_time()`という2つのヘルパーを追加。
方針:
1. SDP（`transport_file`）に実際の値（interlace有無／ptime）が含まれていれば、
   それを使って`59.94i`/`59.94p`・`1ms`/`0.125ms`を決定する
2. SDPに情報が無い場合（`transport_params`のみの直接指定でactivateされた場合）は、
   既存の値がすでに正規の選択肢（"59.94i"/"59.94p"、"1ms"/"0.125ms"）であれば
   **変更しない**。旧仕様の`"sdp"`のような不正な値が残っていた場合のみ、
   要件のデフォルト値（映像は6.1.1の"59.94i"、音声は6.2.4の"1ms"）に補正する
- サンプリングは、この機能範囲では48kHz以外の値を実質サポートしていない
  （設定項目としても元々"SDP"と"48kHz"の2択のみだった）ため、SDPパース結果を
  見るまでもなく常に`"48kHz"`で確定させることにした。将来的に他サンプル
  レートへの対応が必要になった場合は、`a=rtpmap`のクロックレートを解析する
  形で拡張できる（今回はスコープ外と判断）

### 設定ストア・バリデーションの変更

- `config_store.py`のデフォルト値: 映像`video_format`は元々"59.94i"のままで
  問題なし。音声の`sampling`のデフォルトを`"sdp"`→`"48kHz"`、`packet_time`の
  デフォルトを`"sdp"`→`"1ms"`（要件6.2.4のデフォルト値）に変更
- `media.py`のPydanticバリデーション選択肢（`VIDEO_FORMAT_CHOICES`/
  `AUDIO_SAMPLING_CHOICES`/`AUDIO_PACKET_TIME_CHOICES`）から`"sdp"`を削除。
  手動保存APIも含めて`"sdp"`という値そのものを受け付けなくした
- `media.html`の3つの`<select>`（映像フォーマット×4系統、サンプリング、
  パケット間隔）から`<option value="sdp">SDP</option>`を削除。映像は
  Jinja2のfor-loop内の1箇所を直接修正するだけで4系統全てに反映される構造
  だった（テンプレートが4つ複製されているわけではないため）

## 既存の設定（config.json）にすでに`"sdp"`が保存されているケースについて

ステップ2f実装後、実機で一度でもNMOS activateを経由したReceiverは
`video_format`/`sampling`/`packet_time`が`"sdp"`という文字列で保存されている
可能性がある。この値は`connection_api.py`の解決ロジックにより次回のactivate時に
自動的に正規値へ補正される（SDPに情報があればそれを使い、無ければデフォルトへ
補正）が、**一度もactivateされないまま放置された場合、WebGUIの`<select>`要素は
どの`<option>`にも一致せず、ブラウザ依存の見た目（多くの場合先頭の選択肢が
無選択のまま表示される等）になる**。マイグレーション処理は用意していない
（実運用中にこの中間状態のまま長期間置かれる可能性は低いと判断したため）。
実機で該当Receiverがあれば、一度手動保存するか、NMOSから再activateすることで
正規値に修正される。

## 検証

pytest 131件、全件パス確認済み。ステップ2fで追加したテストのうち、新方針と
矛盾するもの（「NMOS制御時は問答無用で"sdp"になる」ことを検証していたテスト）を
実際の新仕様に合わせて書き換え、加えて「SDPに実データがある場合は実値へ更新」
「SDPに情報が無い場合は既存の正規値を維持」の両方を検証する新規テストを追加した。

---

# ステップ2h: subscriptionの動的化・RDSへの再登録（他システムのNMOSコントローラに変更が反映されない不具合）

## 依頼内容と事前調査

依頼者から「本システムで手動でReceiverの内容を変更しても、他システムのNMOS
コントローラのGUI上表示が更新されない。他の物理筐体では自動的に更新される」との
報告があった。コード修正前にまず原因調査を実施し、以下2点を特定・報告した。

## 原因1: IS-04で登録するReceiverリソースの`subscription`が常に固定値

`nmos/resources.py`の`_receiver_common()`が
`"subscription": {"sender_id": None, "active": False}`を無条件に返しており、
`config`（実際のReceiver設定）を一切参照していなかった。RECEIVERが有効化されても、
RDSに登録されているこの値自体は永久に変化しない。

## 原因2: 初回登録後、RDSへの再登録（再POST）が一切行われない

`nmos/registration_client.py`の`register_all()`（Node/Device/Receiverの内容を
RDSへPOSTする処理）は、セッション開始時（初回登録・ハートビート失敗後の再接続時）
のみ呼ばれる設計だった。通常運用中（ハートビートが継続している間）は
`send_heartbeat()`（リソースデータを含まない「生存確認」のみのPOST）しか
送っておらず、config.jsonがどれだけ変化しても、その差分がRDSへ一切通知
されなかった。一般的なNMOS対応機器は状態変化のたびに自発的に再登録する
（イベント駆動）が、本システムにはこの仕組みが無かった。

## 修正

### 原因1の修正: `subscription`の動的化

- `config_store.py`のReceiverスキーマに`sender_id`フィールドを追加（デフォルト
  `None`）。IS-05でコントローラが`staged`にセットした`sender_id`を
  `connection_api.py`の`_activate()`で永続化するようにした
  （`receiver_cfg["sender_id"] = staged.get("sender_id")`）
- `connection_api.py`の`_active_from_config()`も、IS-05の`active.sender_id`を
  ハードコードの`None`ではなくconfig.jsonの`sender_id`から読むよう修正
  （IS-05のGET activeも実は同じ「常にNone」バグを抱えていた）
- `resources.py`の`_receiver_common()`に`receiver_cfg`を渡すよう変更し、
  `subscription`を`{"sender_id": receiver_cfg.get("sender_id"), "active":
  bool(receiver_cfg.get("enabled"))}`と実際の状態から動的に構築するよう修正
- 副次的な修正: `media.py`の手動保存時に`nmos_sdp`・`sender_id`を`None`へ
  クリアするようにした。手動保存は以前のNMOS制御内容を完全に上書きする操作
  であり、これらのフィールドを残したままだと、手動再設定後もRDS上の
  `subscription.sender_id`が古いSenderを指し続けてしまい、今回の修正の意味が
  半減するため（手動保存時のこの2フィールドのクリアは、依頼になかったが今回の
  修正と一体で必要と判断し追加した）

### 原因2の修正: 変更検知による再登録

`registration_client.py`の`_heartbeat_loop()`に、ハートビート送信の直前に
「前回登録時のconfig.jsonと現在のconfig.jsonを比較し、異なっていれば
`register_all()`を再実行する」ロジックを追加した。

- **比較粒度はconfig.json全体とした**（Receiver関連フィールドだけを厳密に
  抽出して比較する、といった細かい差分検出は行わない）。理由:
  実装がシンプルで確実（「関連フィールドの選定漏れ」というバグを生みにくい）。
  NIC設定やPTPドメイン等、NMOSリソースの内容に影響しない変更でも再登録が
  走ってしまうが、操作者による変更は高頻度ではなく、余分な再登録の
  コスト（RDSへの数回の追加POST）は無視できると判断した
- 再登録は「ハートビートに失敗した場合の再接続」とは別物として扱い、
  ハートビートセッション自体は継続したまま（`auto`モードの再発見や
  フェイルオーバーを伴わずに）差分だけをRDSへ反映する設計にした
- 実装中に別のバグを発見: `run_forever()`で`config`を`identity`解決前に
  読み込んでいたため、初回起動時（identityのUUIDが未生成の状態）は
  `identity_module.load_identity()`がconfig.jsonへUUIDを書き込んだ直後に、
  既に読み込み済みの古い`config`オブジェクトとディスク上の内容が食い違う
  状態になっていた。今回の「config全体を比較する」変更でこの食い違いが
  表面化し、初回ハートビート時に不要な再登録が走ってしまうテスト失敗を
  引き起こした。`identity`解決後に`config`を再読込するよう順序を修正して解消

## 検証

修正前の状態を一時的に再現（該当ロジックをコメントアウト）し、新規回帰テスト
`test_run_forever_reregisters_when_config_changes_mid_session`が実際に失敗
（設定変更後もRDSへの再登録が発生しないこと＝register呼び出しが7回のまま
14回に増えないこと）を確認してから修正を復元した。

pytest 136件、全件パス確認済み。追加したテスト:
- `resources.py`の`subscription`が実際のenabled/sender_idを反映することを
  検証する2件
- IS-05 activateで`sender_id`が永続化され、IS-04リソース・IS-05 activeの
  両方に反映されることを検証する1件
- 手動保存が`nmos_sdp`/`sender_id`をクリアすることを検証する1件
- ハートビート継続中の設定変更が検知され、RDSへの再登録が実際に走ることを
  検証する1件（上記の通り、修正無効化での失敗を確認済み）

# ステップ2i: config.jsonのクロスプロセス排他

## 背景

ステップ2のコードレビューで、以前ステップ2cで依頼されていた「config.jsonの
クロスプロセス排他」が未実装のまま残っていることが判明した。`config_store.py`の
ロックは`threading.Lock()`のみで、プロセス内でしか効かない。しかしconfig.jsonへの
書き込みはWebGUIプロセス（multiviewer-webgui.service）とNMOSプロセス
（multiviewer-nmos.service）という2つの独立したsystemdサービスから行われており、
いずれも「`load_config()` → dictを変更 → `save_config()`」というread-modify-write。
2プロセスがこれを同時に行うと、後から書いた側が相手の変更を丸ごと巻き戻す
（lost update）。ステップ2dで修正した`staged`キャッシュ不整合と同じクラスの
問題が、ファイルレベルで残っていた。ステップ4でMTLブリッジが3つ目の書き手として
加わる前に固める必要があった。

## 採用したロック方式

`fcntl.flock`を素のosモジュールで直接呼ぶのではなく、`filelock`パッケージ
（PyPI、`FileLock`クラス）を採用した。理由:

- クロスプラットフォーム: Linux（本番のsystemdサービス）では内部的にflockを
  使い、Windows（開発機でのテスト実行）ではmsvcrtベースのロックを使う。
  `fcntl`を直接importするとWindows上で単体テストが一切実行できなくなる。
- `filelock.Timeout`が`TimeoutError`（ひいては`OSError`）のサブクラスである
  ことを実機で確認済み（`Timeout.__mro__`）。既存コードは保存失敗を
  `except OSError`で捕捉して要件4.8.3.1（保存失敗時はエラー表示＋直前の値を
  維持）を満たしていたため、ロックタイムアウトも同じ例外ハンドラで
  自動的に処理される。
- スレッドセーフかつ同一スレッドからの再入（reentrant acquisition）に
  対応していることを確認済み（後述の`locked_config_optional_write`で
  必須の性質）。

ロックファイルは`config.json`自体ではなく専用ファイル
（`/etc/multiviewer/config.lock`）にした。`save_config()`の書き込みは
一時ファイル＋`os.replace()`によるアトミックな差し替えで、これは
config.jsonのinodeを毎回入れ替える。config.json自体をinode単位でロック
すると、replace後にロックが古いinodeに対してのままになり意味を失う
（新しいinodeを開いた別プロセスは別のロックとして扱われてしまう）。
専用の、決して置き換えられないロックファイルを別に用意することでこれを回避した。

読み込み専用の`load_config()`も同じロックを取るようにした（要求は
「共有ロックで構いません」だったが、`filelock.FileLock`は排他ロックのみを
提供するAPIのため、共有/排他を作り分けず単一の排他ロッククラスに統一した。
本システムの設定読み書き頻度は極めて低く、読み取り同士が直列化されても
実用上の問題にならないと判断）。

ロック取得のタイムアウトは5秒（`LOCK_TIMEOUT_SECONDS`）。設定の保存自体は
ミリ秒オーダーで終わるはずなので、通常のリトライには十分な猶予がありつつ、
ロック保持側がハングした場合に呼び出し元を無期限にブロックしない値とした。
タイムアウト時は`log_store`にエラーを記録した上で`filelock.Timeout`
（=`OSError`）を再送出する。

## `locked_config()`と9か所の書き込み統一

「読み込み→変更→保存」をひとつのコンテキストマネージャに統一:

```python
with config_store.locked_config() as config:
    config["ptp"]["domain"] = 1
```

ブロックの開始でロックを取得しconfig.jsonを読み込み、正常終了時に
自動的に書き戻す（例外発生時は何も書き込まず、ロックのみ解放する）。
依頼で列挙された9か所すべてをこれに移行した:
WebGUI側7か所（`dashboard.py`のdisplay更新、`media.py`の映像/音声Receiver
更新×2、`network.py`のNIC適用/配信設定更新×2、`ptp_nmos.py`のPTP/NMOS
設定更新×2）、NMOS側2か所（`connection_api.py`の`_activate()`、
`identity.py`のidentity解決）。

## `identity.py`の設計変更（9か所のうち最もアーキテクチャが異なる箇所）

他の8か所は「毎回必ず変更して保存する」パターンだが、`identity.py`の
`ensure_identity()`は「まだ無いUUIDだけ埋めて保存、既にあれば何もしない」
という条件付き書き込みで、かつ`load_identity()`は`connection_api.py`の
IS-05リクエストや`node_api.py`のIS-04リクエストのたびに（つまり高頻度に）
呼ばれる。これに単純に`locked_config()`（無条件に書き戻す）を使うと、
実質的にすべてのIS-05/IS-04リクエストがconfig.jsonの全体アトミック
再書き込みを引き起こし、無駄なディスクI/Oとロック競合を増やすことになる。

このため`config_store.py`に`locked_config_optional_write()`を追加した。
ロック取得からの読み込みは`locked_config()`と同じだが、書き戻しを
自動で行わず、代わりに`save()`コールバックを渡す。呼び出し側が実際に
変更した場合だけ`save()`を呼ぶ:

```python
with config_store.locked_config_optional_write() as (config, save):
    if ensure_identity(config):
        save()
    identity = config["identity"]
```

`ensure_identity()`自体は純粋なインメモリ変更関数に変更し（戻り値を
「変更したconfig dict」から「変更が発生したかを示すbool」に変更）、
保存の判断と実行は呼び出し側（`identity.py`の`load_identity()`、
`node_api.py`の`_current_config_and_identity()`）に一本化した。
以前は「`load_config()`で読み込み → `ensure_identity()`内部で別途
`save_config()`」という2回のロック取得に分かれており、その間に
別プロセスの書き込みが割り込む競合ウィンドウが理論上存在した
（初回起動時のUUID生成という一度きりのタイミングでしか実害はないが、
これも1回のロック取得に統合して完全に閉じた）。

このAPI変更に伴い、`ensure_identity(config)["identity"]`という戻り値
契約に依存していた既存テスト（`test_nmos_resources.py`、
`test_nmos_registration_client.py`、`test_nmos_integration.py`、
`test_nmos_identity.py`）を新しい契約
（`ensure_identity(config)`はboolを返し、`config`はin-placeで変更される）
に合わせて更新した。

## `registration_client.py`のイベントループブロッキング対策

`run_forever()`と`_heartbeat_loop()`は`async def`のコルーチンで、
FastAPIのsync `def`ルートハンドラ（Starletteが自動的にスレッドプールで
実行する）とは異なり、直接`await`せずに同期処理を呼ぶとイベントループ
全体をブロックする。ロック導入前から存在していた同じ問題（mDNS探索の
`mdns_discovery.discover_registries()`）に対してはすでに
`asyncio.to_thread()`でラップする対策済みだったが、`config_store.load_config()`
や`identity_module.load_identity()`の直接呼び出し（`run_forever()`内2か所、
`identity`解決1か所、`_heartbeat_loop()`内1か所）は未対応のまま残っていた。
ロック導入により`load_config()`は最大`LOCK_TIMEOUT_SECONDS`（5秒）ブロック
しうる同期呼び出しになったため、同じ`asyncio.to_thread()`パターンで
全4か所をラップした。`_heartbeat_loop()`は5秒間隔で常時実行され続ける
ループのため、ここが未対応のままだとNMOSプロセスのConnection API応答性が
定期的に悪化するリスクがあった。

## 検証

修正前の状態を一時的に再現（`config_store.py`の`_acquired_lock()`から
`with _file_lock:`を外し、実質的なロック取得を無効化）し、新規回帰テスト
`test_config_store_cross_process_lock.py::test_concurrent_processes_do_not_lose_updates_to_different_sections`
が実際に失敗することを確認してから修正を復元した。失敗の様子は
「最終値が期待値と食い違う（lost update）」ではなく、Windows環境では
2プロセスが同時に`os.replace()`で同じconfig.jsonへリネームしようとして
`PermissionError: [WinError 5]`でワーカープロセスがクラッシュするという
形で現れた（`proc.exitcode == 0`のアサーションで検出）。これはPOSIXの
`os.replace()`とは異なり、Windowsではアトミックなファイル置換に排他制御が
必須であることを示しており、ロックなしの並行書き込みが安全でないという
同じ根本原因を別の形で証明している。

回帰テストは`multiprocessing`で実プロセスを2つ起動し（スレッドでは
プロセス内ロックで通ってしまい検出できないため）、一方は`ptp.domain`を、
もう一方は`receivers.video[0]`の`payload_id`/`enabled`を300回ずつ
`locked_config()`経由でインクリメント/トグルし、両プロセス終了後に
最終値が「両方の変更が一切失われず正確に反映された値」
（`ptp.domain == 300`、`payload_id == 96 + 300`、`enabled == (300 % 2 == 1)`）
になっていることを検証する。ワーカー関数はpickle可能な独立モジュール
`tests/config_store_mp_worker.py`に切り出した（Windowsの`multiprocessing`は
`spawn`方式のため、テストファイル内のローカル関数はpickleできない）。

修正後、pytest 138件（既存137件＋新規回帰テスト1件）、全件パス確認済み。

# ステップ3a: PTP同期の基盤確立（Amber片系のみ）＋ダッシュボード表示

要件定義書改訂（PTPをMTL内蔵クライアントではなくlinuxptp（ptp4l/phc2sys）で
OSのシステムクロックを同期する方式に変更）を受けての実装。今回はステージ1
（監視のみ、システムクロックには一切触れない）のみを実施し、ステージ2
（phc2sysによるシステムクロック反映）は実機での確認後、別依頼として着手する。

## アーキテクチャ：ptp4lと監視ループを単一systemdユニットにまとめた理由

`multiviewer-ptp.service`はptp4lサブプロセスの起動と、`pmc`による状態収集
ループ（`app/ptp/monitor.py`）の両方を1つのPythonプロセス（`app/ptp_main.py`）
内で行う。2つの別ユニットに分けなかった理由:

- ステップ3bのAmber/Blue冗長は、要件④-3-3の通りBMCA（IEEE1588標準
  アルゴリズム）に系統選択を委ねる。BMCAは**単一のptp4lデーモンが持つ
  複数ポート間**で動作するものであり、Amber用・Blue用に別々のptp4l
  プロセスを立てる設計ではない（`ptp4l.conf`に`[amber_iface]`
  `[blue_iface]`の2セクションを持たせ、1つのptp4lプロセスに両方の
  インターフェースを渡す）。つまりptp4l自体は将来にわたってずっと
  1プロセスのままなので、それを監視するPython側も同じライフサイクルで
  1ユニットにまとめるのが自然
- ptp4lサブプロセスが死んだら、監視ループも即座に停止しプロセス全体を
  終了させ、systemdのRestart=on-failureで両方をまとめて作り直す
  （設定ファイルの再生成込み）。2ユニット構成だと、片方だけ再起動されて
  「古い設定のまま動くptp4l」と「新しい設定を前提にする監視ループ」が
  ズレる可能性があり、それを避けた

## ptp4l設定：ST2059-2プロファイルの各interval値の根拠

linuxptp本体は`configs/`ディレクトリに`SMPTE2059-2.cfg`のような
プロファイル済み設定ファイルを同梱していない（GitHubリポジトリの
`configs/`一覧を実際に確認し、存在しないことを確認済み）。そのため
「有名な実装から丸ごとコピーする」ことができず、要件定義書⑥-4に
明記の無い各interval値（logSyncInterval等）は以下の2つの独立した
一次情報寄りの情報源を突き合わせて採用した:

- IP Infusion OcNOS-SPドキュメント「PTP SMPTE Profile Configuration」の
  実機バリデーション例
- CiscoのNexus 9000向け「Precision Time Protocol for Timing in IP
  Fabric for Media」ガイド

両者が一致した値を採用:
- `domainNumber` 127（要件⑥-4-2と一致）
- `logAnnounceInterval` 0（1秒に1回）
- `logSyncInterval` -3（8回/秒）
- `logMinDelayReqInterval` -3（8回/秒）
- `announceReceiptTimeout` 3
- `delay_mechanism` E2E（要件⑥-4-3と一致）
- `network_transport` UDPv4（要件⑥-4-4と一致）
- `priority1`/`priority2` 128（linuxptpのデフォルト値。本システムは
  `clientOnly 1`のためBMCA上のpriority比較に参加せず実質無意味だが、
  明示的にデフォルト値を書いておく）

DSCP/TTLのQoSマーキングは、情報源の一部（IP Infusion側）にのみ具体的な
値（DSCP 56、TTL 64）の言及があり、要件定義書⑥-4にも明記が無く、かつ
実際のネットワーク設計（スイッチ側のQoSポリシー）と整合しないと逆効果に
なりうるため、今回は意図的に設定していない（ptp4lのデフォルト動作に
委ねる）。必要になった場合はスイッチ側のQoS設計と合わせてステップ3b以降で
検討する。

## clientOnly 1の固定（要件4.3.5・9.3.3、絶対要件）

`app/ptp/config_gen.py`の`CLIENT_ONLY_LINE`定数としてPythonリテラルで
ハードコードし、`config.json`・WebGUI・関数引数のいずれからも変更できる
経路を作っていない。多重の防御を入れている:

1. `generate_ptp4l_config()`は常にこの定数を埋め込む（設定を「読み込んで
   一部だけ変更」するのではなく、毎回スクラッチから生成）
2. `validate_client_only()`で生成直後の文字列を検証する単体テストを追加
   （`clientOnly 0`や、コメントアウトされた`# clientOnly 1`は
   Falseになることも確認）
3. `write_ptp4l_config()`自体が書き込み前に生成テキストを検証し、
   万一含まれていなければ`RuntimeError`で例外を送出しファイルを書かない
4. `app/ptp_main.py`は書き込んだファイルを**再度ディスクから読み直して**
   検証し、`clientOnly 1`が無ければptp4lを起動せず終了コード1で終了する
   （要件が明示的に求める「起動時に設定ファイルを検査」の実装）
5. 既存のptp4l.conf（前回起動時のもの、あるいは手動改変されたもの）を
   読み込んでマージする経路が存在しない。毎起動時に完全に上書きするため、
   ディスク上のファイルを直接書き換えても次回起動で消える

## Unix Domainソケットのパス

`pmc`とptp4lの管理通信はデフォルトで`/var/run/ptp4l`を使うが、本システムは
`/etc/multiviewer/ptp4l.sock`を明示的に指定した（`ptp4l.conf`の
`uds_address`、`pmc`呼び出しの`-s`オプション）。デフォルトパスに依存すると
将来同一ホストで複数のptp4lインスタンス（ステップ3bでも1インスタンスの
ままだが、念のため）が起動された場合に衝突しうるため、本システム専用の
パスを明示する方が堅牢と判断。

## `pmc`出力のパース方式

linuxptpのソースコード（`pmc.c`の`pmc_show()`、`IFMT`マクロ = `"\n\t\t"`）
を実際に確認し、フィールド行が2タブでインデントされ、フィールド名と値が
半角スペース1つで区切られることを確認した上でパーサーを実装した
（`app/ptp/pmc_client.py`の`parse_fields()`）。ヘッダー行
（`sending: GET ...`や`<clockIdentity>-<port> seq N RESPONSE MANAGEMENT ...`）
の正確な書式には依存しない設計にした。どちらの行もインデントされていれば
パーサーは「先頭トークンをキーとする行」として拾ってしまうが、実際に
参照するのは`master_offset`・`gmPresent`・`gmIdentity`・`portState`という
特定のキーのみのため、ヘッダー行由来の余分なキーが紛れ込んでも実害はない
（見なかったことにされるだけ）。この設計により、実機でのヘッダー行の
細部（バージョン差異等）がパーサーを壊すリスクを避けている。

## ジッター閾値（ハードウェア/ソフトウェアタイムスタンプ別）

要件⑤-1-4がソフトウェアタイムスタンプ時のミリ秒オーダーへの精度低下を
明示的に許容しているため、`app/ptp/judgement.py`の`JITTER_THRESHOLD_NS`で
モードごとに別の閾値を持たせた:

- ハードウェアタイムスタンプ: 1,000ns（1マイクロ秒、offsetローリング
  ウィンドウの母標準偏差）
- ソフトウェアタイムスタンプ: 1,000,000ns（1ミリ秒）

要件本文が「3桁以上違います」と明記している通り、ちょうど1000倍の
差を持つ丸めた値を初期値として採用した。実機での実測値が無い状態での
初期値であり、ステップ3aの実機確認後、必要なら調整することを前提とする
（本レポートの「完了時の報告」参照）。ジッター算出には母標準偏差
（`statistics.pstdev`）を採用し、ピーク・トゥ・ピークは実装しなかった
（要件は「標準偏差またはピーク・トゥ・ピーク」とどちらでも良いとしており、
統計的に扱いやすい標準偏差を選んだ）。

サンプル数がローリングウィンドウ（直近60件）に対して`MIN_SAMPLES_FOR_JITTER`
（10件）未満の間は、ジッター値があっても「同期中」として扱い「正常」
「異常」の判定を保留する。

## Announce受信タイムアウトの検出方法（簡略化した判断）

要件は「Announce受信タイムアウトが発生していないこと」を正常判定の条件に
挙げているが、`pmc`にはタイムアウト発生そのものを直接問い合わせる
管理IDが無い。ptp4lはAnnounceタイムアウトを検知すると自身でBMCAを再実行し
ポート状態を変化させる（典型的にはLISTENINGへ遷移）ため、本実装では
「portStateがSLAVEを維持できているか」を代理指標として採用し、ptp4lの
syslogをtailして"Announce timeout"のログ文字列を検出するような追加実装は
行わなかった。ポート状態の変化それ自体を1秒周期の`pmc`ポーリングで
確実に捕捉できるため、実用上はこれで要件の意図（タイムアウトが起きていない
＝SLAVE状態を保っている）を満たせると判断した。

## PTP状態ファイルのスキーマ（ステップ3b拡張を見越した設計）

`app/ptp/status_store.py`の`ptp-status.json`は最初から`legs`キーで
`amber`/`blue`を分けて持つ:

```json
{
  "domain": 127,
  "active_leg": "amber",
  "legs": {
    "amber": { "interface": ..., "port_state": ..., "gm_present": ...,
               "gm_id": ..., "offset_ns": ..., "jitter_ns": ...,
               "sample_count": ..., "state": ..., "last_sample_at": ... },
    "blue": null
  }
}
```

ステップ3aでは`legs.blue`は常に`null`（未収集）のまま。ステップ3bで
Blue系統の監視を追加する際は、`monitor.py`に`LegMonitor("blue", ...)`を
もう1つ生成して`run_forever()`に渡すだけでよく、スキーマ変更は不要。
`active_leg`も、ステップ3aでは「amberがgm_presentならamber」という
自明な代入だが、ステップ3bではBMCAが実際に選択したポートに基づく値に
差し替える想定（`ptp4l`自身の`GET PORT_DATA_SET`のportStateがSLAVEに
なっている方のポートを見れば判定できる）。

ダッシュボードAPI（`/api/dashboard/status`の`ptp`フィールド）も同じ形を
返しており、フロントエンドはamber/blue両方の`legs`を独立して参照できる
（今回はamberのみHTML/JSで表示、blueは今後追加）。

## 状態ファイルの陳腐化（「不明」判定）

`app/ptp/judgement.py`の`is_stale()`/`effective_leg_view()`で、
`last_sample_at`が`STALE_THRESHOLD_SECONDS`（5秒、ポーリング周期1秒の
5倍）より古い場合は、保存されている`state`が何であっても表示上は
「不明」に強制的に上書きする。これは監視プロセス自体が停止した場合に
古い「正常」がそのまま表示され続けることを防ぐための、読み取り時
（ダッシュボードAPI呼び出し時）の判定であり、書き込み側
（`monitor.py`）の判定とは独立している。`pmc`呼び出しが失敗した
ポーリングサイクルでは状態ファイルへの書き込み自体をスキップする設計
のため、失敗が続けば自然に陳腐化し「不明」に収束する。

## NTP（systemd-timesyncd）・phc2sysについて

ステージ1では両方とも一切手を付けていない。`systemd-timesyncd`の無効化、
phc2sysの導入・設定（ステップ・スルー閾値含む）は、実機でのステージ1
確認結果を受けてから、ステージ2として別途着手する。

## テストの検証方針

`clientOnly 1`のハードコード検証、`pmc`出力パース、状態判定ロジック
（正常/同期中/GM未検出/異常/不明の分岐と閾値切り替え、陳腐化判定）を
中心にユニットテストを追加した（`tests/test_ptp_*.py`、48件）。実際の
`ptp4l`・`pmc`・`ethtool`バイナリは開発機（Windows）に存在しないため、
これらは全て`subprocess.run`をモック化してテストしている。実機での
統合的な動作確認（GM検出・SLAVE遷移・offset収束・ダッシュボード表示）は
未実施であり、本ステップの完了報告に明記の上、次のステップで実施する。
