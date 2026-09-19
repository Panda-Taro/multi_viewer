# compositor/ — FFmpeg 4分割合成・表示モード切替

対応要件: ④-4 (4分割/シングル切替), ④-5 (音声パススルー), ④-1 (フォーマット不整合アラーム)

MTLが提供するFFmpeg連携プラグイン (`mtl_st20p` 映像デマルチプレクサ /
`mtl_st30p` 音声デマルチプレクサ。https://github.com/OpenVisualCloud/Media-Transport-Library
の `ecosystem/ffmpeg_plugin/` を参照) を用いて、MTLが受信・ST2022-7冗長マージ
済みの4映像+1音声をFFmpegに直接取り込み、`filter_complex` で2x2グリッド合成
またはシングル全画面を生成し、MediaMTXへローカルRTSP/RTMPで払い出す。

## 表示モード切替を1秒以内に反映する設計

要件④-4は「WebGUI・視聴ページ双方から切替でき、約1秒以内に反映」を求める。
FFmpegプロセスの再起動では数秒かかり得るため、以下の方式を採用した(判断メモ):

- filter_complexは常に「4分割レイアウト」と「各ストリームの拡大版」を
  同時に構築しておき、`overlay`/`crop`の**enable式**を`zmq`フィルタ経由の
  ランタイムコマンドで切り替える。これによりプロセス再起動なしで
  即時(1フレーム以内)に表示モードを切替可能。
- フォーマット不整合アラームも同様に`drawtext`の`enable`式をzmq経由で
  ON/OFFする。
- `layout.py` がこの filter_complex 文字列の構築とzmqコマンド生成を担当し、
  ハードウェア非依存な部分としてユニットテストしている。
- `compose.sh` は実際にFFmpeg+MTLプラグインを起動するシェルスクリプト
  (本開発環境では`mtl_st20p`/`mtl_st30p`はビルドされたFFmpegにのみ存在する
  ため実行不可。フラグ名はMTL公式ecosystem/ffmpeg_pluginのドキュメントに
  基づくが、実機導入時にプラグインのバージョンに応じた微調整が必要)。
- `zmqctl.py` はFFmpegのzmqフィルタ (`--enable-libzmq`ビルド時) にTCP経由で
  コマンドを送るクライアント。WebGUI/視聴ページからのトグル要求を
  この経由でFFmpegに伝える。

## ファイル

- `layout.py` — 表示モード状態機械、filter_complex文字列生成、zmqコマンド列生成 (テスト対象)
- `zmqctl.py` — FFmpeg zmqフィルタへのコマンド送信クライアント
- `compose.sh` — FFmpeg+MTLプラグイン起動スクリプト (systemdから起動)
- `tests/` — pytestユニットテスト
