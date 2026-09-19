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
