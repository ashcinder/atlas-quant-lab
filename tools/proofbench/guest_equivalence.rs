//! Differential checks against the unchanged registered implementation.
use super::*;
use serde_json::{json, Value};

fn input(count: usize, program: Value) -> Value {
    let bars: Vec<_> = (0..count).map(|i| {
        let price = 100_000_000 + (i as i64 % 37 - 18) * 100_000 + i as i64 * 1_000;
        json!({"time": 1_700_000_000i64 + i as i64 * 86400,
            "open_micros":price,"close_micros":price+37,"high_micros":price+1000,
            "low_micros":price-1000,"volume_micros":1000000})
    }).collect();
    json!({"agent_id":"qja_equivalence", "workflow_commitment":workflow_commitment(),
        "previous_receipt_hash":null,"strategy_salt":vec![0;32],"nullifier_nonce":vec![0;32],
        "initial_equity_micros":10000000000i64,
        "strategy":{"program":program,"commission_bps":10,"slippage_bps":5},
        "market":{"source":"synthetic","symbol":"TEST","interval":"1d","adjustment":"none","bars":bars}})
}

fn compare(value: Value) {
    let old = std::panic::catch_unwind(|| reference::execute(serde_json::from_value(value.clone()).unwrap()));
    let new = std::panic::catch_unwind(|| execute(serde_json::from_value(value).unwrap()));
    assert_eq!(old.is_ok(), new.is_ok(), "accept/reject differs");
    if let (Ok(a), Ok(b)) = (old, new) {
        let a = serde_json::to_value(a).unwrap();
        let mut b = serde_json::to_value(b).unwrap();
        b["proof_profile"] = a["proof_profile"].clone();
        assert_eq!(a, b, "full journal differs");
    }
}

#[test]
fn complete_journal_and_rejections_match() {
    let programs = [
        json!([{"const":0}]),
        json!([{"sma":5},{"sma":20},"gt",{"const":9000},{"const":0},"select"]),
        json!([{"load":0},{"const":1},"add",{"store":0},{"load":0},{"const":7},"mod",{"const":0},"eq",{"const":5000},{"const":0},"select"]),
        json!([{"sma":500},{"sma":1},"lt",{"const":7000},{"const":100},"select"]),
        json!([{"close":0},{"close":500},"gt",{"const":9500},{"const":0},"select"]),
        json!([{"const":-7},{"const":3},"div",{"const":-2},"eq",{"const":5000},{"const":0},"select"]),
        json!([{"const":-7},{"const":3},"mod",{"const":-1},"eq",{"const":5000},{"const":0},"select"]),
        json!([{"const":-1},{"const":5000},{"const":0},"select"]),
        json!([{"const":9501}]), json!([{"sma":0}]), json!([{"sma":501}]),
        json!([{"close":501}]), json!([{"load":16}]), json!([{"store":0}]),
        json!([{"const":1},{"const":0},"div"]), json!([{"const":0},{"const":0}]),
    ];
    for count in [3, 16, 19, 20, 21, 100, 499, 500, 501, 1000] {
        for program in &programs { compare(input(count, program.clone())); }
    }
    for window in 1..=500 {
        // Expose the actual integer average through a legal weight, including
        // non-divisible sums; comparing a mean with itself would hide errors.
        compare(input(503, json!([{"sma":window},{"const":9501},"mod"])));
    }
    for depth in [64, 65] {
        let mut ops = vec![json!({"const":0}); depth];
        ops.extend((1..depth).map(|_| json!("add")));
        compare(input(3, Value::Array(ops)));
    }
}

#[test]
fn hashes_match_across_update_boundaries() {
    use sha2::Digest as _;
    for size in [0, 1, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 4097] {
        let bytes: Vec<u8> = (0..size).map(|i| (i * 37) as u8).collect();
        for chunk in [1, 4, 13, 64, 71] {
            let mut hash = Sha256::new();
            for part in bytes.chunks(chunk) { hash.update(part); }
            assert_eq!(hash.finalize().as_slice(), sha2::Sha256::digest(&bytes).as_slice());
        }
    }
}

#[test]
fn current_close_jump_cannot_change_current_decision() {
    let mut value = input(32, json!([{"sma":5},{"sma":20},"gt",{"const":9000},{"const":0},"select"]));
    for bar in value["market"]["bars"].as_array_mut().unwrap() {
        for field in ["open_micros", "close_micros", "high_micros", "low_micros"] {
            bar[field] = json!(100000000);
        }
    }
    value["market"]["bars"][20]["close_micros"] = json!(1000000000);
    value["market"]["bars"][20]["high_micros"] = json!(1000000000);
    compare(value);
}
