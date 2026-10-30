#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
api_image=${ATLAS_API_IMAGE:-atlas-quant-api:20261030-lab-v1-amd64}
web_image=${ATLAS_WEB_IMAGE:-atlas-quant-web:20261030-lab-v1-amd64}
verifier="$repo/strategy/zkvm/release/linux-amd64/atlas-zkvm"
fingerprint=$(python3 "$repo/deploy/release/source-manifest.py" | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot_sha256"])')

if [[ ! -f "$verifier" ]]; then
  printf 'missing verified artifact: %s\n' "$verifier" >&2
  exit 1
fi

docker buildx build --platform linux/amd64 --load \
  --label "org.atlas.source-snapshot=$fingerprint" \
  --file "$repo/deploy/backend.Dockerfile" --tag "$api_image" "$repo"
docker buildx build --platform linux/amd64 --load \
  --label "org.atlas.source-snapshot=$fingerprint" \
  --build-arg VITE_TRINE_DEMO_MODE=false \
  --build-arg VITE_TRINE_TEST_PRIVATE_KEY= \
  --file "$repo/deploy/frontend.Dockerfile" --tag "$web_image" "$repo"

docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$api_image" "$web_image"
