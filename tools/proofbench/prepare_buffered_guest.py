#!/usr/bin/env python3
"""Isolated SDK input buffering, preserving the exact witness wire format."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

CORE_SHA256 = "26ffa18dc87ea72a9f1c22e131761ed6cbf3eb7db68bc9211be697aba6cbebc3"
REFERENCE_SHA256 = "4c6c5d6c7ff9c628a9adb2d79580a5c5729841682719f387c3b63686f4938e7b"
ENTRY_SHA256 = "59d74d81d99c7cbcdf1903ba1023258a8620692fc86bcf041f6c5c1df0b94ed4"
GUEST_MANIFEST_SHA256 = "25d6a1f4b91249c2881555eba60815c2e74e87ec296466f64faa975c3b312867"
GUEST_LOCK_SHA256 = "85b64b57a280abddc2d279c0db303268feb0569cc7dd94a444ca85cf7fff78e5"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    for relative, expected in [("program-core/src/lib.rs", CORE_SHA256),
                               ("program-core/src/reference.rs", REFERENCE_SHA256),
                               ("program-methods/guest/src/main.rs", ENTRY_SHA256),
                               ("program-methods/guest/Cargo.toml", GUEST_MANIFEST_SHA256),
                               ("program-methods/guest/Cargo.lock", GUEST_LOCK_SHA256)]:
        if hashlib.sha256((args.source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("source differs from the reviewed narrow candidate: " + relative)
    entry = (args.source / "program-methods/guest/src/main.rs").read_text()
    if entry.count("let witness: StrategyWitness = env::read();") != 1:
        raise ValueError("guest input entry differs from the measured baseline")
    args.destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(args.source / part, args.destination / part, copy_function=shutil.copyfile)
    entry = entry.replace("use risc0_zkvm::guest::env;", "use risc0_zkvm::guest::env;\nuse serde::Deserialize;")
    entry = entry.replace("let witness: StrategyWitness = env::read();",
        "let input = std::io::BufReader::with_capacity(8192, env::stdin());\n"
        "    let witness = StrategyWitness::deserialize(&mut risc0_zkvm::serde::Deserializer::new(input)).unwrap();")
    (args.destination / "program-methods/guest/src/main.rs").write_text(entry)
    with (args.destination / "program-methods/guest/Cargo.toml").open("a") as file:
        file.write('\nserde = "1.0"\n')
    lock_path = args.destination / "program-methods/guest/Cargo.lock"
    lock = lock_path.read_text()
    old_package = 'name = "atlas-program-guest"\nversion = "0.2.0"\ndependencies = [\n "atlas-program-core",\n "risc0-zkvm",\n]'
    if lock.count(old_package) != 1:
        raise ValueError("guest lock package differs from the reviewed candidate")
    lock_path.write_text(lock.replace(old_package, old_package.replace('\n]', '\n "serde",\n]')))
    (args.destination / "buffered-manifest.json").write_text(json.dumps({
        "experimental_only": True, "input_wire_format_changed": False,
        "core_sha256": CORE_SHA256, "reference_sha256": REFERENCE_SHA256,
        "buffer_bytes": 8192, "guest_entry_sha256": hashlib.sha256(entry.encode()).hexdigest(),
        "input_guest_manifest_sha256": GUEST_MANIFEST_SHA256,
        "input_guest_lock_sha256": GUEST_LOCK_SHA256,
        "output_guest_manifest_sha256": hashlib.sha256((args.destination / "program-methods/guest/Cargo.toml").read_bytes()).hexdigest(),
        "output_guest_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    }, indent=2))
