#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s ENV_FILE\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
env_file=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")

python3 "$root/deploy/release/preflight.py" --env-file "$env_file"
python3 "$root/deploy/release/compose.py" "$env_file" \
  up --detach --no-build --pull never --wait --wait-timeout 180
"$root/deploy/release/healthcheck.sh" "$env_file"
