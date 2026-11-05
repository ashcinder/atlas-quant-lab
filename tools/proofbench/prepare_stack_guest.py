#!/usr/bin/env python3
"""Compare fixed storage under the existing 64-entry guest stack limit."""
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
        "program-core/src/lib.rs": "6e7edd1eb65af4edcdab6dd7b5b66951fc3d677c18c14589bd79623c023b5b6d",
        "program-core/src/word_reader.rs": "2e27bac9e4ba2267ab39bd87aabe24e9fa3d4f9ac74051a4cbc29d578e499f7f",
        "program-methods/guest/src/main.rs": "7e96cb3fd0999b6b464d58135a642f4afc810df25fa5fa1a6ff7a7f026cf73d2",
        "program-core/Cargo.toml": "74d5d76291431a05e39449751e4ef0c8a13b33830d9769e54cbcb0698fa32bcc",
        "program-core/Cargo.lock": "4e357b92df453831db27b2757df7897e7a1f7cda4d78697ff40bcbc3264a8cb2",
        "program-methods/guest/Cargo.toml": "5e8c5e14603617109d6d85ee25a7bcd4bd004e2a97d99cf0f8e2fdd71613eb5e",
        "program-methods/guest/Cargo.lock": "36576eacb872a2215d6b4a753345db4e944da05a0e5aa1092415c5f1fd6695b1",
    }
    for relative, expected in pins.items():
        if hashlib.sha256((args.source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("source differs from reviewed hashforcelto: " + relative)
    args.destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(args.source / part, args.destination / part, copy_function=shutil.copyfile)
    core = args.destination / "program-core/src/lib.rs"
    text = core.read_text()
    for before, after in [
        ("stack: &mut Vec<i128>) -> u32", "stack: &mut EvalStack) -> u32"),
        ("let mut stack = Vec::with_capacity(64);", "let mut stack = EvalStack::new();"),
        ("&mut Vec::new())\n}", "&mut EvalStack::new())\n}"),
    ]:
        if text.count(before) != 1:
            raise ValueError("reviewed stack expression differs: " + before)
        text = text.replace(before, after)
    text += '''
// One extra slot preserves push-then-reject at depth 65, never accepting it.
struct EvalStack { values: [i128; 65], len: usize }
impl EvalStack {
    fn new() -> Self { Self { values: [0; 65], len: 0 } }
    fn clear(&mut self) { self.len = 0; }
    fn len(&self) -> usize { self.len }
    fn push(&mut self, value: i128) { self.values[self.len] = value; self.len += 1; }
    fn pop(&mut self) -> Option<i128> {
        if self.len == 0 { None } else { self.len -= 1; Some(self.values[self.len]) }
    }
}
impl std::ops::Index<usize> for EvalStack {
    type Output = i128;
    fn index(&self, index: usize) -> &i128 {
        assert!(index < self.len);
        &self.values[index]
    }
}
'''
    core.write_text(text)
    (args.destination / "stack-manifest.json").write_text(json.dumps({
        "experimental_only": True, "input_hashes": pins, "stack_limit_changed": False,
        "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "stack_storage_slots": 65, "accepted_stack_limit": 64,
    }, indent=2) + "\n")
