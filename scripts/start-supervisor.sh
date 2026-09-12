#!/usr/bin/env bash
set -euo pipefail
ATLAS_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ATLAS_SUPERVISOR_DIR="$ATLAS_PROJECT_ROOT/Supervisor/brokerchain-supervisor"
ATLAS_SUPERVISOR_BIN_DIR="$ATLAS_PROJECT_ROOT/backend/.data/supervisor-bin"
if lsof -nP -iTCP:42515 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "42515端口已被监听；请核验现有Supervisor，不重复启动。" >&2
  exit 1
fi
mkdir -p "$ATLAS_SUPERVISOR_BIN_DIR"
cd "$ATLAS_SUPERVISOR_DIR"
go build -o "$ATLAS_SUPERVISOR_BIN_DIR/supervisor" .
exec "$ATLAS_SUPERVISOR_BIN_DIR/supervisor"
