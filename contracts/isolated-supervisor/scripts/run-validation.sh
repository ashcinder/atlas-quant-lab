#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$PACKAGE_DIR/../.." && pwd)"
SOURCE_DIR="${ATLAS_SUPERVISOR_SOURCE:-$PROJECT_DIR/contracts/supervisor-src}"
MYSQL_PORT="${ATLAS_SUPERVISOR_MYSQL_PORT:-19316}"
RPC_PORT="${ATLAS_SUPERVISOR_RPC_PORT:-42519}"
RUN_ROOT="${ATLAS_SUPERVISOR_RUN_ROOT:-$(mktemp -d /tmp/atlas-supervisor-remediation-XXXXXX)}"
RESULT_FILE="${ATLAS_SUPERVISOR_RESULT_FILE:-$PACKAGE_DIR/results/validation-latest.json}"
KEEP_RUNNING="${ATLAS_SUPERVISOR_KEEP_RUNNING:-0}"

if [[ ! -f "$SOURCE_DIR/go.mod" ]]; then
  echo "Supervisor source not found: $SOURCE_DIR" >&2
  exit 1
fi
if lsof -nP -iTCP:"$MYSQL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "MySQL port is already in use: $MYSQL_PORT" >&2
  exit 1
fi
if lsof -nP -iTCP:"$RPC_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "RPC port is already in use: $RPC_PORT" >&2
  exit 1
fi

mkdir -p "$RUN_ROOT" "$RUN_ROOT/secrets" "$RUN_ROOT/mysql-data" "$RUN_ROOT/mysql-tmp" "$RUN_ROOT/state" "$RUN_ROOT/logs" "$(dirname "$RESULT_FILE")"
chmod 700 "$RUN_ROOT" "$RUN_ROOT/secrets"
if [[ -e "$RUN_ROOT/supervisor" ]]; then
  echo "Run root is not empty: $RUN_ROOT/supervisor already exists" >&2
  exit 1
fi
cp -a "$SOURCE_DIR" "$RUN_ROOT/supervisor"
if [[ "$SOURCE_DIR" != "$PROJECT_DIR/contracts/supervisor-src" || ! -f "$RUN_ROOT/supervisor/.atlas-hardened" ]]; then
  python3 "$SCRIPT_DIR/sanitize-copy.py" "$RUN_ROOT/supervisor"
  git -C "$RUN_ROOT/supervisor" apply --ignore-space-change --ignore-whitespace "$PACKAGE_DIR/patches/supervisor-isolated-bootstrap.patch"
  mkdir -p "$RUN_ROOT/supervisor/cmd/atlas-isolated-supervisor"
  cp "$PACKAGE_DIR/overlay/cmd/atlas-isolated-supervisor/main.go" "$RUN_ROOT/supervisor/cmd/atlas-isolated-supervisor/main.go"
  cp "$PACKAGE_DIR/overlay/chain/isolated_call.go" "$RUN_ROOT/supervisor/chain/isolated_call.go"
fi

node "$SCRIPT_DIR/create-wallet.mjs" "$RUN_ROOT/secrets/wallet.json"
MYSQL_PASSWORD="$(openssl rand -hex 32)"
MYSQL_ROOT_PASSWORD="$(openssl rand -hex 32)"
cat > "$RUN_ROOT/secrets/mysql-root.cnf" <<EOF
[client]
user=root
password=$MYSQL_ROOT_PASSWORD
protocol=socket
socket=$RUN_ROOT/mysql.sock
EOF
chmod 600 "$RUN_ROOT/secrets/mysql-root.cnf"
printf '%s' "$MYSQL_PASSWORD" > "$RUN_ROOT/secrets/mysql-password"
chmod 600 "$RUN_ROOT/secrets/mysql-password" "$RUN_ROOT/secrets/wallet.json"

cat > "$RUN_ROOT/my.cnf" <<EOF
[mysqld]
basedir=/usr/local/mysql
datadir=$RUN_ROOT/mysql-data
port=$MYSQL_PORT
bind-address=127.0.0.1
socket=$RUN_ROOT/mysql.sock
pid-file=$RUN_ROOT/mysql.pid
log-error=$RUN_ROOT/logs/mysql.log
tmpdir=$RUN_ROOT/mysql-tmp
skip-name-resolve
local-infile=0
mysqlx=0
EOF
chmod 600 "$RUN_ROOT/my.cnf"

MYSQL_PID=""
SUPERVISOR_PID=""
stop_supervisor() {
  if [[ -n "$SUPERVISOR_PID" ]] && kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
    kill "$SUPERVISOR_PID"
    wait "$SUPERVISOR_PID" 2>/dev/null || true
  fi
  SUPERVISOR_PID=""
}
stop_mysql() {
  if [[ -n "$MYSQL_PID" ]] && kill -0 "$MYSQL_PID" 2>/dev/null; then
    /usr/local/mysql/bin/mysqladmin --defaults-extra-file="$RUN_ROOT/secrets/mysql-root.cnf" shutdown >/dev/null 2>&1 || kill "$MYSQL_PID"
    wait "$MYSQL_PID" 2>/dev/null || true
  fi
  MYSQL_PID=""
}
cleanup() {
  stop_supervisor
  stop_mysql
}
trap cleanup EXIT INT TERM

/usr/local/mysql/bin/mysqld --defaults-file="$RUN_ROOT/my.cnf" --initialize-insecure
/usr/local/mysql/bin/mysqld --defaults-file="$RUN_ROOT/my.cnf" --skip-networking >"$RUN_ROOT/logs/mysql.stdout.log" 2>&1 &
MYSQL_PID=$!
for _ in $(seq 1 60); do
  if /usr/local/mysql/bin/mysqladmin --protocol=socket --socket="$RUN_ROOT/mysql.sock" -uroot ping >/dev/null 2>&1; then break; fi
  sleep 0.5
