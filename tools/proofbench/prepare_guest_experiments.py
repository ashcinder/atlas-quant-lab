#!/usr/bin/env python3
"""Create isolated SDK 3.0.6 guest variants; never edit registered sources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "atlas_program_backtest_risc0_v3_experimental"


def replace_once(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def prepare(destination):
    destination.mkdir(parents=True, exist_ok=False)
    original = ROOT / "strategy/zkvm"
    source = (original / "program-core/src/lib.rs").read_text()
    manifest = {}
    for variant in ("baseline", "sha", "optimized"):
        path = destination / variant
        # Fresh file mtimes prevent Cargo root-package cache reuse across
        # different source directories mounted at the same container path.
        shutil.copytree(original / "program-core", path / "program-core", copy_function=shutil.copyfile)
        shutil.copytree(original / "program-methods/guest", path / "program-methods/guest", copy_function=shutil.copyfile)
        core = replace_once(source, '"atlas_program_backtest_risc0_v2"', f'"{PROFILE}"')
        if variant != "baseline":
            core = replace_once(core, "use sha2::{Digest, Sha256};",
                                "use risc0_zkvm::sha::rust_crypto::{Digest, Sha256};")
            with (path / "program-core/Cargo.toml").open("a") as f:
                f.write('\nrisc0-zkvm = { version = "=3.0.6", default-features = false, features = ["std"] }\n')
        if variant == "optimized":
            core = replace_once(core,
                "fn evaluate(program: &[Instruction], closed: &[MarketBar], state: &mut [i128; 16]) -> u32 {",
                "fn evaluate_cached(program: &[Instruction], closed: &[MarketBar], state: &mut [i128; 16], prefix: &[i128], stack: &mut Vec<i128>) -> u32 {")
            core = replace_once(core, "    let mut stack: Vec<i128> = Vec::new();", "    stack.clear();")
            core = replace_once(core,
                "closed[closed.len() - *window as usize..].iter()\n                        .map(|b| b.close_micros as i128).sum::<i128>() / *window as i128",
                "(prefix[closed.len()] - prefix[closed.len() - *window as usize]) / *window as i128")
            core = replace_once(core, "    let mut state = [0i128; 16];",
                "    // Validated <=20,000 positive i64 closes: sum fits exactly in i128.\n"
                "    let prefix = close_prefix(&strategy.program, bars);\n"
                "    let mut stack = Vec::with_capacity(64);\n"
                "    let mut state = [0i128; 16];")
            core = replace_once(core, "evaluate(&strategy.program, &bars[..index], &mut state)",
                "evaluate_cached(&strategy.program, &bars[..index], &mut state, &prefix, &mut stack)")
            core += '''
fn close_prefix(program: &[Instruction], bars: &[MarketBar]) -> Vec<i128> {
    if !program.iter().any(|op| matches!(op, Instruction::Sma(_))) { return Vec::new(); }
    let mut prefix = Vec::with_capacity(bars.len() + 1);
    prefix.push(0i128);
    for bar in bars { prefix.push(prefix.last().unwrap() + bar.close_micros as i128); }
    prefix
}

#[cfg(test)]
fn evaluate(program: &[Instruction], closed: &[MarketBar], state: &mut [i128; 16]) -> u32 {
    evaluate_cached(program, closed, state, &close_prefix(program, closed), &mut Vec::new())
}
'''
        (path / "program-core/src/lib.rs").write_text(core)
        # Original code is compiled only for host differential tests, never the guest.
        (path / "program-core/src/reference.rs").write_text(source)
        with (path / "program-core/src/lib.rs").open("a") as f:
            f.write('\n#[cfg(test)]\nmod reference;\n#[cfg(test)]\nmod equivalence;\n')
        shutil.copyfile(ROOT / "tools/proofbench/guest_equivalence.rs", path / "program-core/src/equivalence.rs")
        with (path / "program-core/Cargo.toml").open("a") as f:
            f.write('\n[workspace]\n\n[dev-dependencies]\nserde_json = "1.0"\n')
        # Pin all registry versions to the existing workspace for host tests.
        shutil.copyfile(original / "Cargo.lock", path / "program-core/Cargo.lock")
        manifest[variant] = {"core_sha256": hashlib.sha256((path / "program-core/src/lib.rs").read_bytes()).hexdigest(),
                             "profile": PROFILE, "experimental_only": True}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    prepare(parser.parse_args().destination)
