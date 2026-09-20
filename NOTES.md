# NOTES — 実装上の判断メモ

要件定義書に明記されていない実装レベルの詳細について、判断した内容と理由を記録する。
(タスク指示: 「stop せずに合理的な判断をして進め、判断はコミットメッセージか本ファイルに
記録すること」に対応)

## 技術スタック

- **WebGUIバックエンド**: Python 3 + FastAPI + Uvicorn。フロントエンドはビルドチェーン
  なしの Vanilla JS + Jinja2 テンプレート。理由: 他コンポーネント(MTL CLI, nmos-cpp REST,
  bridge)との連携がPythonで簡潔に書け、認証なし・LAN限定という軽量な要求に対して
  Node/React等のフルスタックは過剰と判断。
- **bridge**: Python。nmos-cpp (C++, IS-05 Connection API) からのactivate通知を
  HTTPコールバック/ポーリングで受け、MTL設定ファイル(JSON)を書き換え、
  `mtl_manager`相当のRX再起動をsystemd経由でトリガーする設計とした。

## 設定ファイル形式・配置場所

- MTL RX設定: `/etc/multiviewer/mtl/rx_*.json` (実機ではこのパスを想定。
  リポジトリ内では `mtl/config/` にサンプルを格納)
- WebGUI/システム全体設定: `/etc/multiviewer/config.yaml` (実機)。
  リポジトリ内サンプルは `webgui/app/default_config.yaml`。
- ログ: `/var/log/multiviewer/*.log` に systemd journal 経由、または各サービスが
  直接書き込む。WebGUIのログビューアは `journalctl` 実行 + ログファイルの両対応。
- ログフォーマット: `ISO8601タイムスタンプ [コンポーネント名] [レベル] メッセージ` の
  プレーンテキスト行。要件は「NMOS接続断、PTP切替、Receiver状態変化を記録」とのみ
  規定しているため、構造化(JSON Lines)ではなく人間可読のプレーンテキスト行を採用し、
  WebGUIのエクスポート機能でそのままダウンロード可能とした。

## デフォルトポート (要件は「auto」がデフォルトと指定、以下は開発時の固定値/レンジ)

- WebGUI: 80番 (HTTP, `/mgmt/`, `/monitor01/`はMediaMTXへリバースプロキシ)
- MediaMTX WebRTC (WHEP): 8889 (MediaMTXデフォルト)、HTTP APIは9997
- nmos-cpp Node API: 8080 (P2Pモード時)、Registration APIクライアントポートは
  デフォルト "auto" (エフェメラル、OS割り当て) とし、GUIから明示指定も可能とした。
- bridge 内部リスンポート: 8090 (nmos-cpp との連携用ローカルAPI)

## NIC命名・冗長構成

- Amber = 物理的に1本目の10G NIC (例: `enp1s0f0` のような命名を想定。実際のNIC名は
  OS依存のため、WebGUIがOSから動的に取得して表示する設計とした)
- Blue = 2本目の10G NIC
- 1G制御NIC = 3本目

## 4分割合成のレイアウト

- 要件定義書は「4分割」の具体的な配置(縦横比、順序)を規定していないため、
  一般的な放送マルチビューアに倣い 2x2 グリッド、Receiver1=左上, 2=右上, 3=左下,
  4=右下 と決定。WebGUIでの並び替えは本バージョンでは未実装(将来拡張候補)。

## フォーマット不整合アラームの表示方法

- 「WebRTCアラームとして表示」と規定されているため、FFmpeg合成時にdrawtext
  フィルタでOSDオーバーレイとして合成後映像に焼き込む方式とした
  (別チャンネルでのアラート配信は行わない = 視聴者には常に映像内表示で伝わる)。

## テスト方針

- 実機非依存のロジック(SDPパース、IS-05 activateペイロード→MTL設定変換、
  表示モード遷移、WebGUI設定バリデーション、NMOSリソースIDの一貫性)は
  pytestでユニットテスト化し、本開発環境で実行・合格を確認した。
- MTL/FFmpeg/MediaMTX/nmos-cppの実バイナリ起動・実RXは本環境で実行不能なため、
  スクリプト/設定の構文的正しさと、ドキュメント化した手動検証手順に留める。

