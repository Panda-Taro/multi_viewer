#!/usr/bin/env bash
# tests/run_all.sh
# 対応要件: ⑨ (実機非依存ロジックの自動テスト実行)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || PYTHON_BIN="python"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m pytest \
  mtl/tests \
  compositor/tests \
  mediamtx/tests \
  nmos/tests \
  bridge/tests \
  webgui/tests \
  -q
