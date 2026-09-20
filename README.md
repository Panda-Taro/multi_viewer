# MultiViewer

PC ベース・低コストの放送モニタリングシステム。ST2110-20 映像×4系統／ST2110-30
音声×1系統を受信し、4分割合成映像を WebRTC (WHEP) で LAN 内の PC/iPad に配信する。
NMOS (IS-04/IS-05) の **Receiver ロールのみ** をサポートする。

本リポジトリは「MultiViewer要件定義書」に基づく実装である。要件定義書の章番号
(④-1 等) はコミットメッセージ内で参照している。

## アーキテクチャ概要

```
                 ST2110-20 x4 (Amber/Blue, ST2022-7)
                 ST2110-30 x1 (Amber/Blue, ST2022-7)
                 PTP (ST2059-2)
                        │
                 [10G NIC A: Amber] [10G NIC B: Blue]
                        │                 │
                        └───────┬─────────┘
                                ▼
                    mtl/  (Media Transport Library)
                    ・ST2110-20/-30 RX
                    ・PTP クライアント (Amber優先/Blue自動切替)
                    ・ST2022-7 冗長マージ
                                │  (共有メモリ / MTL SDK 経由でフレーム供給)
                                ▼
                    compositor/ (FFmpeg + MTL連携プラグイン)
                    ・4分割合成 / シングル切替
                    ・フォーマット不整合検知 → OSDアラーム
                    ・音声 ch1/2 パススルー
                                │ (RTMP/RTSP等ローカル配信 or 共有メモリ)
                                ▼
                    mediamtx/ (MediaMTX)
                    ・WebRTC WHEP 配信 (H.264 + Opus)
                    ・最大5クライアント同時視聴
                                │
                        [1G NIC: 制御系]
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  nmos/ (nmos-cpp)       bridge/ (自作)             webgui/ (自作)
  IS-04 Node/Reg/Query   IS-05 activate を受けて   /mgmt/ 設定・ダッシュボード
  IS-05 Connection API   MTL RXセッションを再設定   /monitor01/ へのリンク表示
  Receiver x5 のみ       + IGMPv3 join (Amber/Blue)  NMOS状態のライブ反映
```

## ディレクトリ構成

| ディレクトリ | 内容 | 要件章 |
|---|---|---|
| `mtl/` | MTLビルド/セットアップ、ST2110 RX・PTP・ST2022-7 制御ラッパ | ④-1,④-2,④-3,⑦ |
| `compositor/` | FFmpeg 4分割合成、表示モード切替、フォーマット不整合アラーム | ④-4,④-5 |
| `mediamtx/` | MediaMTX 設定 (WHEP配信) | ④-6 |
| `nmos/` | nmos-cpp 設定、Receiverリソースモデル (IS-04/IS-05) | ④-7 |
| `bridge/` | IS-05 activate → MTL再設定 + IGMPv3 join を行う自作ブリッジ (Python) | ④-7,⑦ |
| `webgui/` | WebGUI (FastAPI + Jinja2/JS)。`/mgmt/` 設定画面、ダッシュボード | ④-8 |
| `systemd/` | 各コンポーネントの systemd unit ファイル | 配置要件 |
| `scripts/` | 初回セットアップスクリプト (`setup.sh`) | 配置要件 |
| `docs/` | アーキテクチャ・運用ドキュメント | 全般 |
| `tests/` | 統合テスト用スクリプト・メモ | ⑨ |

## 技術スタック選定理由

- **WebGUI: Python (FastAPI) + Jinja2 + Vanilla JS**
  要件定義書はスタックを指定していないため、以下の理由で選定 (判断根拠、要NOTES.md参照):
  - MTL/nmos-cpp/bridge との連携 (CLI呼び出し・REST) が Python で単純化できる。
  - 認証なし・LAN限定という要件に対し、軽量な ASGI サーバ (uvicorn) で十分。
  - Grafana/Zabbix ライクなダークUIは素のCSS+JSで十分再現可能であり、Node/フロントエンド
    ビルドチェーンを持ち込むコストを避けた。
- **bridge: Python** — nmos-cpp (C++) と MTL (C/CLI) の間を取り持つ薄い仲介層。
  IS-05 activate の JSON を受けて SDP を解析し、MTL RX 設定ファイルを書き換えて
  MTL RXプロセスへ再設定を反映させる。単体テスト可能なロジックとして分離。

