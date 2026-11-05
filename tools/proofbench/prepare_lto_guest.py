#!/usr/bin/env python3
"""Compare cross-crate release optimization without changing guest algorithms."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    pins = {
        "program-core/src/lib.rs": "ad5b2c13ceb1dbf2d6a33d8e6ef5de27511a0db5447274a9aa29ab4e0a02bb45",
        "program-core/src/word_reader.rs": "2e27bac9e4ba2267ab39bd87aabe24e9fa3d4f9ac74051a4cbc29d578e499f7f",
        "program-methods/guest/src/main.rs": "7e96cb3fd0999b6b464d58135a642f4afc810df25fa5fa1a6ff7a7f026cf73d2",
        "program-core/Cargo.toml": "74d5d76291431a05e39449751e4ef0c8a13b33830d9769e54cbcb0698fa32bcc",
        "program-core/Cargo.lock": "4e357b92df453831db27b2757df7897e7a1f7cda4d78697ff40bcbc3264a8cb2",
        "program-methods/guest/Cargo.toml": "c9027ecbd5a696ae56127d5e981171072adff051aed39c910f0197a7b8e94c61",
        "program-methods/guest/Cargo.lock": "36576eacb872a2215d6b4a753345db4e944da05a0e5aa1092415c5f1fd6695b1",
    }
    for relative, expected in pins.items():
        if hashlib.sha256((args.source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("source differs from reviewed hashwords: " + relative)
    args.destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(args.source / part, args.destination / part, copy_function=shutil.copyfile)
    manifest = args.destination / "program-methods/guest/Cargo.toml"
    text = manifest.read_text()
    if "[profile." in text:
        raise ValueError("unexpected existing release profile")
    manifest.write_text(text + '\n[profile.release]\nlto = "fat"\ncodegen-units = 1\n')
    (args.destination / "lto-manifest.json").write_text(json.dumps({
        "experimental_only": True, "input_hashes": pins, "algorithms_changed": False,
        "sdk_version_changed": False, "floating_point_fast_math": False,
        "lto": "fat", "codegen_units": 1,
    }, indent=2) + "\n")
