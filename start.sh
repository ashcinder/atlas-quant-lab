#!/usr/bin/env bash
# ============================================================
# QuantJudge 一键启动脚本
# 启动：Supervisor（ZKEVM）、后端API、前端
# ============================================================
set -euo pipefail

ATLAS_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ATLAS_PROJECT_ROOT/backend"
FRONTEND_DIR="$ATLAS_PROJECT_ROOT/frontend"
SUPERVISOR_DIR="$ATLAS_PROJECT_ROOT/contracts/supervisor-src"
SUPERVISOR_RUN_ROOT=""
SUPERVISOR_PORT="${ATLAS_SUPERVISOR_RPC_PORT:-42519}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查依赖
check_deps() {
  local missing=()
  if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    missing+=("Python 虚拟环境 (backend/.venv)")
  fi
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    missing+=("前端依赖 (frontend/node_modules)")
  fi
  if [[ ! -f "$SUPERVISOR_DIR/.atlas-hardened" ]]; then
    missing+=("受检 Supervisor 源码 (contracts/supervisor-src)")
  fi
  if ! command -v go >/dev/null 2>&1; then
    missing+=("Go 工具链")
  fi
  for tool in node python3 openssl curl git; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      missing+=("$tool")
    fi
  done
  if [[ ! -x /usr/local/mysql/bin/mysqld ]]; then
    missing+=("本机 MySQL (/usr/local/mysql/bin/mysqld)")
  fi
  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "缺少依赖："
    for dep in "${missing[@]}"; do
      echo "  - $dep"
    done
    exit 1
  fi
}

# 启动 Supervisor（ZKEVM）
start_supervisor() {
  SUPERVISOR_RUN_ROOT="$(mktemp -d /tmp/atlas-supervisor-local-XXXXXX)"
  log_info "启动隔离 Supervisor 并验证签名交易与重启..."
  ATLAS_SUPERVISOR_RUN_ROOT="$SUPERVISOR_RUN_ROOT" \
  ATLAS_SUPERVISOR_RPC_PORT="$SUPERVISOR_PORT" \
  ATLAS_SUPERVISOR_RESULT_FILE="$SUPERVISOR_RUN_ROOT/validation.json" \
  ATLAS_SUPERVISOR_KEEP_RUNNING=1 \
    "$ATLAS_PROJECT_ROOT/contracts/isolated-supervisor/scripts/run-validation.sh"
  export QUANTJUDGE_SUPERVISOR_RPC_URL="http://127.0.0.1:$SUPERVISOR_PORT"
  log_info "隔离 Supervisor 已就绪；Atlas API 使用 $QUANTJUDGE_SUPERVISOR_RPC_URL"
}

cleanup() {
  if [[ -n "${FRONTEND_PID:-}" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  if [[ -n "${BACKEND_PID:-}" ]]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [[ -n "$SUPERVISOR_RUN_ROOT" && -f "$SUPERVISOR_RUN_ROOT/supervisor.pid" ]]; then
    kill "$(cat "$SUPERVISOR_RUN_ROOT/supervisor.pid")" 2>/dev/null || true
    /usr/local/mysql/bin/mysqladmin --defaults-extra-file="$SUPERVISOR_RUN_ROOT/secrets/mysql-root.cnf" shutdown >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 启动后端 API
start_backend() {
  local port=8000
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    log_error "后端 API 端口 ${port} 已占用；无法保证现有进程连接到本轮隔离 Supervisor"
    exit 1
  fi

  log_info "启动后端 API（端口 ${port}）..."
  cd "$BACKEND_DIR"
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $port &
  BACKEND_PID=$!

  # 等待后端就绪
  local max_wait=45
  local waited=0
  while ! curl -sf "http://127.0.0.1:$port/api/v1/health" >/dev/null 2>&1; do
    sleep 1
    ((++waited))
    if [[ $waited -ge $max_wait ]]; then
      log_error "后端 API 启动超时"
      exit 1
    fi
  done
  log_info "后端 API 已就绪（PID: ${BACKEND_PID}）"
}

# 启动前端
start_frontend() {
  local port=5173
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    log_warn "前端已在端口 ${port} 运行，跳过启动"
    return 0
  fi

  log_info "启动前端（端口 ${port}）..."
  cd "$FRONTEND_DIR"
  node node_modules/vite/bin/vite.js --host 127.0.0.1 --strictPort &
  FRONTEND_PID=$!

  # 等待前端就绪
  local max_wait=30
  local waited=0
  while ! curl -sf "http://127.0.0.1:$port" >/dev/null 2>&1; do
    sleep 1
    ((++waited))
    if [[ $waited -ge $max_wait ]]; then
      log_error "前端启动超时"
      exit 1
    fi
  done
  log_info "前端已就绪（PID: ${FRONTEND_PID}）"
}

# 主流程
main() {
  echo ""
  echo "========================================"
  echo "  QuantJudge 一键启动"
  echo "========================================"
  echo ""

  check_deps
  if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    log_error "后端 API 端口 8000 已占用；先停止旧进程，以便连接本轮隔离 Supervisor"
    exit 1
  fi
  start_supervisor
  start_backend
  start_frontend

  echo ""
  echo "========================================"
  echo -e "  ${GREEN}全部服务已启动${NC}"
  echo "========================================"
  echo ""
  echo "  前端界面:  http://127.0.0.1:5173"
  echo "  后端 API:  http://127.0.0.1:8000"
  echo "  Supervisor: $QUANTJUDGE_SUPERVISOR_RPC_URL (仅本机隔离测试链)"
  echo ""
  echo "  按 Ctrl+C 停止所有服务"
  echo "========================================"
  echo ""

  # 等待所有子进程
  wait
}

main "$@"
