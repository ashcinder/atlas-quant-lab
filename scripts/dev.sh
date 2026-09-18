 #!/usr/bin/env bash
set -euo pipefail
ATLAS_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$ATLAS_PROJECT_ROOT/backend/.venv/bin/python" || ! -d "$ATLAS_PROJECT_ROOT/frontend/node_modules" ]]; then
  echo "请先按 README 安装 Python 虚拟环境和前端依赖。" >&2
  exit 1
fi
# Optional explicit, trusted local configuration; never contains a private key.
TRINE_DEV_ENV="${TRINE_DEV_ENV:-${XDG_CONFIG_HOME:-$HOME/.config}/trine/dev.env}"
if [[ -f "$TRINE_DEV_ENV" ]]; then
  set -a
  source "$TRINE_DEV_ENV"
  set +a
fi
children=()
cleanup() {
  for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
if [[ "${QUANTJUDGE_SUPERVISOR_RPC_URL:-}" == "http://127.0.0.1:42516" ]]; then
  if ! "$ATLAS_PROJECT_ROOT/backend/.venv/bin/python" -c 'import socket; s=socket.create_connection(("127.0.0.1",42516),2); s.close()' 2>/dev/null; then
    bash "$ATLAS_PROJECT_ROOT/scripts/start-supervisor-isolated.sh" >"${TMPDIR:-/tmp}/trine-supervisor.log" 2>&1 &
    children+=("$!")
    echo "启动隔离 Supervisor 42516，日志：${TMPDIR:-/tmp}/trine-supervisor.log"
  fi
fi
(cd "$ATLAS_PROJECT_ROOT/backend" && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
children+=("$!")
(cd "$ATLAS_PROJECT_ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --strictPort) &
children+=("$!")
echo "Trine: http://127.0.0.1:5173 · 首次使用请创建账号。Ctrl+C 停止。"
while true; do
  for child in "${children[@]}"; do kill -0 "$child" 2>/dev/null || exit 1; done
  sleep 1
done
exit 1
  
