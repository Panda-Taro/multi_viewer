# tests/ — 統合テスト実行

各コンポーネントのユニットテストはそれぞれのディレクトリ (`mtl/tests`,
`compositor/tests`, `mediamtx/tests`, `nmos/tests`, `bridge/tests`,
`webgui/tests`) に置かれている。`run_all.sh` はこれらをまとめて実行する。

```bash
bash tests/run_all.sh
```

実機ハードウェア(ST2110送出機材・AF_XDP NIC・PTPグランドマスタ・NMOS
コントローラ)に依存する項目のチェックリストは `docs/verification.md` を参照。
