#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
python3 deploy/release/checksums.py --check SHA256SUMS
gzip -dc images/atlas-images.tar.gz | docker load

python3 - <<'PY'
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("release-manifest.json").read_text())
for record in manifest["images"].values():
    actual = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", record["name"]],
        text=True,
    ).strip()
    expected = f"{record['id']} linux/amd64"
    if actual != expected:
        raise SystemExit(f"loaded image mismatch: expected {expected}, got {actual}")
print("images loaded and matched release-manifest.json")
PY
