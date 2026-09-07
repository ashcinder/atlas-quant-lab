#!/usr/bin/env bash
set -euo pipefail
ATLAS_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$ATLAS_PROJECT_ROOT/backend/.venv/bin/python" || ! -d "$ATLAS_PROJECT_ROOT/frontend/node_modules" ]]; then
  echo "请先按 README 安装 Python 虚拟环境和前端依赖。" >&2
  exit 1
fi
children=()
cleanup() {
  for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
(cd "$ATLAS_PROJECT_ROOT/backend" && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
children+=("$!")
(cd "$ATLAS_PROJECT_ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --strictPort) &
children+=("$!")
echo "Atlas: http://127.0.0.1:5173 · 首次使用请创建账号。Ctrl+C 停止。"
while kill -0 "${children[0]}" 2>/dev/null && kill -0 "${children[1]}" 2>/dev/null; do sleep 1; done
exit 1