## MTL連携の実装方針

- MTL本体はDPDK/AF_XDPを要求するため本サンドボックスでのビルド・実行は不可能。
  `mtl/` 配下は、MTL公式ドキュメント(https://github.com/OpenVisualCloud/Media-Transport-Library)
  に記載された実際のCLIオプション・JSON設定スキーマ(`st2110-20`のtype、`RxTxApp`
  相当のconfig構造、`st22p`ではなく`video_format`/`payload_type`/`ip_addr`/
  `mcast_sip_addr`等のフィールド名)に準拠したラッパースクリプト・設定テンプレートとして
  実装した。実行可能バイナリそのものは含まれない(要件のインストールスクリプトが
  実機でソースからビルドする)。

### 2026-09 実機セットアップで判明した修正 (MTL RxTxApp関連)

実際にUbuntu Server実機で `scripts/setup.sh` を実行し、以下の誤りが判明した
(sony/nmos-cpp・OpenVisualCloud/Media-Transport-Libraryの実ソースを直接
clone・grepして確認の上で修正):

- **RxTxAppの配置場所**: MTL本体の`build.sh`は`tests/tools/RxTxApp/`配下を
  独立したmesonプロジェクトとして別途ビルドし、`ninja install`でシステム全体
  (デフォルトprefix `/usr/local`)へインストールする。`/opt/multiviewer/build/
  Media-Transport-Library/build/app/RxTxApp`のような場所には存在しない。
  正しくは`/usr/local/bin/RxTxApp`。`mtl/scripts/start_rx.sh`のデフォルト
  `MTL_BIN`を修正した。
- **RxTxAppのCLIオプション**: `--ptp_domain`・`--rx_only`という実際のCLI
  オプションは存在しない(tests/tools/RxTxApp/src/args.cのgetopt_long一覧に
  無い)。渡すとRxTxAppが即座にエラー終了する。`--config_file`のみ実在する。
  RxTxAppはRX/TX兼用ツールで、JSON設定に`tx_sessions`を含めなければRX
  専用として動作する。PTPドメインを指定する実際の方法はソース上
  ("domain"という文字列がtests/tools/RxTxApp配下に一切ない)特定できず、
  **要実機検証**として残した。
- **RxTxApp JSON設定のフィールド名**: `rx_sessions`内の受信マルチキャスト
  アドレスは`dip`ではなく`ip`(`dip`はtx_sessions専用)。ポート番号は
  `udp_port`ではなく`start_port`。video/audioセッションオブジェクトには
  `"type": "frame"`が必須(parse_json.cがNULLチェックなしでこの値を
  `strcmp()`に渡すため、欠落しているとRxTxAppがクラッシュする)。
  `mtl/rxctl.py`の`to_mtl_json()`と`mtl/config/rx_config.template.json`を
  修正した。
- **nmos-cpp node_implementation.cppの全面書き直し**: 当初の実装は
  `nmos::get_seed_id`・`nmos::make_node_resources`・
  `nmos::experimental::insert_resource_after`・`nmos::node_model::
  connection_activation_handler`など、現行nmos-cpp(masterブランチ)には
  存在しないAPIを前提にしていた。sony/nmos-cppを実際にcloneし、公式サンプル
  実装(`Development/nmos-cpp-node/node_implementation.cpp`)の実際のAPI
  パターンを確認した上で全面的に書き直した
  (詳細はnmos/node_implementation/multiviewer_node_implementation.cpp
  冒頭のコメントおよびコミット履歴参照)。
- **教訓**: 本プロジェクトのように依存する外部OSSのAPI/CLIが要件定義時点の
  想定から変化・相違している場合、コメントで「要実機確認」と書くだけでは
  不十分で、実際に対象リポジトリをcloneしてソースを確認しないと動作しない
  コードになりやすい。今回は全て実機ビルドのフィードバックと実ソース確認に
  より修正した。
- **FFmpegビルド手順の欠落**: `scripts/setup.sh`のbuild_components()に
  FFmpeg(MTL連携プラグイン組み込み)のビルド手順が元々欠落しており、
  `multiviewer-compositor.service`が「ffmpegが見つかりません」で起動に
  失敗していた。MTL公式の`ecosystem/ffmpeg_plugin/build.sh`のロジックを
  参考に`mtl/scripts/build_ffmpeg.sh`を新規追加し、要件⑥-4-3(H.264)・
  ⑥-4-4(Opus)を満たすため`--enable-gpl --enable-libx264 --enable-libopus`を
  追加で有効化した(公式スクリプトはlibopenh264のみを想定しており、そのままでは
  libx264/opusが有効にならないため)。
- **nmos-cpp seed_idのUUID形式不正**: `nmos/config/node_config.json`の
  `seed_id`が`nmos-cpp`のJSONスキーマ検証(UUID形式必須の正規表現)に
  違反しており、`multiviewer-nmos-node.service`が起動直後に
  `JSON error: schema validation failed at /seed_id`で即終了していた。
  実在するUUID形式の値に修正した。
- **mtl-rxの起動待ちループは仕様通り(バグではない)**: `RxTxApp`は
  `mtl_init()`の時点でインターフェース(実NICのPCI/AF_XDPポート名)と
  少なくとも1つの有効なRx/Txセッションを要求するため、WebGUIやNMOSで
  実際のNIC情報・Receiver設定が投入されるまでは
  `invalid num_ports 0`/`can not parse ip array for rx`等のエラーで
  起動に失敗し続ける。systemdの`Restart=on-failure`(3秒間隔)により
  静かにリトライを続ける設計とし、これは実機での運用開始(WebGUIでの
  NIC/Receiver設定)によって解消される想定の「未設定状態」であり、
  コード上の不具合ではない。実機検証手順は`docs/verification.md`参照。
- **nmos-cpp node_implementation.cppのSIGSEGV(実機gdbで特定)**: 実機で
  `multiviewer-nmos-node`がnode/deviceリソース挿入後にクラッシュしていた。
  `gdb -batch -ex run -ex bt`で取得したバックトレースから、
  `nmos::stash_category(nmos::category{ "..." })` に**一時オブジェクト**を
  直接渡していたことが原因と判明。`stash_category(const category&)`が
  返す`omanip_function`はcategoryへの参照をキャプチャする実装のため、
  呼び出し式の終わりで一時オブジェクトが破棄されるとダングリング参照になり、
  ログ出力の度に壊れた参照から`std::string`を再構築しようとしてSIGSEGVして
  いた。nmos-cpp公式サンプルの`namespace categories { const nmos::category
  node_implementation{ "..." }; }`という名前空間スコープのstaticオブジェクト
  パターンに合わせて修正した。**教訓**: 一時オブジェクトを「参照をキャプチャする
  コールバックファクトリ」に渡す設計のAPIは、コンパイルが通っても実行時に
  ダングリング参照でクラッシュすることがあるため、公式サンプルのオブジェクト
  寿命の扱い方まで含めて模倣する必要がある。
- **FFmpeg zmqフィルタの組み込み方法の誤り**: `compositor/compose.sh`が
  `-zmq_bind_addr`というFFmpegに存在しないグローバルCLIオプションを渡して
  いたため`Unrecognized option`で即終了していた。FFmpegの`zmq`フィルタは
  filter_complex内にフィルタノード(`zmq=bind_address=...`)として組み込む
  設計であるため、`compositor/layout.py`の`build_filter_complex()`が
  自身の末尾に`zmq`フィルタを追加するよう修正し、compose.sh側の
  `-zmq_bind_addr`引数は削除した。また`zmq`フィルタ自体を有効化するには
  FFmpegを`--enable-libzmq`(+`libzmq3-dev`)付きでビルドする必要があるが
  当初のbuild_ffmpeg.shに含めていなかったため追加した。
  **さらに2回目の実機検証で判明**: `bind_address='tcp://127.0.0.1:5555'`
  というシングルクォート方式でも同じ`No option name near '//...'`エラーが
  再現した(FFmpeg 7.0.3)。FFmpeg本体のソース(libavfilter/f_zmq.c)を確認
  したところ`bind_address`のデフォルト値が`tcp://*:5555`であり、
  ちょうど本システムが使いたいポートと一致することが分かったため、
  `bind_address`オプションを一切指定せず裸の`zmq`フィルタ
  (`[vout_pre]zmq[vout]`)を使う方式に変更してエスケープ問題自体を回避した。
  **さらに3回目の実機検証で判明**: zmqのエスケープ問題解消後、今度は
  `[AVFilterGraph] No such filter: 'drawtext'` で失敗した。drawtextフィルタ
  (④-1のフォーマット不統一アラームのOSD焼き込みに使用)はFFmpegのデフォルト
  configureでは無効化されており、`--enable-libfreetype`
  (+`--enable-libfontconfig` `--enable-libharfbuzz`、
  `libfreetype6-dev`/`libfontconfig1-dev`/`libharfbuzz-dev`)が必要なため
  build_ffmpeg.shに追加した。
  **さらに4回目の実機検証で判明(フィルタグラフ設計自体の誤り)**:
  zmq/drawtextの問題解消後、`Timeline ('enable' option) not supported
  with filter 'crop'` で失敗した。`crop`フィルタはenable(timeline)
  オプションに対応していない。さらにこの時点では未発覚だったが、
  `[single0][single1][single2][single3]overlay@quad2=...`のように
  overlayフィルタに4入力を渡す記述、および`[quadbase]overlay@quad=...`
  のように1入力しか渡さない記述も、overlayが厳密に2入力(base+overlay)
  しか受け付けないため構文として無効だった。`compositor/layout.py`の
  フィルタグラフを、(1)quadoutはhstack/vstackの結果をそのまま使い
  overlay不要、(2)singleoutは黒背景に対しoverlay@single0..3を順に
  チェーン(選択中の1本だけenable=1)、(3)quadoutとsingleoutを
  overlay@mode(2入力)で合成しモードを切り替える、という3段構成に
  全面的に書き直した。「overlayフィルタの入力は常に2つ」という制約を
  今後のフィルタグラフ変更でも守れるよう、回帰テスト
  (`test_build_filter_complex_overlay_filters_have_exactly_two_inputs`)を
  追加した。**教訓**: FFmpegのフィルタグラフはコンパイルエラーのような
  静的検証が効かず、実際に`ffmpeg`を実行するまで構造的な誤り(入力数不一致、
  非対応オプション)が発覚しないため、実機での動作確認が特に重要になる。
- **compose.shがRX設定のプレースホルダをそのままFFmpegへ渡していた**:
  実機で `mtl_parse_rx_port, 0 sip VIDEO1_MCAST is not valid ip address`
  で起動失敗を確認。当初のcompose.shは`-p_sip "AMBER_IP"`のような文字列
  リテラルのプレースホルダをハードコードしており、rxctl.pyが生成した実際の
  RX設定JSON(`/etc/multiviewer/mtl/rx_config.json`)を全く読んでいなかった。
  `compositor/compose.py`を新規作成し、RX設定JSONを読み込んで実際の
  Amber/Blue IP・マルチキャストアドレス・ポート・payload_typeを反映した
  ffmpeg引数を組み立ててexecするよう書き直した(bashでの複雑な配列/クォート
  処理を避けるため、ffmpeg起動処理全体をPython化)。オプション名
  (p_port/r_port/p_sip/r_sip/p_rx_ip/r_rx_ip/udp_port/payload_type)は
  MTL公式リポジトリのecosystem/ffmpeg_plugin/mtl_common.hを実際に確認して
  得た。video_size/pix_fmt/fpsはMTL公式プラグインのデフォルト値
  (1920x1080/yuv422p10le/59.94fps)が本システムの既定フォーマットと一致する
  ため未指定のままとしたが、NMOS SDPでデフォルト以外のフォーマットが
  指定された場合の動的マッピングは未実装(要実装、docs/verification.md
  に追記)。

## 2026-09 WebGUI「4.8 WebGUI」章アップデート対応 + Receiver有効/無効仕様

要件定義書の更新版4.8章と、ユーザーとの協議で確定したReceiver有効/無効の
補足仕様(WebGUIトグルとIS-05 master_enableの一本化、IGMP Leave、3状態LED)
を実装した。判断・制約は以下の通り。

### 画面構成の再編

- 「PTP・NMOS設定」を要件④-8-4-3の記載通りメディアストリーム設定
  (Receiverのみ、④-8-4-2)から独立した専用画面(`/mgmt/ptp-nmos`)に分離した。
  従来はmedia.html/media.pyに同居していた。
- 「ログの大きな表示とエクスポート」は要件④-8-4-4-3の記載通りシステム設定
  画面(`/mgmt/system`)内に埋め込み(直近50件+全ログ/エクスポートへの導線)。
  独立した`/mgmt/logs`ページ自体はより広い絞り込み検索用に残したが、左ペイン
  ナビゲーションからは外した(要件のメニュー構成:ダッシュボード/メディア
  ストリーム設定/PTP・NMOS設定/システム設定の4項目に合わせるため)。
- ダッシュボードの映像プレビュー領域(`#preview`)自体をクリック可能にし、
  表示モード切替(要件④-8-4-1-1-1-2「画面クリックで4分割~1つ素材全面の切替」)
  に対応した。既存の切替ボタンは併存させている(要件は排他を求めていないため)。

### Receiver有効/無効の実装方針

- 内部状態は`mtl/rxctl.py`の`VideoReceiverConfig.enabled`/
  `AudioReceiverConfig.enabled`に一本化した。WebGUIトグル
  (`/webgui/receiver-toggle`)とNMOS IS-05 deactivate
  (`/nmos/deactivate`)はどちらも`bridge/src/translator.py`の
  `apply_enable_request`/`apply_deactivate_request`を経由し、同一の
  `RxSystemConfig`を操作する(要件:「同一の実体を操作するものとして扱う」)。
- 無効化時もソースIP・マルチキャストアドレス・ポート・ペイロードID等は
  データクラス上に保持したまま、`to_mtl_json()`が`is_active()`
  (`enabled and is_configured()`)でRxセッションから除外する方式とした。
  再有効化時はSDPを取得し直さず、保持済みの値でIGMP Joinをやり直す
  (`apply_enable_request`)。
- IGMPv3 Leaveは`bridge/src/igmp.py`に`leave_ssm_group()`を追加した。
  Join時に作成したソケットをbridgeプロセス内メモリ(`_join_sockets`)で
  保持しておき、無効化時にそのソケット上で`IP_DROP_SOURCE_MEMBERSHIP`を
  発行してからcloseする。ソケットを保持していない場合(bridge再起動直後等)
  はベストエフォートでadd即dropする。要件⑥-3-2-3(Join)と対になる動作。
- ダッシュボードのReceiver LEDは3状態(有効・受信中=緑/有効・信号なし=黄/
  無効=灰)に再設計した(`webgui/app/status.py`)。無効化のトリガー種別
  (WebGUI手動 or NMOS操作)はLED上では区別しない(要件通り)。ただしbridgeの
  ログには`trigger`ラベル("WebGUI"/"NMOS")を残し、運用上の追跡は可能にした。
- 映像フォーマット(④-8-4-2-1-1-1「SDP or 59i or 59p」)、音声サンプリング/
  パケットインターバル(④-8-4-2-1-2-1)は、それぞれ`video_format_mode`/
  `sampling_mode`/`ptime_mode`という「モード」フィールドを追加し、
  手動固定モード時はSDP適用(`apply_sdp`)で上書きされないようにした
  (従来は単なる文字列上書きで、手動設定してもNMOSからの次のactivateで
  常に上書きされてしまう設計だったため、この変更がないと「手動固定」を
  実現できない)。

### 既知の制約(要実機検証)

- nmos-cpp側(`nmos/node_implementation/multiviewer_node_implementation.cpp`)
  の活性化ハンドラは、`master_enable=false`(deactivate)の場合のみ新設の
  `/nmos/deactivate`へreceiver_role付きで通知するよう変更した。
  `master_enable=true`(activate)の場合は既存のまま`/nmos/activate`へ
  `receiver_id`+`active`を送るが、**これは元々`bridge/src/server.py`の
  `ActivateRequest`(`receiver_role`+`sdp`を要求)とスキーマが一致しておらず、
  実際には常に422で失敗していたと考えられる、本タスク以前からの既存の
  不整合**。今回のスコープ(Receiver有効/無効)には含まれないため未修正。
  実際のSender SDP本文をactivateハンドラから取得する経路(IS-05の
  transport_paramsにSDP全文は含まれないため、別途Sender側のtransport file
  取得が必要)を含めて別途実装が必要。
- WebGUIトグル操作時、bridgeの`/webgui/receiver-toggle`は呼ぶが、
  nmos-cpp自身が保持するIS-05 `active.master_enable`の値そのものを
  WebGUI側から書き換える経路(通常のNMOSコントローラと同じくIS-05
  Connection APIのstaged PATCH+activateをローカルhttp_clientで叩く)は
  未実装。現状はbridge側の内部状態(`RxSystemConfig.enabled`)とMTL Rx
  セッション制御・IGMP Join/Leaveは正しく連動するが、外部NMOSコントローラが
  IS-05 `/active`を読んだ際にWebGUIトグルの結果が反映されない可能性がある
  (「IS-05の`master_enable`もfalseになる」という補足仕様の一部が未達)。
  nmos-cppのreceiver_role_by_idマップをこの用途にも転用できるため、
  次段の実装候補として残す。
- C++側の変更(`multiviewer_node_implementation.cpp`)は、本サンドボックス
  ではnmos-cpp実体をビルドできないため(DPDK/AF_XDP同様、既存のNOTES.md
  記載の制約と同じ)コンパイル未検証。実機ビルドでの確認が必要。

## 2026-09 メディアストリーム設定画面の再レイアウト + Amber/Blue項目の独立化

ユーザーからのフィードバック(スクロールなしで5ペイン全て視認できるように、
Amber/Blueそれぞれに独立したSource IP/ポート欄を設ける)を受けて再修正した。

- `mtl/rxctl.py`の`VideoReceiverConfig`/`AudioReceiverConfig`から共有の
  `source_ip`/`port`フィールドを廃止し、`source_ip_amber`/`port_amber`/
  `source_ip_blue`/`port_blue`に分離した。ST2022-7では冗長化されたSender側も
  Amber/Blueの2物理IFから別々に送出するため、Source IP・ポートがAmber/Blueで
  異なりうる、という実際のSMPTE 2022-7の性質に合わせた(要件のGUI項目定義
  通り「Amber（ソースIPアドレス、マルチキャストグループアドレス、ポート番号）」
  「Blue（同）」がそれぞれ独立した項目であることに対応)。
  - Amber側のみ、IS-05 activateで得たSDPから自動反映される(従来通り)。
  - Blue側は要件通り手打ちのみ(自動反映元がない。ST2022-7の2経路目は
    NMOS SDPからは1系統分の情報しか得られないため)。
  - MTL RxTxAppの1 rx_session構成は`start_port`を1つしか持てないため、
    `to_mtl_json()`は`port_amber`を採用値とする(`port_blue`が異なっていても
    現状のRxTxApp連携では反映されない。要実機検証、非対称ポートが実際に
    必要な場合は別途MTL側の対応調査が必要)。
- `webgui/app/templates/media.html`を、Grafana/Zabbix的な密度優先の
  グリッドレイアウトに全面刷新した。5ペイン(映像Receiver x4、音声Receiver x1)
  を`display: grid`(3列、狭幅では2列に自動収縮)で並べ、各ペイン内は
  ラベル+入力を横一列にした`field-row`で構成することで、1画面(概ねフルHD
  相当の解像度)でスクロールなしに全ペインを視認できるようにした
  (`webgui/app/static/css/style.css`の`.media-grid`/`.receiver-pane`/
  `.field-row`)。狭い/低解像度な環境では依然としてブラウザ側のズームや
  ウィンドウ幅次第でスクロールが発生しうるが、要件が想定するデスクトップ
  ブラウザでの利用では収まる設計とした。
