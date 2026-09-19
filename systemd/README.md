# systemd/ — サービスユニット定義

対応要件: 配置要件(Docker不使用、各コンポーネント独立systemdユニット、`Restart=on-failure`)

| ユニット | 役割 | 依存 |
|---|---|---|
| `multiviewer-hugepages.service` | DPDK/AF_XDP用hugepages設定 (oneshot) | - |
| `multiviewer-mtl-rx.service` | MTL RX (ST2110-20x4/-30x1, PTP, ST2022-7) | hugepages |
| `multiviewer-compositor.service` | FFmpeg 4分割合成 | mtl-rx |
| `multiviewer-mediamtx.service` | WebRTC(WHEP)配信 | - |
| `multiviewer-nmos-node.service` | nmos-cpp (IS-04 Node/IS-05 Connection) | avahi-daemon (mDNS) |
| `multiviewer-bridge.service` | IS-05 activate→MTL設定+IGMPv3 join | nmos-node |
| `multiviewer-webgui.service` | WebGUI (`/mgmt/`, `/monitor01/`) | mediamtx |
| `multiviewer-nic-rollback.timer`/`.service` | NIC IP変更の自動ロールバック監視 (30秒毎) | - |

全ユニットは `Restart=on-failure` を設定し、`scripts/setup.sh` が
`/etc/systemd/system/` へコピーし `systemctl enable --now` する。

## 起動順序

```
multiviewer-hugepages
  -> multiviewer-mtl-rx
    -> multiviewer-compositor
multiviewer-mediamtx (独立)
  -> multiviewer-webgui
avahi-daemon
  -> multiviewer-nmos-node
    -> multiviewer-bridge
```
