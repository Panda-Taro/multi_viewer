# mtl/ — Media Transport Library 連携層

対応要件: ④-1 (映像受信), ④-2 (音声受信), ④-3 (PTP同期), ⑦ (AF_XDP/NIC非依存)

[Media Transport Library (MTL)](https://github.com/OpenVisualCloud/Media-Transport-Library)
は Intel主導のOSS ST2110スタックで、DPDK または AF_XDP をバックエンドとして
ST2110-20/-30/-40 の送受信、PTP (ST2059-2) クライアント、ST2022-7 冗長を提供する。

本ディレクトリはMTL本体をビルド・実行するためのスクリプトと、MTLのJSON設定
スキーマ(MTL公式リポジトリ `app/etc/*.json` に準拠したフィールド名)に基づく
RX設定テンプレート、および設定生成・反映を行うPython制御モジュール
(`rxctl.py`)を提供する。**MTL本体のソース/バイナリは含まない**
(`scripts/build_mtl.sh` が実機でソースからクローン・ビルドする)。

## なぜこの実装形態か (判断メモ)

MTLはDPDKもしくはlibxdp/AF_XDPを要求し、実行にはカーネルモジュール・
hugepages・専用NICドライバ設定が必須で、本開発サンドボックス(Windows上の
非特権コンテナ)ではビルド・実行が不可能。そのため、

1. `build_mtl.sh` / `setup_hugepages.sh` は MTL公式ドキュメントに記載された
   実際の手順(DPDKビルド → MTLビルド → `RxTxApp`サンプルアプリのインストール)
   をそのままシェルスクリプト化した「実機で動くはずの」実装とした。
2. RX設定(`config/rx_config.json`)はMTL公式サンプル(`app/etc/`)のJSONスキーマ
   ("interfaces", "rx_sessions[].video[]", "rx_sessions[].audio[]" 等の
   フィールド名・値のenum)に準拠させた。ただし要件ドキュメントにない
   ST2022-7冗長構成のJSON表現(`interface`配列を2要素にし`dip`配列も2要素に
   対応させる方式)はMTL README記載のRedundant(ST2022-7)設定例に基づく解釈であり、
   実機のMTLバージョンによりフィールド名が異なる可能性がある。**実機導入時は
   導入するMTLバージョンの `app/etc/` サンプルと突き合わせて確認すること。**
3. `rxctl.py` はMTL RXプロセス(`RxTxApp` または自作RXデーモン)を直接
   linkするC++ SDK呼び出しではなく、(a) JSON設定ファイルの生成・書き換え、
   (b) systemd経由でのRXプロセス再起動、という「設定ファイル + プロセス制御」
   境界で抽象化した。これはbridge (④-7) からのIS-05 activate要求を
   低リスクに反映するためと、hugepages/DPDK EAL初期化を伴うMTLプロセスを
   Python長時間常駐プロセスに直接linkするのは複雑度・安定性の観点で
   避けるべきと判断したため。将来的にMTLのC APIをPython bindingやgRPCで
   直接叩く構成に差し替え可能なよう、`RxSessionConfig` データクラス経由の
   薄い境界にしている。

## ファイル

- `scripts/build_mtl.sh` — DPDK/MTLの取得・ビルド・インストール
- `scripts/setup_hugepages.sh` — hugepages設定 (DPDK/AF_XDP用)
- `scripts/start_rx.sh` — 生成済みJSON設定でRXアプリを起動 (systemdから呼ばれる)
- `scripts/ptp_status.sh` — MTLのPTPログ/統計から現在の同期ソース(Amber/Blue)を
  抽出するラッパー (実機のログフォーマットはMTLバージョン依存のため要調整)
- `config/rx_config.template.json` — 4映像+1音声のRXセッション設定テンプレート
- `rxctl.py` — RX設定のPythonデータモデル・バリデーション・JSON生成・
  ST2022-7冗長構成・フォーマット統一性チェック (ユニットテスト対象)
- `ptp_monitor.py` — PTP Amber/Blue切替の状態機械 (ユニットテスト対象)
