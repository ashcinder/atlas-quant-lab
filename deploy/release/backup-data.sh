#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s ENV_FILE OUTPUT.tar.gz\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
env_file=$1
if [[ $(sed -n 's/^ATLAS_CHAIN_MODE=//p' "$env_file") == isolated_lab ]]; then
  exec python3 "$root/deploy/release/chain-snapshot.py" backup "$env_file" "$2"
fi
output_parent=$(cd "$(dirname "$2")" && pwd)
output="$output_parent/$(basename "$2")"
if [[ -e "$output" || -e "$output.sha256" ]]; then
  printf 'backup output already exists\n' >&2
  exit 1
fi

stage=$(mktemp -d "${TMPDIR:-/tmp}/atlas-backup.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
mkdir -m 700 "$stage/data"
running=$(python3 "$root/deploy/release/compose.py" "$env_file" ps --status running --quiet api)
if [[ -n "$running" ]]; then
  python3 "$root/deploy/release/compose.py" "$env_file" stop api
  trap 'python3 "$root/deploy/release/compose.py" "$env_file" start api >/dev/null 2>&1 || true; rm -rf "$stage"' EXIT
fi
python3 "$root/deploy/release/compose.py" "$env_file" cp api:/app/backend/.data/. "$stage/data/"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$stage/data" -czf "$output" .
chmod 600 "$output"
python3 "$root/deploy/release/checksums.py" "$output" > "$output.sha256"
chmod 600 "$output.sha256"
if [[ -n "$running" ]]; then
  python3 "$root/deploy/release/compose.py" "$env_file" start api
fi
trap 'rm -rf "$stage"' EXIT
printf 'backup created: %s\n' "$output"
