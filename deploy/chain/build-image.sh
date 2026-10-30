#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT="${ATLAS_SUPERVISOR_BINARY_OUTPUT:-$PROJECT_DIR/.artifacts/lab-full-20261030/chain-build/atlas-isolated-supervisor-linux-amd64}"
IMAGE="${ATLAS_SUPERVISOR_IMAGE:-atlas-supervisor:20261030-lab-full-v1-amd64}"
WEB_BASE="${ATLAS_WEB_IMAGE:-atlas-quant-web:20261030-lab-v1-amd64}"
MYSQL_SOURCE='mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7'
MYSQL_IMAGE="${ATLAS_MYSQL_IMAGE:-atlas-mysql:8.4-amd64}"
BUILD_DIR="$SCRIPT_DIR/.build"
fingerprint=$(python3 "$PROJECT_DIR/deploy/release/source-manifest.py" | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot_sha256"])')

if [[ ! -f "$PROJECT_DIR/contracts/supervisor-src/.atlas-hardened" ]]; then
  echo 'Refusing to build an unsanitized Supervisor source tree.' >&2
  exit 1
fi
mkdir -p "$(dirname "$OUTPUT")" "$BUILD_DIR"
trap 'rm -rf "$BUILD_DIR"' EXIT

(
  cd "$PROJECT_DIR/contracts/supervisor-src"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath \
    -ldflags='-s -w -buildid=' -o "$OUTPUT" ./cmd/atlas-isolated-supervisor
)
chmod 0555 "$OUTPUT"
file "$OUTPUT" | grep -Eq 'ELF 64-bit.*x86-64'
BINARY_SHA256="$(shasum -a 256 "$OUTPUT" | awk '{print $1}')"
cp "$OUTPUT" "$BUILD_DIR/atlas-isolated-supervisor-linux-amd64"

docker build --platform linux/amd64 \
  --file "$SCRIPT_DIR/Dockerfile" \
  --build-arg "ATLAS_WEB_BASE_IMAGE=$WEB_BASE" \
  --build-arg "ATLAS_SUPERVISOR_BINARY_SHA256=$BINARY_SHA256" \
  --label "org.atlas.component=isolated-lab-supervisor" \
  --label "org.atlas.source-snapshot=$fingerprint" \
  --label "org.atlas.supervisor.binary-sha256=$BINARY_SHA256" \
  --tag "$IMAGE" "$PROJECT_DIR"

docker image inspect "$IMAGE" --format '{{.Id}} {{.Os}}/{{.Architecture}}'
docker image inspect "$MYSQL_SOURCE" >/dev/null
docker build --platform linux/amd64 --file "$SCRIPT_DIR/mysql.Dockerfile" \
  --build-arg "ATLAS_MYSQL_BASE_IMAGE=$MYSQL_SOURCE" --tag "$MYSQL_IMAGE" "$PROJECT_DIR"
docker image inspect "$MYSQL_IMAGE" --format '{{.Id}} {{.Os}}/{{.Architecture}}'
printf 'Supervisor binary: %s\nSupervisor SHA-256: %s\nSupervisor image: %s\nMySQL image: %s\n' \
  "$OUTPUT" "$BINARY_SHA256" "$IMAGE" "$MYSQL_IMAGE"
