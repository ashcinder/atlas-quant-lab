#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s ENV_FILE\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
env_file=$1
http_port=$(sed -n 's/^ATLAS_HTTP_PORT=//p' "$env_file")
domain=$(sed -n 's/^ATLAS_DOMAIN=//p' "$env_file")
https_port=$(sed -n 's/^ATLAS_HTTPS_PORT=//p' "$env_file")

curl --fail --silent --show-error "http://127.0.0.1:${http_port}/healthz" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${http_port}/api/v1/health" >/dev/null
curl --fail --silent --show-error "https://${domain}:${https_port}/healthz" >/dev/null
python3 "$root/deploy/release/compose.py" "$env_file" ps
printf '%s\n' 'HTTP upstream and public HTTPS health checks passed'
