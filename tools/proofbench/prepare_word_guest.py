#!/usr/bin/env python3
"""Reduce per-word buffered input copies, preserving SDK serde wire format."""
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
    pins = {"program-core/src/lib.rs": "37879fa315fdd5486749b52abca65465687706c50946f4f6662f2793e830e2b5",
            "program-methods/guest/src/main.rs": "1d5975a81c2aa94e7cfaea816dbe39c194596da9ef8372f06a17a3a576994ed9",
            "program-core/Cargo.toml": "74d5d76291431a05e39449751e4ef0c8a13b33830d9769e54cbcb0698fa32bcc",
            "program-core/Cargo.lock": "4e357b92df453831db27b2757df7897e7a1f7cda4d78697ff40bcbc3264a8cb2",
            "program-methods/guest/Cargo.toml": "c9027ecbd5a696ae56127d5e981171072adff051aed39c910f0197a7b8e94c61",
            "program-methods/guest/Cargo.lock": "36576eacb872a2215d6b4a753345db4e944da05a0e5aa1092415c5f1fd6695b1"}
    for relative, expected in pins.items():
        if hashlib.sha256((args.source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("input differs from reviewed hashfull: " + relative)
    args.destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(args.source / part, args.destination / part, copy_function=shutil.copyfile)
    core = args.destination / "program-core/src/lib.rs"
    core.write_text(core.read_text() + "\npub mod word_reader;\n")
    shutil.copyfile(Path(__file__).with_name("word_reader.rs"), core.with_name("word_reader.rs"))
    entry = args.destination / "program-methods/guest/src/main.rs"
    text = entry.read_text()
    old = "std::io::BufReader::with_capacity(8192, env::stdin())"
    if text.count(old) != 1:
        raise ValueError("guest input entry differs")
    entry.write_text(text.replace(old, "atlas_program_core::word_reader::WordReader::new(env::stdin())"))
    (args.destination / "word-manifest.json").write_text(json.dumps({
        "experimental_only": True, "input_hashes": pins, "input_wire_format_changed": False,
        "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "entry_sha256": hashlib.sha256(entry.read_bytes()).hexdigest(),
        "reader_sha256": hashlib.sha256(core.with_name("word_reader.rs").read_bytes()).hexdigest(),
    }, indent=2) + "\n")
