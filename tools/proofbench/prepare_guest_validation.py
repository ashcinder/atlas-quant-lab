#!/usr/bin/env python3
"""Copy backend code and add one experimental profile to its exact Literal.

No production files, data, API contracts, metric limits or registry entries are
changed. This is a migration rehearsal, not current-service compatibility.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    destination = parser.parse_args().destination
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / "backend/app", destination / "app",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    model = destination / "app/zkp_models.py"
    original = model.read_text()
    old = 'proof_profile: Literal["atlas_sma_backtest_risc0_v1", "atlas_program_backtest_risc0_v2"]'
    new = old[:-1] + ', "atlas_program_backtest_risc0_v3_experimental"]'
    assert original.count(old) == 1
    model.write_text(original.replace(old, new, 1))
    (destination / "experimental-schema.json").write_text(json.dumps({
        "experimental_only": True, "production_service_updated": False,
        "change": "add one profile Literal; preserve old values and all constraints",
        "original_model_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "experimental_model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
    }, indent=2))
