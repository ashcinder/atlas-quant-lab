#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 3 ]]; then
  printf 'usage: %s ENV_FILE PREVIOUS_RELEASE_MANIFEST COMPATIBILITY_RECORD\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
python3 - "$root" "$1" "$2" "$3" <<'PY'
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root, env_file, previous_path, compatibility_path = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "deploy/release"))
from preflight import load_release_manifest, read_env, validate_rollback_compatibility
import hashlib

current_path = root / "release-manifest.json"
if not current_path.is_file():
    raise SystemExit("current release-manifest.json is required")
if not previous_path.is_file() or not compatibility_path.is_file():
    raise SystemExit("previous release manifest and compatibility record are required")
values = read_env(env_file)
current = load_release_manifest(current_path, values)
previous = load_release_manifest(previous_path, values)
record = json.loads(compatibility_path.read_text())
validate_rollback_compatibility(current, previous, record)
backup_path = Path(record.get('verified_backup_path', ''))
if not backup_path.is_absolute() or not backup_path.is_file():
    raise SystemExit('absolute verified_backup_path is required')
with backup_path.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else None
if actual is None:
    h=hashlib.sha256()
    with backup_path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    actual=h.hexdigest()
if actual != record['verified_backup_sha256']:
    raise SystemExit('verified backup does not match compatibility record')

components = {"api": "ATLAS_API_IMAGE", "web": "ATLAS_WEB_IMAGE"}
if values.get("ATLAS_CHAIN_MODE") == "isolated_lab":
    # Identical chain IDs are required above; keep the currently running images.
    for component,key in (('supervisor','ATLAS_SUPERVISOR_IMAGE'),('mysql','ATLAS_MYSQL_IMAGE')):
        if values.get(key)!=current['images'][component]['name']:
            raise SystemExit('current chain configuration does not match the reviewed manifest')
for component, key in components.items():
    try:
        values[key] = previous["images"][component]["name"]
    except (KeyError, TypeError):
        raise SystemExit(f"previous release manifest is missing {component}") from None

with tempfile.NamedTemporaryFile(mode="w", suffix=".env") as temp:
    temp.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    temp.flush()
    subprocess.run(
        [sys.executable, str(root / "deploy/release/preflight.py"),
         "--env-file", temp.name, "--release-manifest", str(previous_path)],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(root / "deploy/release/compose.py"), temp.name,
         "up", "--detach", "--no-build", "--pull", "never", "--wait",
         "--wait-timeout", "180"],
        check=True,
    )
print("previous reviewed release restored; update the private env file before the next start")
PY
