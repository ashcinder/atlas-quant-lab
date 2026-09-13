#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
command -v nitro-cli >/dev/null
python3.11 -m venv .artifacts/nitro/venv
.artifacts/nitro/venv/bin/pip install -r deploy/nitro/requirements.txt
bash deploy/nitro/deploy.sh build