## 動作確認状況 (honesty split)

実機 (ST2110送出機材, AF_XDP対応10G NIC, PTPグランドマスタ, NMOSコントローラ/レジストリ,
iPad実機) がこの開発環境には存在しないため、以下のように区分する。

### 動作確認済み (verified in this environment)
- 全コンポーネントのハードウェア非依存ロジックをpytestで実行し、**151件全て合格**
  (mtl 16件、compositor 9件、mediamtx 8件、nmos 11件、bridge 24件、webgui 44件)。
  実行方法: `bash tests/run_all.sh` (または各ディレクトリで `python -m pytest`)。
  内容: SDP(RFC4175/ST2110-30拡張)パース、IS-05 activate→MTL設定変換、
  4系統フォーマット不統一アラーム判定、PTP Amber/Blue自動フェイルオーバー
  状態機械、表示モード(4分割/シングル)切替とzmqコマンド生成、NMOS
  Receiverリソースモデル(Sender非生成・ID安定性)、IGMPv3 SSM join計画、
  WebGUI設定バリデーション(保存失敗時のロールバック)、NIC IP変更の
  確認/自動ロールバック状態機械、ログストア。
- 設定ファイル (MediaMTX yaml, nmos-cpp json, mtl rx_config json, systemd
  unit) の構文チェック (yaml/json parse、systemdユニットのセクション存在確認)
  および全シェルスクリプトの `bash -n` 構文チェックを実施。
- WebGUIをFastAPI TestClientおよびローカル起動 (`uvicorn app.main:app`) で
  動作確認: `/mgmt/`, `/mgmt/media`, `/mgmt/system`, `/mgmt/logs`,
  `/monitor01/` の全画面レンダリング、設定保存API、表示モード切替APIが
  正常応答することを確認。

### 実装したが未検証 — 実機検証が必要 (implemented but unverified)
- MTL による実際の ST2110-20/-30 RX、PTP同期、ST2022-7冗長マージ動作
  → 要 AF_XDP対応10G NIC ×2、ST2110送出機材、PTPグランドマスタ
- FFmpeg+MTLプラグインによる実映像の4分割合成、フォーマット不整合の実検知
  → 要実映像ソース
- MediaMTX 経由の実際のWebRTC WHEP配信 (Chrome/iPad Safari実機)
  → 要LAN環境+実クライアント
- nmos-cpp の実RDS (Registration API) への登録、mDNS/DNS-SD発見、P2Pモード
  → 要外部NMOSレジストリ/コントローラ
- IS-05 activateを外部NMOSコントローラから実際に受け、bridgeが実MTL RXを
  再設定しIGMPv3 joinを行う一連の流れ
  → 要外部NMOSコントローラ + IGMPv3対応スイッチ
- ST2022-7 Amber/Blueケーブル抜線によるシームレス切替、PTP Amber障害時のBlue自動切替
  → 要実ネットワーク・実PTPグランドマスタ2系統
- systemd導入スクリプト (`scripts/setup.sh`) の実機フルインストール
  → 要Ubuntu Server 24.04.4実機 (本開発環境はWindows上のsandboxであり直接実行不可)

具体的な検証手順は `docs/verification.md` を参照。

## セットアップ (実機での想定手順)

```bash
sudo ./scripts/setup.sh
```

これにより依存パッケージ導入、MTL/nmos-cpp/MediaMTXのビルド、hugepages設定、
systemdユニットの導入・有効化までを行う。導入後は `/mgmt/` にアクセスして
NIC IP・Receiver設定・NMOS設定等をGUIから行う (人手によるGUI設定のみで
異なるハードウェアへの再展開が可能な設計)。

## ライセンス・バージョン管理

主要コンポーネントのバージョンは `docs/versions.md` に記載。

## ドキュメント一覧

- `NOTES.md` — 要件定義書に明記されていない実装詳細の判断メモ
- `docs/versions.md` — コンポーネントバージョン一覧・障害時リカバリ手順
- `docs/verification.md` — 実機検証手順 (要件⑨の受け入れ基準対応)
- `mtl/README.md`, `compositor/README.md`, `mediamtx/README.md`,
  `nmos/README.md`, `bridge/README.md`, `webgui/README.md`,
  `systemd/README.md` — 各コンポーネントの設計判断・使い方
- `tests/README.md` — テスト実行方法
