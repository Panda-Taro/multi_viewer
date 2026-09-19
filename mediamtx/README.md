# mediamtx/ — WebRTC (WHEP) 配信

対応要件: ④-6

[MediaMTX](https://github.com/bluenviron/mediamtx) はGo製のメディアサーバで、
RTSP/RTMP入力をWebRTC (WHEP/WHIP) や HLS等で配信できる。本システムでは
compositor (FFmpeg) がローカルRTSPでpushした合成映像+音声を受け取り、
WHEPで `/monitor01/` としてLAN内へ配信する。

## 設計判断

- FFmpeg→MediaMTXの受け渡しはローカルループバックRTSP (`rtsp://127.0.0.1:8554/monitor01`)
  とした。MediaMTXは`paths`設定でこのパスに対しWebRTC配信を自動的に有効化する。
- H.264 + Opus固定 (要件⑥で明示されているコーデック)。MediaMTXの
  `webrtcAdditionalHosts`等はLAN内アクセスのため空でよいが、1G制御NIC
  のIPをGUIから設定できるようにし、`mediamtx.yml`をwebguiが書き換える。
- 認証なし (要件: WebGUI/WebRTCとも認証なし)。MediaMTXの`authMethod: none`相当
  (デフォルトでpaths個別認証を無効化)。
- ビットレート10-50Mbps: MediaMTX自体はエンコードをしない(FFmpeg側で
  `-b:v`指定)。WebGUIの「ビットレート」設定はcompositor起動オプションに
  反映される (webgui/app/routers/system.py 参照)。
- 最大5クライアント: MediaMTXは接続数上限を明示的な設定項目として持たないため、
  リバースプロキシ層(nginx等を挟む場合)かWebGUI側で視聴セッション数を
  カウントし、6件目以降は待機ページを返す設計とした(`webgui`側のsession管理、
  将来拡張。現バージョンではMediaMTXの`hlsAlwaysRemux`等は未使用)。

## ファイル

- `mediamtx.yml` — MediaMTX設定 (パス`monitor01`、WebRTC有効化、ポート等)
- `generate_config.py` — WebGUI設定 (ビットレート/URL/NIC IP) からmediamtx.ymlを
  再生成するヘルパ (テスト対象)
