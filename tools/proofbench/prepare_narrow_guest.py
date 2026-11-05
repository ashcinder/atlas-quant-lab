#!/usr/bin/env python3
"""Add exact unsigned 32/64-bit division paths to an isolated optimized guest.

All multiplications, division boundaries, signed cases and wide fallback stay
in place. Refuse mismatching sources or an existing destination.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

CANONICAL_SHA256 = "4c6c5d6c7ff9c628a9adb2d79580a5c5729841682719f387c3b63686f4938e7b"
OPTIMIZED_SHA256 = "2017441747d3cb64e943aa46fca552bc437e032afb966eaa639ce0b4ff109f5b"


def prepare(source, destination):
    reference = source / "program-core/src/reference.rs"
    original_core = source / "program-core/src/lib.rs"
    if hashlib.sha256(reference.read_bytes()).hexdigest() != CANONICAL_SHA256:
        raise ValueError("reference does not match the frozen 9e3b079 canonical source")
    if hashlib.sha256(original_core.read_bytes()).hexdigest() != OPTIMIZED_SHA256:
        raise ValueError("input does not match the measured optimized baseline")
    destination.mkdir(parents=True, exist_ok=False)
    for part in ("program-core", "program-methods/guest"):
        shutil.copytree(source / part, destination / part, copy_function=shutil.copyfile)
    path = destination / "program-core/src/lib.rs"
    text = path.read_text()
    changes = [
        ("(prefix[closed.len()] - prefix[closed.len() - *window as usize]) / *window as i128",
         "div_exact(prefix[closed.len()] - prefix[closed.len() - *window as usize], *window as i128)", 1),
        ("Instruction::Div => a / b", "Instruction::Div => div_exact(a, b)", 1),
        ("((numerator * MICROS) / denominator) as i64", "div_exact(numerator * MICROS, denominator) as i64", 1),
        ("((wins as i128 * MICROS) / returns.len() as i128) as i64", "div_exact(wins as i128 * MICROS, returns.len() as i128) as i64", 1),
        ("cash + quantity_micros * open / MICROS", "cash + div_exact(quantity_micros * open, MICROS)", 1),
        ("equity_at_open * target_bps as i128 / BPS", "div_exact(equity_at_open * target_bps as i128, BPS)", 1),
        ("target_notional * MICROS / open", "div_exact(target_notional * MICROS, open)", 1),
        ("open * (BPS + strategy.slippage_bps as i128) / BPS", "div_exact(open * (BPS + strategy.slippage_bps as i128), BPS)", 1),
        ("cash * MICROS * BPS / (execution_price * (BPS + strategy.commission_bps as i128))",
         "div_exact(cash * MICROS * BPS, execution_price * (BPS + strategy.commission_bps as i128))", 1),
        ("delta * execution_price / MICROS", "div_exact(delta * execution_price, MICROS)", 1),
        ("notional * strategy.commission_bps as i128 / BPS", "div_exact(notional * strategy.commission_bps as i128, BPS)", 2),
        ("open * (BPS - strategy.slippage_bps as i128) / BPS", "div_exact(open * (BPS - strategy.slippage_bps as i128), BPS)", 1),
        ("(-delta) * execution_price / MICROS", "div_exact((-delta) * execution_price, MICROS)", 1),
        ("cash + quantity_micros * bar.close_micros as i128 / MICROS", "cash + div_exact(quantity_micros * bar.close_micros as i128, MICROS)", 1),
    ]
    for old, new, count in changes:
        if text.count(old) != count:
            raise ValueError("unexpected division call site: " + old)
        text = text.replace(old, new)
    text += '''
// The expressions at each call site retain their original i128 operations.
// TryFrom rejects negative/out-of-range values. Zero divisors still panic;
// signed division, overflow rejection and wide values use the original path.
#[inline]
fn div_exact(numerator: i128, denominator: i128) -> i128 {
    if let (Ok(a), Ok(b)) = (u32::try_from(numerator), u32::try_from(denominator)) {
        return (a / b) as i128;
    }
    if let (Ok(a), Ok(b)) = (u64::try_from(numerator), u64::try_from(denominator)) {
        return (a / b) as i128;
    }
    numerator / denominator
}

#[cfg(test)]
mod narrow_division_tests {
    use super::*;
    fn compare(a: i128, b: i128) {
        let old = std::panic::catch_unwind(|| a / b);
        let new = std::panic::catch_unwind(|| div_exact(a, b));
        assert_eq!(old.is_ok(), new.is_ok(), "accept/reject differs for {a}/{b}");
        if let (Ok(a), Ok(b)) = (old, new) { assert_eq!(a, b); }
    }
    #[test]
    fn division_boundaries_and_signed_rejections_match() {
        let values = [i128::MIN, i128::MIN+1, -1_000_000_000_000_000_000,
            i64::MIN as i128, -7, -3, -1, 0, 1, 3, 7,
            u32::MAX as i128-1, u32::MAX as i128, u32::MAX as i128+1,
            i64::MAX as i128, u64::MAX as i128-1, u64::MAX as i128,
            u64::MAX as i128+1, i128::MAX];
        for a in values { for b in values { compare(a,b); } }
        let mut state = 0x7e57_1234_5678_9abcu128;
        for _ in 0..10000 {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let a = state as i128;
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            compare(a, state as i128);
            compare(a as u64 as i128, state as u64 as i128);
            compare(a as u32 as i128, state as u32 as i128);
        }
    }
    #[test]
    fn successful_witnesses_exercise_all_division_widths() {
        for (price, window) in [(u32::MAX as i64, 1), (u32::MAX as i64+1, 1),
                                (1_000_000_000_000_000_000i64, 20)] {
            let bars: Vec<_> = (0..(window+1).max(3)).map(|i| serde_json::json!({
                "time":1700000000i64+i as i64*86400,"open_micros":price,"close_micros":price,
                "low_micros":price,"high_micros":price,"volume_micros":1000000})).collect();
            let value = serde_json::json!({"agent_id":"qja_width_paths","workflow_commitment":workflow_commitment(),
                "previous_receipt_hash":null,"strategy_salt":vec![0;32],"nullifier_nonce":vec![0;32],
                "initial_equity_micros":10000000000i64,"strategy":{"program":[{"sma":window},{"const":9501},"mod"],
                "commission_bps":10,"slippage_bps":5},"market":{"source":"synthetic","symbol":"TEST",
                "interval":"1d","adjustment":"none","bars":bars}});
            let a = reference::execute(serde_json::from_value(value.clone()).unwrap());
            let b = execute(serde_json::from_value(value).unwrap());
            let a = serde_json::to_value(a).unwrap();
            let mut b = serde_json::to_value(b).unwrap();
            b["proof_profile"] = a["proof_profile"].clone();
            assert_eq!(a,b);
        }
    }
}
'''
    path.write_text(text)
    (destination / "narrow-manifest.json").write_text(json.dumps({
        "experimental_only": True, "canonical_sources_changed": False,
        "fallback": "original signed i128 division for any negative or wider operand",
        "core_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "canonical_reference_sha256": CANONICAL_SHA256,
        "optimized_input_sha256": OPTIMIZED_SHA256,
        "replacement_count": sum(count for _, _, count in changes),
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
