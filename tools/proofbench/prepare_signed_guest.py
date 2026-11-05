#!/usr/bin/env python3
"""Extend the isolated exact division experiment to signed 32/64-bit operands."""
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
    hashes = {
        "program-core/src/lib.rs": "26ffa18dc87ea72a9f1c22e131761ed6cbf3eb7db68bc9211be697aba6cbebc3",
        "program-core/src/reference.rs": "4c6c5d6c7ff9c628a9adb2d79580a5c5729841682719f387c3b63686f4938e7b",
        "program-methods/guest/src/main.rs": "1d5975a81c2aa94e7cfaea816dbe39c194596da9ef8372f06a17a3a576994ed9",
    }
    for relative, expected in hashes.items():
        if hashlib.sha256((args.source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("input differs from measured buffered source: " + relative)
    args.destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(args.source / part, args.destination / part, copy_function=shutil.copyfile)
    core = args.destination / "program-core/src/lib.rs"
    text = core.read_text()
    old = "    numerator / denominator\n}"
    if text.count(old) != 1:
        raise ValueError("reviewed division fallback differs")
    text = text.replace(old, '''    if let (Ok(a), Ok(b)) = (i32::try_from(numerator), i32::try_from(denominator)) {
        if let Some(quotient) = a.checked_div(b) { return quotient as i128; }
    }
    if let (Ok(a), Ok(b)) = (i64::try_from(numerator), i64::try_from(denominator)) {
        if let Some(quotient) = a.checked_div(b) { return quotient as i128; }
    }
    numerator / denominator
}''')
    text = text.replace("// TryFrom rejects negative/out-of-range values. Zero divisors still panic;\n// signed division, overflow rejection and wide values use the original path.",
        "// Checked signed paths preserve truncation; narrow MIN/-1 falls through.\n// Out-of-range operands and final overflow/zero rejection retain original i128.")
    text = text.replace("i64::MIN as i128, -7, -3, -1, 0, 1, 3, 7,",
        "i64::MIN as i128, i64::MIN as i128+1, i32::MIN as i128-1, i32::MIN as i128,\n"
        "            i32::MAX as i128, i32::MAX as i128+1, -7, -3, -1, 0, 1, 3, 7,")
    text = text.replace("compare(a as u32 as i128, state as u32 as i128);",
        "compare(a as u32 as i128, state as u32 as i128);\n"
        "            compare(a as i32 as i128, state as i32 as i128);\n"
        "            compare(a as i64 as i128, state as i64 as i128);")
    core.write_text(text)
    (args.destination / "signed-manifest.json").write_text(json.dumps({
        "experimental_only": True, "canonical_sources_changed": False,
        "input_hashes": hashes, "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "fallback": "original i128 for wide operands, narrow overflow and final zero/overflow rejection",
        "call_sites_changed": False,
    }, indent=2))
