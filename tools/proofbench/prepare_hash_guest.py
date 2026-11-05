#!/usr/bin/env python3
"""Isolated byte-identical hash batching; never edits registered guest sources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("reviewed hash source differs: " + before[:80])
    return text.replace(before, after, 1)


def prepare(source, destination, full_market):
    pinned = {
        "program-core/src/lib.rs": "aaeae5ad6615eb01784032ca8d663e8321f8a0f3d74d8f64f056fb2e14105c66",
        "program-core/src/reference.rs": "4c6c5d6c7ff9c628a9adb2d79580a5c5729841682719f387c3b63686f4938e7b",
        "program-methods/guest/src/main.rs": "1d5975a81c2aa94e7cfaea816dbe39c194596da9ef8372f06a17a3a576994ed9",
        "program-core/Cargo.toml": "74d5d76291431a05e39449751e4ef0c8a13b33830d9769e54cbcb0698fa32bcc",
        "program-core/Cargo.lock": "4e357b92df453831db27b2757df7897e7a1f7cda4d78697ff40bcbc3264a8cb2",
        "program-methods/guest/Cargo.toml": "c9027ecbd5a696ae56127d5e981171072adff051aed39c910f0197a7b8e94c61",
        "program-methods/guest/Cargo.lock": "36576eacb872a2215d6b4a753345db4e944da05a0e5aa1092415c5f1fd6695b1",
    }
    for relative, expected in pinned.items():
        if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("source differs from measured signed guest: " + relative)
    destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(source / part, destination / part, copy_function=shutil.copyfile)
    core = destination / "program-core/src/lib.rs"
    text = core.read_text()
    text = replace_once(text, "        hash.update([tag]);\n        hash.update(value.to_be_bytes());", """        let mut encoded = [0u8; 9];
        encoded[0] = tag;
        encoded[1..].copy_from_slice(&value.to_be_bytes());
        hash.update(encoded);""")
    text = replace_once(text, """    for bar in &dataset.bars {
        for value in [""", """    for bar in &dataset.bars {
        let mut encoded = [0u8; 48];
        for (part, value) in encoded.chunks_exact_mut(8).zip([""")
    text = replace_once(text, """            bar.volume_micros,
        ] {
            hasher.update(value.to_be_bytes());
        }
    }""", """            bar.volume_micros,
        ]) {
            part.copy_from_slice(&value.to_be_bytes());
        }
        hasher.update(encoded);
    }""")
    start = text.index("fn merkle_root(")
    end = text.index("\nfn curve_commitment", start)
    text = text[:start] + """// The SDK API applies standard SHA-256 padding; no raw/compression-only hashes.
fn hash_bytes_fast(bytes: &[u8]) -> [u8; 32] {
    use risc0_zkvm::sha::{Impl, Sha256 as _};
    Impl::hash_bytes(bytes).as_bytes().try_into().unwrap()
}

fn merkle_root(mut leaves: Vec<[u8; 32]>) -> String {
    assert!(!leaves.is_empty(), "empty merkle tree");
    while leaves.len() > 1 {
        let width = leaves.len();
        for output in 0..width.div_ceil(2) {
            // Read both children before overwriting the earlier output slot.
            let mut encoded = [0u8; 64];
            encoded[..32].copy_from_slice(&leaves[output * 2]);
            encoded[32..].copy_from_slice(&leaves[(output * 2 + 1).min(width - 1)]);
            leaves[output] = hash_bytes_fast(&encoded);
        }
        leaves.truncate(width.div_ceil(2));
    }
    hex::encode(leaves[0])
}
""" + text[end:]
    text = replace_once(text, """        hasher.update(point.time.to_be_bytes());
        hasher.update(point.return_ppm.to_be_bytes());
        hasher.update(point.benchmark_return_ppm.to_be_bytes());""", """        let mut encoded = [0u8; 24];
        encoded[..8].copy_from_slice(&point.time.to_be_bytes());
        encoded[8..16].copy_from_slice(&point.return_ppm.to_be_bytes());
        encoded[16..].copy_from_slice(&point.benchmark_return_ppm.to_be_bytes());
        hasher.update(encoded);""")
    text = replace_once(text, """        let mut leaf = Sha256::new();
        leaf.update(b"ATLASDECISION1");
        leaf.update(bar.time.to_be_bytes());
        leaf.update(target_bps.to_be_bytes());
        leaf.update((cash as i64).to_be_bytes());
        leaf.update((quantity_micros as i64).to_be_bytes());
        leaf.update(equity_i64.to_be_bytes());
        leaves.push(leaf.finalize().into());""", """        let mut encoded = [0u8; 50];
        encoded[..14].copy_from_slice(b"ATLASDECISION1");
        encoded[14..22].copy_from_slice(&bar.time.to_be_bytes());
        encoded[22..26].copy_from_slice(&target_bps.to_be_bytes());
        encoded[26..34].copy_from_slice(&(cash as i64).to_be_bytes());
        encoded[34..42].copy_from_slice(&(quantity_micros as i64).to_be_bytes());
        encoded[42..].copy_from_slice(&equity_i64.to_be_bytes());
        leaves.push(hash_bytes_fast(&encoded));""")
    if full_market:
        start = text.index("pub fn market_commitment(")
        end = text.index("\npub fn strategy_commitment", start)
        text = text[:start] + """pub fn market_commitment(dataset: &MarketDataset) -> String {
    let mut encoded = Vec::with_capacity(32 + dataset.source.len() + dataset.symbol.len()
        + dataset.interval.len() + dataset.adjustment.len() + 48 * dataset.bars.len());
    encoded.extend_from_slice(b"ATLASMARKET1");
    for value in [&dataset.source, &dataset.symbol, &dataset.interval, &dataset.adjustment] {
        encoded.extend_from_slice(&(value.len() as u32).to_be_bytes());
        encoded.extend_from_slice(value.as_bytes());
    }
    encoded.extend_from_slice(&(dataset.bars.len() as u32).to_be_bytes());
    for bar in &dataset.bars {
        for value in [bar.time, bar.open_micros, bar.high_micros, bar.low_micros,
                      bar.close_micros, bar.volume_micros] {
            encoded.extend_from_slice(&value.to_be_bytes());
        }
    }
    hex::encode(hash_bytes_fast(&encoded))
}
""" + text[end:]
    text += '\n#[cfg(test)]\nmod hash_equivalence;\n'
    core.write_text(text)
    shutil.copyfile(Path(__file__).with_name("hash_equivalence.rs"),
                    core.with_name("hash_equivalence.rs"))
    (destination / "hash-manifest.json").write_text(json.dumps({
        "experimental_only": True, "canonical_sources_changed": False,
        "input_hashes": pinned, "full_market_buffer": full_market,
        "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "input_wire_format_changed": False, "hash_preimages_changed": False,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--full-market", action="store_true")
    args = parser.parse_args()
    prepare(args.source, args.destination, args.full_market)
