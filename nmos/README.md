# nmos/ — NMOS IS-04/IS-05 Receiver実装

対応要件: ④-7, ⑥, ⑦(Receiverロールのみ)

[nmos-cpp](https://github.com/sony/nmos-cpp) (AMWA NMOS公式リファレンス実装の1つ、
C++) を用い、IS-04 (Node/Registration/Query API) の **Node** として動作し、
IS-05 (Connection API) で **4映像Receiver + 1音声Receiver** のみを公開する
(Senderリソースは一切生成しない)。

## 実装アプローチと判断メモ

nmos-cppは「動作するリソース(Sender/Receiver等)をコード上で登録する」
アーキテクチャで、`nmos/node_server.h` の `node_implementation` を自プロジェクト用に
差し替えることで、公開するリソースやIS-05 activate時のハンドラを定義する。
これは設定ファイルだけで完結せずC++コードの実装を要するため、本リポジトリでは:

1. `scripts/build_nmos_cpp.sh` — nmos-cpp を実際にクローン・CMakeビルドする
   (Boost, cpprestsdk, websocketpp 等の実依存関係を含む)。
2. `node_implementation/multiviewer_node_implementation.cpp` — nmos-cpp の
   `nmos::experimental::node_implementation` を参考に、本システム固有の
   5リソース(video x4 + audio x1のReceiver)を `nmos::make_video_receiver` /
   `nmos::make_audio_receiver` 相当のAPIで構築し、IS-05
   `/connection/receivers/{id}/staged` PATCH (activate要求) が来た際に
   `bridge/` へHTTPで転送するハンドラ (`make_connection_activation_handler`)
   を実装する。**これはnmos-cppリポジトリの `nmos-cpp-node` サンプルに
   実際に組み込んでビルドする前提のソースであり、本リポジトリ単体では
   ビルドできない(nmos-cppのCMakeプロジェクトにこのファイルを追加し
   `node_implementation.cpp` を置き換える必要がある)。手順は
   `scripts/build_nmos_cpp.sh` 内にコメントで明記した。**
3. `config/node_config.json` — nmos-cpp実行時設定 (実際のnmos-cppが読む
   キー名: `http_port`, `domain`, `label`, `discovery_backend`,
   `registration_address`, `logging_level` 等) に準拠。
   mDNS/DNS-SD自動発見と静的Registration API指定の両方を切り替え可能にした。
4. `receiver_model.py` — IS-04 Receiverリソース/IS-05 Connectionリソースの
   JSON構造をPythonデータクラスとして表現し、(a) 5リソースのUUID一貫性、
   (b) SenderリソースをNEVER生成しないこと、(c) IS-05 activate要求の
   staged→activeへのマージロジック、をハードウェア非依存にテストする。
   これは実際にはC++側実装の「設計台帳」として機能し、C++実装のロジックは
   本Pythonモデルと同一のリソース構造・IDに従う。

## ファイル

- `scripts/build_nmos_cpp.sh`
- `config/node_config.json`
- `config/registration_static.json` (静的RDS指定時の例)
- `node_implementation/multiviewer_node_implementation.cpp`
- `receiver_model.py`, `tests/test_receiver_model.py`