done
/usr/local/mysql/bin/mysqladmin --protocol=socket --socket="$RUN_ROOT/mysql.sock" -uroot ping >/dev/null
# First boot has no TCP listener. Set root before enabling loopback TCP.
/usr/local/mysql/bin/mysql --protocol=socket --socket="$RUN_ROOT/mysql.sock" -uroot <<SQL
ALTER USER 'root'@'localhost' IDENTIFIED BY '$MYSQL_ROOT_PASSWORD';
CREATE DATABASE atlas_supervisor_isolated CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'atlas_supervisor'@'127.0.0.1' IDENTIFIED BY '$MYSQL_PASSWORD';
GRANT ALL PRIVILEGES ON atlas_supervisor_isolated.* TO 'atlas_supervisor'@'127.0.0.1';
SQL
stop_mysql
/usr/local/mysql/bin/mysqld --defaults-file="$RUN_ROOT/my.cnf" >"$RUN_ROOT/logs/mysql.stdout.log" 2>&1 &
MYSQL_PID=$!
for _ in $(seq 1 60); do
 if /usr/local/mysql/bin/mysqladmin --defaults-extra-file="$RUN_ROOT/secrets/mysql-root.cnf" ping >/dev/null 2>&1; then break; fi
 sleep 0.5
done
/usr/local/mysql/bin/mysqladmin --defaults-extra-file="$RUN_ROOT/secrets/mysql-root.cnf" ping >/dev/null


if /usr/local/mysql/bin/mysql --no-defaults --protocol=socket --socket="$RUN_ROOT/mysql.sock" --user=root --skip-password --execute='SELECT 1' >/dev/null 2>&1; then
 echo "Empty root password unexpectedly accepted" >&2
 exit 1
fi

(
  cd "$RUN_ROOT/supervisor"
  gofmt -w cmd/atlas-isolated-supervisor/main.go chain/isolated_call.go supervisor/security.go
  go build -o "$RUN_ROOT/atlas-isolated-supervisor" ./cmd/atlas-isolated-supervisor
)

PAYER_ADDRESS="$(node -e "const d=require(process.argv[1]); process.stdout.write(d.payer.address)" "$RUN_ROOT/secrets/wallet.json")"
RECIPIENT_ADDRESS="$(node -e "const d=require(process.argv[1]); process.stdout.write(d.recipient.address)" "$RUN_ROOT/secrets/wallet.json")"
FEE_ADDRESS="$(node -e "const d=require(process.argv[1]); process.stdout.write(d.feeSink.address)" "$RUN_ROOT/secrets/wallet.json")"

start_supervisor() {
  (
    cd "$RUN_ROOT/supervisor"
    exec env \
    ATLAS_SUPERVISOR_STATE_ROOT="$RUN_ROOT/state" \
    ATLAS_SUPERVISOR_LEVELDB_DIR="$RUN_ROOT/state/leveldb" \
    ATLAS_SUPERVISOR_DB_PORT="$MYSQL_PORT" \
    ATLAS_SUPERVISOR_DB_NAME="atlas_supervisor_isolated" \
    ATLAS_SUPERVISOR_DB_USER="atlas_supervisor" \
    ATLAS_SUPERVISOR_DB_PASSWORD="$MYSQL_PASSWORD" \
    ATLAS_SUPERVISOR_PAYER_ADDRESS="$PAYER_ADDRESS" \
    ATLAS_SUPERVISOR_RECIPIENT_ADDRESS="$RECIPIENT_ADDRESS" \
    ATLAS_SUPERVISOR_FEE_ADDRESS="$FEE_ADDRESS" \
    ATLAS_SUPERVISOR_RPC_ADDR="127.0.0.1:$RPC_PORT" \
    "$RUN_ROOT/atlas-isolated-supervisor"
  ) >"$RUN_ROOT/logs/supervisor.log" 2>&1 &
  SUPERVISOR_PID=$!
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' "http://127.0.0.1:$RPC_PORT/" >/dev/null 2>&1; then break; fi
    if ! kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
      echo "Supervisor exited during startup; see $RUN_ROOT/logs/supervisor.log" >&2
      exit 1
    fi
    sleep 0.5
  done
  curl -fsS --max-time 2 -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' "http://127.0.0.1:$RPC_PORT/" >/dev/null
}

start_supervisor
ATLAS_SUPERVISOR_RPC_URL="http://127.0.0.1:$RPC_PORT/" node "$SCRIPT_DIR/verify.mjs" phase1 "$RUN_ROOT/secrets/wallet.json" "$RUN_ROOT/phase1.json" "$RESULT_FILE"
stop_supervisor
start_supervisor
ATLAS_SUPERVISOR_RPC_URL="http://127.0.0.1:$RPC_PORT/" node "$SCRIPT_DIR/verify.mjs" phase2 "$RUN_ROOT/secrets/wallet.json" "$RUN_ROOT/phase1.json" "$RESULT_FILE"

if [[ "$KEEP_RUNNING" == "1" ]]; then
  trap - EXIT INT TERM
  printf '%s\n' "$SUPERVISOR_PID" > "$RUN_ROOT/supervisor.pid"
  printf '%s\n' "$MYSQL_PID" > "$RUN_ROOT/mysql-launch.pid"
  chmod 600 "$RUN_ROOT/supervisor.pid" "$RUN_ROOT/mysql-launch.pid"
else
  stop_supervisor
  stop_mysql
  trap - EXIT INT TERM
fi

printf 'Validation passed. Sanitized result: %s\nDiagnostics retained at: %s\nProcesses retained: %s\n' "$RESULT_FILE" "$RUN_ROOT" "$KEEP_RUNNING"
