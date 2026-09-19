# コンポーネントバージョン管理

要件⑤(保守性): MTL/FFmpeg/MediaMTX/nmos-cpp/WebGUIスタックのバージョンを追跡する。

| コンポーネント | バージョン(ピン留め) | 取得元 |
|---|---|---|
| OS | Ubuntu Server 24.04.4 LTS | 固定要件 |
| Media Transport Library (MTL) | v24.9 系 (タグ追従、`mtl/scripts/build_mtl.sh` 内で明示) | https://github.com/OpenVisualCloud/Media-Transport-Library |
| DPDK | MTLが要求するバージョン (25.03系。`mtl/scripts/build_mtl.sh` の `DPDK_VERSION` で管理。**2026-09に23.11→25.03へ変更**: MTL mainブランチの要求上昇により実機ビルドで`libdpdk found: NO ... need '>=25.03'`が発生したため) | https://www.dpdk.org/ |
| FFmpeg | 7.x (MTL SDK提供のFFmpeg MTLプラグインパッチ適用版) | https://ffmpeg.org/ , MTL同梱パッチ |
| MediaMTX | v1.9.x | https://github.com/bluenviron/mediamtx |
| nmos-cpp | main (AMWA NMOS準拠、IS-04 v1.3 / IS-05 v1.1対応コミット) | https://github.com/sony/nmos-cpp |
| WebGUIバックエンド | Python 3.12 + FastAPI 0.11x + Uvicorn | pip |
| bridge | Python 3.12 | pip |

各バージョンは `mtl/scripts/build_mtl.sh` / `scripts/setup.sh` 内の変数として
一元管理し、更新時はそのスクリプトのみを変更すればよい設計とした。

## 障害時リカバリ手順 (要件⑤: 保守性)

| 症状 | 対応 |
|---|---|
| MTL RXプロセスが停止/クラッシュ | systemd が `Restart=on-failure` で自動再起動。3回連続失敗時は `journalctl -u multiviewer-mtl-rx` を確認し、hugepages不足・NICドライバ不整合を疑う |
| FFmpeg合成プロセス停止 | systemd自動再起動。MTL側の共有メモリ/デバイスとの接続が張り直される |
| MediaMTXが視聴不可 | `systemctl status multiviewer-mediamtx`、ポート8889/9997の競合を確認 |
| nmos-cppがRDSに登録できない | mDNS到達性、静的IP設定、`journalctl -u multiviewer-nmos-node` を確認 |
| bridgeがactivateを反映しない | `systemctl status multiviewer-bridge`、ログの activate リクエスト受信有無を確認 |
| WebGUIが応答しない | `systemctl restart multiviewer-webgui` |
| NIC IP変更後にアクセス不能 | 変更はロールバック機構(`webgui`が旧設定を一時保持し、再起動後一定時間内に
  確認応答がなければ旧IPに戻すデザイン。詳細は `webgui/app/routers/system.py` 参照)で復旧 |
