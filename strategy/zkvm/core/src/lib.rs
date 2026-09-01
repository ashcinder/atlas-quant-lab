use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const MICROS: i128 = 1_000_000;
const BPS: i128 = 10_000;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct MarketBar {
    pub time: i64,
    pub open_micros: i64,
    pub high_micros: i64,
    pub low_micros: i64,
    pub close_micros: i64,
    pub volume_micros: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct MarketDataset {
    pub source: String,
    pub symbol: String,
    pub interval: String,
    pub adjustment: String,
    pub bars: Vec<MarketBar>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SmaStrategy {
    pub fast_period: u32,
    pub slow_period: u32,
    pub target_position_bps: u32,
    pub commission_bps: u32,
    pub slippage_bps: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct StrategyWitness {
    pub agent_id: String,
    pub workflow_commitment: String,
    pub previous_receipt_hash: Option<String>,
    pub strategy_salt: [u8; 32],
    pub nullifier_nonce: [u8; 32],
    pub initial_equity_micros: i64,
    pub strategy: SmaStrategy,
    pub market: MarketDataset,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ZkMetricSet {
    pub total_return_ppm: i64,
    pub annualized_return_ppm: i64,
    pub max_drawdown_ppm: i64,
    pub annualized_volatility_ppm: i64,
    pub sharpe_milli: i64,
    pub win_rate_ppm: i64,
    pub benchmark_return_ppm: i64,
    pub observation_count: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ZkCurvePoint {
    pub time: i64,
    pub return_ppm: i64,
    pub benchmark_return_ppm: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ZkPublicStatement {
    pub schema: String,
    pub proof_profile: String,
    pub agent_id: String,
    pub strategy_commitment: String,
    pub workflow_commitment: String,
    pub market_data_hash: String,
    pub cost_model_hash: String,
    pub report_type: String,
    pub period_start: i64,
    pub period_end: i64,
    pub initial_equity_micros: i64,
    pub final_equity_micros: i64,
    pub decision_count: u32,
    pub decision_merkle_root: String,
    pub equity_curve_hash: String,
    pub previous_receipt_hash: Option<String>,
    pub nullifier: String,
    pub metrics: ZkMetricSet,
    pub public_curve: Vec<ZkCurvePoint>,
}

fn put_text(hasher: &mut Sha256, value: &str) {
    let bytes = value.as_bytes();
    hasher.update((bytes.len() as u32).to_be_bytes());
    hasher.update(bytes);
}

fn as_hex(hasher: Sha256) -> String {
    hex::encode(hasher.finalize())
}

pub fn market_commitment(dataset: &MarketDataset) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASMARKET1");
    put_text(&mut hasher, &dataset.source);
    put_text(&mut hasher, &dataset.symbol);
    put_text(&mut hasher, &dataset.interval);
    put_text(&mut hasher, &dataset.adjustment);
    hasher.update((dataset.bars.len() as u32).to_be_bytes());
    for bar in &dataset.bars {
        for value in [
            bar.time,
            bar.open_micros,
            bar.high_micros,
            bar.low_micros,
            bar.close_micros,
            bar.volume_micros,
        ] {
            hasher.update(value.to_be_bytes());
        }
    }
    as_hex(hasher)
}

pub fn strategy_commitment(strategy: &SmaStrategy, salt: &[u8; 32]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASSTRATEGY1");
    hasher.update(strategy.fast_period.to_be_bytes());
    hasher.update(strategy.slow_period.to_be_bytes());
    hasher.update(strategy.target_position_bps.to_be_bytes());
    hasher.update(strategy.commission_bps.to_be_bytes());
    hasher.update(strategy.slippage_bps.to_be_bytes());
    hasher.update(salt);
    as_hex(hasher)
}

pub fn cost_model_commitment(strategy: &SmaStrategy) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASCOST1");
    hasher.update(strategy.commission_bps.to_be_bytes());
    hasher.update(strategy.slippage_bps.to_be_bytes());
    hasher.update(b"next_open_no_lookahead:v1");
    as_hex(hasher)
}

pub fn workflow_commitment() -> String {
    let mut hasher = Sha256::new();
    hasher.update(
        b"ATLASWORKFLOW1:market_data>sma_signal>target_sizer>hard_risk>next_open_execution>audit>output",
    );
    as_hex(hasher)
}

fn validate_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_witness(witness: &StrategyWitness) {
    let strategy = &witness.strategy;
    assert!(witness.agent_id.starts_with("qja_"), "invalid agent id");
    assert_eq!(
        witness.workflow_commitment,
        workflow_commitment(),
        "workflow mismatch"
    );
    assert!(
        witness
            .previous_receipt_hash
            .as_deref()
            .map(validate_hash)
            .unwrap_or(true),
        "invalid previous receipt"
    );
    assert!(
        (2..=250).contains(&strategy.fast_period),
        "invalid fast period"
    );
    assert!(
        (3..=500).contains(&strategy.slow_period),
        "invalid slow period"
    );
    assert!(
        strategy.fast_period < strategy.slow_period,
        "fast must be less than slow"
    );
    assert!(
        (1..=9_500).contains(&strategy.target_position_bps),
        "invalid target position"
    );
    assert!(strategy.commission_bps <= 1_000, "commission too high");
    assert!(strategy.slippage_bps <= 1_000, "slippage too high");
    assert!(witness.initial_equity_micros > 0, "invalid initial equity");
    assert!(
        witness.market.bars.len() >= strategy.slow_period as usize + 2
            && witness.market.bars.len() <= 20_000,
        "invalid bar count"
    );
    let mut previous_time = 0;
    for bar in &witness.market.bars {
        assert!(bar.time > previous_time, "bar times must increase");
        assert!(
            bar.low_micros > 0 && bar.open_micros > 0 && bar.close_micros > 0,
            "invalid price"
        );
        assert!(
            bar.high_micros >= bar.open_micros.max(bar.close_micros),
            "invalid high"
        );
        assert!(
            bar.low_micros <= bar.open_micros.min(bar.close_micros),
            "invalid low"
        );
        assert!(bar.volume_micros >= 0, "invalid volume");
        previous_time = bar.time;
    }
}

fn merkle_root(mut leaves: Vec<[u8; 32]>) -> String {
    assert!(!leaves.is_empty(), "empty merkle tree");
    while leaves.len() > 1 {
        if leaves.len() % 2 == 1 {
            leaves.push(*leaves.last().unwrap());
        }
        leaves = leaves
            .chunks_exact(2)
            .map(|pair| {
                let mut hasher = Sha256::new();
                hasher.update(pair[0]);
                hasher.update(pair[1]);
                hasher.finalize().into()
            })
            .collect();
    }
    hex::encode(leaves[0])
}

fn curve_commitment(curve: &[ZkCurvePoint]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASCURVE1");
    hasher.update((curve.len() as u32).to_be_bytes());
    for point in curve {
        hasher.update(point.time.to_be_bytes());
        hasher.update(point.return_ppm.to_be_bytes());
        hasher.update(point.benchmark_return_ppm.to_be_bytes());
    }
    as_hex(hasher)
}

fn ppm_ratio(numerator: i128, denominator: i128) -> i64 {
    ((numerator * MICROS) / denominator) as i64
}

fn f64_to_i64(value: f64, scale: f64) -> i64 {
    let scaled = value * scale;
    if scaled.is_nan() {
        0
    } else if scaled >= i64::MAX as f64 {
        i64::MAX
    } else if scaled <= i64::MIN as f64 {
        i64::MIN
    } else {
        scaled.round() as i64
    }
}

fn calculate_metrics(equity: &[i64], benchmark: &[i64], times: &[i64]) -> ZkMetricSet {
    let initial = equity[0] as f64;
    let final_value = *equity.last().unwrap() as f64;
    let total_return = final_value / initial - 1.0;
    let elapsed_days = (((times[times.len() - 1] - times[0]) as f64) / 86_400.0).max(1.0);
    let annual_factor = (365.0 / elapsed_days).min(10.0);
    let annualized = (final_value / initial).powf(annual_factor) - 1.0;
    let mut returns = Vec::with_capacity(equity.len() - 1);
    for pair in equity.windows(2) {
        returns.push(pair[1] as f64 / pair[0] as f64 - 1.0);
    }
    let mean = returns.iter().sum::<f64>() / returns.len() as f64;
    let variance = if returns.len() > 1 {
        returns
            .iter()
            .map(|value| (value - mean).powi(2))
            .sum::<f64>()
            / (returns.len() - 1) as f64
    } else {
        0.0
    };
    let standard_deviation = variance.sqrt();
    let periods_per_year = ((returns.len() as f64 / elapsed_days) * 365.0).max(1.0);
    let annual_volatility = standard_deviation * periods_per_year.sqrt();
    let sharpe = if standard_deviation > 0.0 {
        mean / standard_deviation * periods_per_year.sqrt()
    } else {
        0.0
    };
    let wins = returns.iter().filter(|value| **value > 0.0).count();
    let mut peak = equity[0];
    let mut max_drawdown_ppm = 0i64;
    for value in equity {
        peak = peak.max(*value);
        max_drawdown_ppm = max_drawdown_ppm.min(ppm_ratio((*value - peak) as i128, peak as i128));
    }
    let benchmark_return = *benchmark.last().unwrap() as f64 / benchmark[0] as f64 - 1.0;
    ZkMetricSet {
        total_return_ppm: f64_to_i64(total_return, 1_000_000.0),
        annualized_return_ppm: f64_to_i64(annualized, 1_000_000.0),
        max_drawdown_ppm,
        annualized_volatility_ppm: f64_to_i64(annual_volatility, 1_000_000.0),
        sharpe_milli: f64_to_i64(sharpe, 1_000.0),
        win_rate_ppm: ((wins as i128 * MICROS) / returns.len() as i128) as i64,
        benchmark_return_ppm: f64_to_i64(benchmark_return, 1_000_000.0),
        observation_count: equity.len() as u32,
    }
}

pub fn execute(witness: StrategyWitness) -> ZkPublicStatement {
    validate_witness(&witness);
    let bars = &witness.market.bars;
    let strategy = &witness.strategy;
    let mut cash = witness.initial_equity_micros as i128;
    let mut quantity_micros = 0i128;
    let mut equities = Vec::with_capacity(bars.len());
    let mut benchmarks = Vec::with_capacity(bars.len());
    let mut times = Vec::with_capacity(bars.len());
    let mut leaves = Vec::with_capacity(bars.len());

    for (index, bar) in bars.iter().enumerate() {
        let signal = if index >= strategy.slow_period as usize {
            let fast_start = index - strategy.fast_period as usize;
            let slow_start = index - strategy.slow_period as usize;
            let fast_sum: i128 = bars[fast_start..index]
                .iter()
                .map(|item| item.close_micros as i128)
                .sum();
            let slow_sum: i128 = bars[slow_start..index]
                .iter()
                .map(|item| item.close_micros as i128)
                .sum();
            fast_sum * strategy.slow_period as i128 > slow_sum * strategy.fast_period as i128
        } else {
            false
        };
        let open = bar.open_micros as i128;
        let equity_at_open = cash + quantity_micros * open / MICROS;
        let target_notional = if signal {
            equity_at_open * strategy.target_position_bps as i128 / BPS
        } else {
            0
        };
        let desired_quantity = target_notional * MICROS / open;
        let delta = desired_quantity - quantity_micros;
        if delta > 0 {
            let execution_price = open * (BPS + strategy.slippage_bps as i128) / BPS;
            let notional = delta * execution_price / MICROS;
            let fee = notional * strategy.commission_bps as i128 / BPS;
            assert!(notional + fee <= cash, "insufficient cash");
            cash -= notional + fee;
            quantity_micros += delta;
        } else if delta < 0 {
            let execution_price = open * (BPS - strategy.slippage_bps as i128) / BPS;
            let notional = (-delta) * execution_price / MICROS;
            let fee = notional * strategy.commission_bps as i128 / BPS;
            cash += notional - fee;
            quantity_micros += delta;
        }
        assert!(
            cash >= 0 && quantity_micros >= 0,
            "long-only invariant failed"
        );
        let equity = cash + quantity_micros * bar.close_micros as i128 / MICROS;
        assert!(
            equity > 0 && equity <= i64::MAX as i128,
            "equity out of range"
        );
        let equity_i64 = equity as i64;
        equities.push(equity_i64);
        benchmarks.push(bar.close_micros);
        times.push(bar.time);
        let mut leaf = Sha256::new();
        leaf.update(b"ATLASDECISION1");
        leaf.update(bar.time.to_be_bytes());
        leaf.update(
            (if signal {
                strategy.target_position_bps
            } else {
                0
            })
            .to_be_bytes(),
        );
        leaf.update((cash as i64).to_be_bytes());
        leaf.update((quantity_micros as i64).to_be_bytes());
        leaf.update(equity_i64.to_be_bytes());
        leaves.push(leaf.finalize().into());
    }

    let step = bars.len().div_ceil(96);
    let mut public_curve = Vec::new();
    for index in (0..bars.len()).step_by(step) {
        public_curve.push(ZkCurvePoint {
            time: times[index],
            return_ppm: ppm_ratio((equities[index] - equities[0]) as i128, equities[0] as i128),
            benchmark_return_ppm: ppm_ratio(
                (benchmarks[index] - benchmarks[0]) as i128,
                benchmarks[0] as i128,
            ),
        });
    }
    if public_curve.last().unwrap().time != *times.last().unwrap() {
        let index = bars.len() - 1;
        public_curve.push(ZkCurvePoint {
            time: times[index],
            return_ppm: ppm_ratio((equities[index] - equities[0]) as i128, equities[0] as i128),
            benchmark_return_ppm: ppm_ratio(
                (benchmarks[index] - benchmarks[0]) as i128,
                benchmarks[0] as i128,
            ),
        });
    }
    assert!(public_curve.len() <= 96, "public curve too large");

    let strategy_hash = strategy_commitment(strategy, &witness.strategy_salt);
    let market_hash = market_commitment(&witness.market);
    let mut nullifier_hasher = Sha256::new();
    nullifier_hasher.update(b"ATLASNULL1");
    nullifier_hasher.update(hex::decode(&strategy_hash).unwrap());
    nullifier_hasher.update(hex::decode(&market_hash).unwrap());
    nullifier_hasher.update(bars[0].time.to_be_bytes());
    nullifier_hasher.update(bars[bars.len() - 1].time.to_be_bytes());
    nullifier_hasher.update(witness.nullifier_nonce);

    ZkPublicStatement {
        schema: "atlas.quantjudge.zk.statement.v1".to_owned(),
        proof_profile: "atlas_sma_backtest_risc0_v1".to_owned(),
        agent_id: witness.agent_id,
        strategy_commitment: strategy_hash,
        workflow_commitment: witness.workflow_commitment,
        market_data_hash: market_hash,
        cost_model_hash: cost_model_commitment(strategy),
        report_type: "backtest".to_owned(),
        period_start: bars[0].time,
        period_end: bars[bars.len() - 1].time,
        initial_equity_micros: witness.initial_equity_micros,
        final_equity_micros: *equities.last().unwrap(),
        decision_count: leaves.len() as u32,
        decision_merkle_root: merkle_root(leaves),
        equity_curve_hash: curve_commitment(&public_curve),
        previous_receipt_hash: witness.previous_receipt_hash,
        nullifier: as_hex(nullifier_hasher),
        metrics: calculate_metrics(&equities, &benchmarks, &times),
        public_curve,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn witness() -> StrategyWitness {
        let bars = (0..40)
            .map(|index| {
                let close = 100_000_000 + index as i64 * 500_000;
                MarketBar {
                    time: 1_700_000_000 + index as i64 * 86_400,
                    open_micros: close - 100_000,
                    high_micros: close + 500_000,
                    low_micros: close - 500_000,
                    close_micros: close,
                    volume_micros: 10_000_000,
                }
            })
            .collect();
        StrategyWitness {
            agent_id: "qja_test_agent".to_owned(),
            workflow_commitment: workflow_commitment(),
            previous_receipt_hash: None,
            strategy_salt: [7; 32],
            nullifier_nonce: [9; 32],
            initial_equity_micros: 100_000_000_000,
            strategy: SmaStrategy {
                fast_period: 5,
                slow_period: 20,
                target_position_bps: 9_000,
                commission_bps: 10,
                slippage_bps: 5,
            },
            market: MarketDataset {
                source: "binance".to_owned(),
                symbol: "BTC-USD".to_owned(),
                interval: "1d".to_owned(),
                adjustment: "raw".to_owned(),
                bars,
            },
        }
    }

    #[test]
    fn deterministic_execution_and_commitments() {
        let one = execute(witness());
        let two = execute(witness());
        assert_eq!(one.strategy_commitment, two.strategy_commitment);
        assert_eq!(one.market_data_hash, two.market_data_hash);
        assert_eq!(one.nullifier, two.nullifier);
        assert_eq!(one.decision_merkle_root, two.decision_merkle_root);
        assert!(one.final_equity_micros > 0);
        assert!(one.public_curve.len() <= 96);
    }
}
