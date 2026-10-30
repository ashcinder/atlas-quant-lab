#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  printf 'usage: %s ENV_FILE BACKUP.tar.gz NEW_PROJECT\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
env_file=$1
if [[ $(sed -n 's/^ATLAS_CHAIN_MODE=//p' "$env_file") == isolated_lab ]]; then
  exec python3 "$root/deploy/release/chain-snapshot.py" restore "$env_file" "$2" "$3"
fi
archive=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
project=$3
case "$project" in
  ''|*[!a-zA-Z0-9_-]*) printf '%s\n' 'invalid project name' >&2; exit 1 ;;
esac
if [[ ! -f "$archive" || ! -f "$archive.sha256" ]]; then
  printf '%s\n' 'backup and matching .sha256 file are required' >&2
  exit 1
fi
(cd "$(dirname "$archive")" && python3 "$root/deploy/release/checksums.py" --check "$(basename "$archive").sha256")

api_image=$(sed -n 's/^ATLAS_API_IMAGE=//p' "$env_file")
volume="${project}_atlas-data"
if docker volume inspect "$volume" >/dev/null 2>&1; then
  printf 'restore volume already exists: %s\n' "$volume" >&2
  exit 1
fi
docker volume create "$volume" >/dev/null
docker run --rm --platform linux/amd64 --network none --user 0:0 --entrypoint sh \
  -v "$(dirname "$archive"):/backup:ro" -v "$volume:/restore" "$api_image" \
  -c 'test -z "$(ls -A /restore)"; tar -xzf "/backup/$1" -C /restore; chown -R 10001:10001 /restore' \
  sh "$(basename "$archive")"
printf 'restored independent volume: %s\n' "$volume"
printf 'validate with: docker compose --env-file %q -f compose.release.yaml -p %q up --detach --no-build --pull never --wait\n' "$env_file" "$project"
