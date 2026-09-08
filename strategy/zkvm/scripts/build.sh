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
program_json="$($zkvm_dir/target/release/atlas-zkvm profile --profile atlas_program_backtest_risc0_v2)"
python3 - "$zkvm_dir/profiles.json" "$profile_json" "$program_json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
    "schema": "atlas.quantjudge.zk.profiles.v1",
    "profiles": {},
}
for encoded in sys.argv[2:]:
    profile = json.loads(encoded)
    profile_id = profile.pop("id")
    current = payload["profiles"].get(profile_id)
    if current and current["image_id"] != profile["image_id"]:
        print(f"Preserving immutable {profile_id}; rebuilt image does not match. Proving must use a new reviewed profile.", file=sys.stderr)
        continue
    payload["profiles"][profile_id] = profile
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Built production verifier and updated $zkvm_dir/profiles.json"
