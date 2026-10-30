#!/usr/bin/env python3
"""Validate and install the pinned Linux amd64 zkVM verifier artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
from pathlib import Path

EXPECTED_SHA256 = "b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3"
EXPECTED_IMAGE_ID = "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4"
PROFILE = "atlas_program_backtest_risc0_v2"
REPO = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = REPO / "strategy/zkvm/release/linux-amd64/atlas-zkvm"


def validate_file(path: Path) -> None:
    payload = path.read_bytes()
    if payload[:4] != b"\x7fELF" or len(payload) < 20:
        raise SystemExit(f"not an ELF binary: {path}")
    if struct.unpack_from("<H", payload, 18)[0] != 62:
        raise SystemExit(f"not an amd64 ELF binary: {path}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"SHA-256 mismatch: expected {EXPECTED_SHA256}, got {digest}")


def validate_profile(path: Path) -> bool:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        return False
    result = subprocess.run(
        [str(path), "profile", "--profile", PROFILE],
        check=True,
        capture_output=True,
        text=True,
    )
    image_id = json.loads(result.stdout).get("image_id")
    if image_id != EXPECTED_IMAGE_ID:
        raise SystemExit(f"image ID mismatch: expected {EXPECTED_IMAGE_ID}, got {image_id}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="reviewed Linux amd64 atlas-zkvm artifact")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {source}")
    validate_file(source)
    profile_checked = validate_profile(source)

    destination = args.destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source != destination:
        temporary = destination.with_name(f".{destination.name}.tmp")
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    else:
        os.chmod(destination, 0o755)

    validate_file(destination)
    print(f"installed {destination}")
    print(f"sha256 {EXPECTED_SHA256}")
    if profile_checked:
        print(f"profile {PROFILE} image_id {EXPECTED_IMAGE_ID}")
    else:
        print("profile execution deferred to the linux/amd64 Docker image build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
