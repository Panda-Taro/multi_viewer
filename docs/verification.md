# 実機検証手順 (要件⑨ 受け入れ基準に対応)

本ドキュメントは、実機(ST2110送出機材・AF_XDP対応10G NIC・PTPグランドマスタ・
NMOSコントローラ/レジストリ・iPad)が揃った環境で、実装済みだが本開発環境では
検証できなかった項目を確認するための手順を示す。

## 1. ST2110-20 4系統受信 + ST2022-7冗長

> **注記**: `sudo ./scripts/setup.sh` 直後、`multiviewer-mtl-rx`/
> `multiviewer-compositor` は実NIC・実Receiver設定が未投入のため
> `invalid num_ports 0` 等のエラーで再起動を繰り返す(`Restart=on-failure`
> により3秒毎)。これは想定内の「未設定状態」であり、手順2でWebGUI/NMOSから
> 実際の設定を投入すると解消される見込み(要実機確認)。

1. `sudo ./scripts/setup.sh` を対象機で実行し、全systemdサービスを起動。
2. `/mgmt/` の「メディアストリーム設定」で4つの映像Receiverにテスト用送出機材の
   Source IP/マルチキャストアドレス/ポート/ペイロードIDを設定 (またはNMOSコントローラ
   から`IS-05 activate`で設定)。
3. `/monitor01/` にブラウザでアクセスし4分割映像が表示されることを確認。
4. Amber側10Gケーブルを抜線 → 視聴映像が途切れないこと(ST2022-7マージにより
   Blue側のみで継続)を確認。約100msのバッファリング許容。
5. Amberを再接続 → 自動的にAmber/Blue両方から受信する状態に復帰することを確認。
6. 4つのReceiverのうち1つだけ異なる解像度/フレームレートのSDPをactivateし、
   `/monitor01/` に「映像フォーマットが4系統で非統一です」のOSDアラームが
   表示されることを確認。

## 2. ST2110-30 音声受信

1. 音声Receiverにテスト送出のSDPをactivate。
2. ブラウザ視聴でch1/2の音声が聞こえること、ch3以降を送出しても影響がないことを確認。

## 3. PTP (ST2059-2) Amber/Blue自動切替

1. Amber側のPTPグランドマスタを停止。
2. RXの同期がBlue側PTPに自動切り替わることを、`mtl/scripts/ptp_status.sh` の
   出力、および `/mgmt/` ダッシュボードのPTPロック状態表示で確認。
3. `/mgmt/` のログビューアに切替イベントが記録されていることを確認。

## 4. 表示モード切替

1. WebGUIダッシュボードのプレビューのトグル、および `/monitor01/` ページ自体の
   トグルボタンで4分割⇄シングルを切り替え、1秒以内に反映されることをストップ
   ウォッチ等で計測。

## 5. 複数クライアント同時視聴

1. Chrome (PC) 3台 + iPad Safari 2台の計5台で同時に `/monitor01/` へアクセスし、
   全クライアントで同期した映像/音声が視聴できることを確認。
2. 6台目のアクセス時の挙動(要件は5台までを想定。挙動は要件外だが、MediaMTXの
   `webrtcAdditionalHosts`/接続数制限設定で意図的に制限するか検討)。

## 6. NMOS IS-04/IS-05

1. 外部RDS (nmos-cpp RegistrationサーバやEasyNMOS等) を1G制御NIC と同一LAN上に
   起動し、mDNS/DNS-SD (`_nmos-register._tcp`) で自動発見されることを確認。
2. RDSを停止し、静的IP/ポート設定に切り替えて登録されることを確認。
3. RDSが存在しない状態でP2Pモード(Node API単体)が有効になることを確認。
4. 外部NMOSコントローラ(例: Riedel/NMOS ControllerやEasyNMOS付属UI)から
   5つのReceiver全てに対しSender SDPをactivateし、`bridge`がMTL RX設定を
   更新しIGMPv3 joinを行うことを、`journalctl -u multiviewer-bridge` と
   `ip maddr show` (Amber/Blue双方のインターフェース)で確認。

## 7. WebGUI

1. `/mgmt/` の各画面 (ダッシュボード/メディアストリーム設定/システム設定) が表示され、
   設定値の保存・エラー時のロールバックが機能することを確認。
2. NIC IP変更 → 確認ダイアログ表示 → 反映には再起動が必要である旨の案内 → 再起動後
   に新IPで到達可能なことを確認 (誤設定時は一定時間で自動ロールバックすることも確認)。
3. ログのエクスポート(ダウンロード)機能を確認。

## 8. レイテンシ

1. ST2110送出側とブラウザ表示側でタイムコードを重畳したテスト映像を用い、
   カメラ等でエンド・ツー・エンドの遅延を実測し、約1秒程度に収まることを確認。
