# bridge/ — NMOS IS-05 activate → MTL RX制御 (自作ブリッジ)

対応要件: ④-7, ⑦

nmos-cpp (C++, IS-05 Connection API) が外部NMOSコントローラから
`PATCH /connection/receivers/{id}/staged` (activate要求、Sender SDP情報を含む)
を受けると、`nmos/node_implementation/multiviewer_node_implementation.cpp` の
activationハンドラが本ブリッジへHTTPで通知する。本ブリッジはこれを受けて:

1. 通知に含まれるSender SDP (SDP文字列 or 構造化JSON) をパースし、
   映像/音声・source IP・マルチキャストグループ・ポート・payload type・
   フォーマット情報を抽出する (`src/sdp.py`)。
2. 対象Receiver (4映像 or 1音声のどれか) の `mtl.rxctl.RxSystemConfig` を更新し、
   MTL RX設定JSON (`/etc/multiviewer/mtl/rx_config.json`) を書き換える
   (`src/translator.py`)。
3. Amber/Blue両方の10G NICに対してIGMPv3 join (SSM: Source-Specific Multicast)
   を発行する (`src/igmp.py`)。Linuxでは `ip maddr add` ではIGMPv3のSSM
   (source指定)は表現できないため、実機では `setsockopt(IP_ADD_SOURCE_MEMBERSHIP)`
   を用いたソケットベースのjoinを行う設計とした (判断メモ: NOTES.md参照)。
4. MTL RXプロセスへ設定反映のため systemd 経由で再起動 (`systemctl restart
   multiviewer-mtl-rx`) をトリガーする。MTLがランタイムAPIでの動的セッション
   追加をサポートするバージョンであれば、将来的にはプロセス再起動なしの
   ホットリロードに置き換えられる (現状は要件の「約1秒」レイテンシ目標は
   ストリーミングパス自体の話であり、activate自体の反映速度は明記されて
   いないため、再起動方式で許容されると判断した)。

## エンドポイント (`src/server.py`, FastAPI)

- `POST /nmos/activate` — nmos-cppからのactivate通知を受信
- `GET /health` — systemdのヘルスチェック用

## ファイル

- `src/sdp.py` — SDPパーサ (video/audio, m=/c=/a=行の抽出)
- `src/translator.py` — activateペイロード → `mtl.rxctl.RxSystemConfig` 反映
- `src/igmp.py` — IGMPv3 (SSM) join発行 (Amber/Blue両NIC)
- `src/server.py` — FastAPIエントリポイント
- `tests/` — pytestユニットテスト (SDPパース、翻訳ロジック)
