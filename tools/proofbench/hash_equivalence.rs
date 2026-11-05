//! Independent byte/preimage checks against SHA2 and the registered algorithm.
use super::*;

#[test]
fn sdk_direct_hash_preserves_standard_padding_and_unaligned_inputs() {
    use sha2::Digest as _;
    let data: Vec<u8> = (0..4099).map(|i| (i * 37) as u8).collect();
    for length in [0, 1, 50, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 4096] {
        for offset in 0..4 {
            let bytes = &data[offset..offset + length];
            assert_eq!(hash_bytes_fast(bytes).as_slice(), sha2::Sha256::digest(bytes).as_slice());
        }
    }
}

#[test]
fn in_place_merkle_preserves_order_odd_duplication_and_every_level() {
    use sha2::Digest as _;
    for count in (1..=129).chain([255, 256, 257, 499, 500, 501, 999, 1000, 20000]) {
        let leaves: Vec<[u8; 32]> = (0..count).map(|i| sha2::Sha256::digest((i as u64).to_be_bytes()).into()).collect();
        let mut expected = leaves.clone();
        while expected.len() > 1 {
            if expected.len() % 2 == 1 { expected.push(*expected.last().unwrap()); }
            expected = expected.chunks_exact(2).map(|pair| {
                let mut hash = sha2::Sha256::new();
                hash.update(pair[0]);
                hash.update(pair[1]);
                hash.finalize().into()
            }).collect();
        }
        assert_eq!(merkle_root(leaves), hex::encode(expected[0]), "leaf count {count}");
    }
}

#[test]
fn batched_market_preserves_length_prefix_and_field_order() {
    for count in [3, 55, 56, 63, 64, 65, 500, 1000] {
        let bars: Vec<_> = (0..count).map(|i| MarketBar {
            time: 1700000000 + i, open_micros: 100 + i, high_micros: 200 + i,
            low_micros: 50 + i, close_micros: 150 + i, volume_micros: i,
        }).collect();
        for label in ["", "x", "行情\0TEST", &"a".repeat(63), &"b".repeat(64)] {
            let market = MarketDataset { source: label.into(), symbol: "TEST".into(),
                interval: "1d".into(), adjustment: "none".into(), bars: bars.clone() };
            let old = serde_json::from_value(serde_json::to_value(&market).unwrap()).unwrap();
            assert_eq!(market_commitment(&market), reference::market_commitment(&old));
        }
    }
}
