#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
output=${1:?usage: linux-supplements.sh EVIDENCE_DIR PYTEST_DEPENDENCIES RECEIPT_BUNDLE}
deps=${2:?pytest dependencies directory}
bundle=${3:?existing public receipt bundle}
image=${ATLAS_E2E_API_IMAGE:-atlas-quant-api:r23-local}
mkdir -p "$output/proof-compatibility"
out=$(cd "$output" && pwd)
deps=$(cd "$deps" && pwd)
bundle=$(cd "$(dirname "$bundle")" && pwd)/$(basename "$bundle")
zip_dir="$out/receipt-input"
mkdir "$zip_dir"
python3 - "$bundle" "$zip_dir" <<'PY'
import pathlib,sys,zipfile
source,output=sys.argv[1:]
with zipfile.ZipFile(source) as archive:
    required={"manifest.json","journal.json","market.json","proof.r0","verify-proof-bundle.py","README.txt"}
    for member in required:
        pathlib.Path(output,member).write_bytes(archive.read(member))
PY
docker run --rm --network none --platform linux/amd64 --entrypoint python \
  --tmpfs /tmp:size=512m,mode=1777,exec \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/pytest-tools:/app/backend \
  -v "$deps:/pytest-tools:ro" -v "$PWD/backend/tests:/app/backend/tests:ro" \
  -v "$PWD/scripts/author-proof.py:/app/scripts/author-proof.py:ro" \
  -w /app/backend "$image" -m pytest -p no:cacheprovider -o addopts= -q \
  tests/test_browser_compute.py tests/test_private_compute.py tests/test_market_publisher.py tests/test_public_artifacts.py \
  > "$out/linux-browser-tests.log" 2>&1
docker run --rm --network none --platform linux/amd64 --entrypoint python \
  --tmpfs /tmp:size=512m,mode=1777,exec \
  -e PYTHONDONTWRITEBYTECODE=1 -e ATLAS_DATA_DIR=/tmp/atlas -e ATLAS_OBJECT_ROOT=/tmp/atlas/objects \
  -e ATLAS_ALLOW_REGISTRATION=true -e ATLAS_COOKIE_SECURE=false \
  -v "$zip_dir:/bundle:ro" -v "$bundle:/bundle.zip:ro" \
  -v "$out/proof-compatibility:/output" \
  -v "$PWD/tools/browser_compute/verify_compatibility.py:/qa/verify_compatibility.py:ro" \
  "$image" /qa/verify_compatibility.py > "$out/proof-compatibility.log" 2>&1
