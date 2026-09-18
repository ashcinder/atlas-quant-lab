#!/usr/bin/env bash
set -euo pipefail
TRINE_NODE_DIR="${TRINE_NODE_DIR:-$HOME/.local/share/atlas-supervisor-zkp-isolated}"
if [[ ! -d "$TRINE_NODE_DIR" ]]; then
  echo "缺少隔离 Supervisor 数据目录：$TRINE_NODE_DIR。不会重置已有链。" >&2
  exit 1
fi
cd "$TRINE_NODE_DIR"
TRINE_NODE_BINARY="$TRINE_NODE_DIR/atlas-isolated-supervisor-new"
if [[ ! -x "$TRINE_NODE_BINARY" ]]; then
  echo "请先在隔离节点源码应用 contracts/patches/supervisor-bkc-rpc.patch 并执行 CGO_ENABLED=0 go build -o atlas-isolated-supervisor-new ." >&2
  exit 1
fi
exec "$TRINE_NODE_BINARY"
