#!/usr/bin/env bash
# Run on a Nitro-enabled Amazon Linux host with Docker, nitro-cli and Python.
set -euo pipefail
cd "$(dirname "$0")/../.."
command -v nitro-cli >/dev/null
command -v docker >/dev/null
[[ -c /dev/nitro_enclaves ]] || { echo 'Nitro-enabled EC2 required'; exit 1; }
mode=${1:-build}
mkdir -p .artifacts/nitro
if [[ "$mode" == build ]]; then
  docker build -f deploy/nitro/Dockerfile -t atlas-enclave:review .
  nitro-cli build-enclave --docker-uri atlas-enclave:review --output-file .artifacts/nitro/atlas.eif > .artifacts/nitro/measurements.json
  sha256sum .artifacts/nitro/atlas.eif > .artifacts/nitro/atlas.eif.sha256
  echo 'Build complete. Author must review and approve these measurements in their own KMS account.'
elif [[ "$mode" == run ]]; then
  : "${ATLAS_PACKAGE:?Set encrypted package absolute path}"
  : "${ATLAS_PLATFORM:?Set HTTPS platform URL}"
  : "${ATLAS_APPROVED_EIF_SHA256:?Set author-approved EIF SHA256}"
  actual=$(sha256sum .artifacts/nitro/atlas.eif | cut -d ' ' -f 1)
  [[ "$actual" == "$ATLAS_APPROVED_EIF_SHA256" ]] || { echo 'EIF does not match approval'; exit 1; }
  # No --debug-mode or --attach-console. Never terminate an unrelated enclave.
  nitro-cli run-enclave --eif-path .artifacts/nitro/atlas.eif --cpu-count 2 --memory 1024 > .artifacts/nitro/instance.json
  enclave_id=$(python3 -c 'import json; print(json.load(open(".artifacts/nitro/instance.json"))["EnclaveID"])')
  trap 'nitro-cli terminate-enclave --enclave-id "$enclave_id" >/dev/null' EXIT
  cid=$(python3 -c 'import json; print(json.load(open(".artifacts/nitro/instance.json"))["EnclaveCID"])')
  .artifacts/nitro/venv/bin/python deploy/nitro/relay.py --cid "$cid" --package "$ATLAS_PACKAGE" --platform "$ATLAS_PLATFORM"
else
  echo 'Usage: deploy.sh build|run'; exit 1
fi
