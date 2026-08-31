#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
zkvm_dir="$(cd "$script_dir/.." && pwd)"

if ! command -v cargo-risczero >/dev/null 2>&1 && ! cargo risczero --version >/dev/null 2>&1; then
  echo "cargo-risczero is required. Install with rzup install." >&2
  exit 1
fi

cargo build --manifest-path "$zkvm_dir/Cargo.toml" --release --locked
profile_json="$($zkvm_dir/target/release/atlas-zkvm profile)"
python3 - "$zkvm_dir/profiles.json" "$profile_json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
profile = json.loads(sys.argv[2])
payload = {
    "schema": "atlas.quantjudge.zk.profiles.v1",
    "profiles": {profile.pop("id"): profile},
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Built production verifier and updated $zkvm_dir/profiles.json"
