// Versioned programmable guest. The legacy SMA core is intentionally unchanged.
use serde::{Deserialize, Serialize};
use risc0_zkvm::sha::rust_crypto::{Digest, Sha256};

const MICROS: i128 = 1_000_000;
const BPS: i128 = 10_000;

/// Private bounded RPN program; no syscalls, loops, external inputs or float ops.
/// Arithmetic is signed integer arithmetic; prices are micros, output is bps.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Instruction {
    Const(i64), Close(u32), Sma(u32), Index, Load(u8), Store(u8),
    Add, Sub, Mul, Div, Mod, Gt, Lt, Eq, And, Or, Not, Select,
}

impl Instruction {
    fn commit(&self, hash: &mut Sha256) {
        let (tag, value): (u8, i64) = match self {
            Self::Const(v) => (0, *v), Self::Close(v) => (1, *v as i64),
            Self::Sma(v) => (2, *v as i64), Self::Index => (3, 0),
            Self::Load(v) => (4, *v as i64), Self::Store(v) => (5, *v as i64),
            Self::Add => (6, 0), Self::Sub => (7, 0), Self::Mul => (8, 0),
            Self::Div => (9, 0), Self::Mod => (10, 0), Self::Gt => (11, 0),
            Self::Lt => (12, 0), Self::Eq => (13, 0), Self::And => (14, 0),
            Self::Or => (15, 0), Self::Not => (16, 0), Self::Select => (17, 0),
        };
        let mut encoded = [0u8; 9];
        encoded[0] = tag;
        encoded[1..].copy_from_slice(&value.to_be_bytes());
        hash.update(encoded);
    }
}

fn evaluate_cached(program: &[Instruction], closed: &[MarketBar], state: &mut [i128; 16], prefix: &[i128], stack: &mut Vec<i128>) -> u32 {
    assert!(program.len() <= 256);
    stack.clear();
    for instruction in program {
        let result = match instruction {
            Instruction::Const(v) => *v as i128,
            Instruction::Index => closed.len() as i128,
            Instruction::Close(lag) => {
                assert!(*lag <= 500, "lag limit");
                closed.len().checked_sub(*lag as usize + 1)
                    .map(|i| closed[i].close_micros as i128).unwrap_or(0)
            }
            Instruction::Sma(window) => {
                assert!((1..=500).contains(window), "window limit");
                if closed.len() < *window as usize { 0 } else {
                    div_exact(prefix[closed.len()] - prefix[closed.len() - *window as usize], *window as i128)
                }
            }
            Instruction::Load(index) => state[*index as usize],
            Instruction::Store(index) => {
                let value = stack.pop().expect("stack underflow");
                state[*index as usize] = value;
                continue;
            }
            Instruction::Not => (stack.pop().expect("stack underflow") == 0) as i128,
            Instruction::Select => {
                let no = stack.pop().expect("stack underflow");
                let yes = stack.pop().expect("stack underflow");
                let condition = stack.pop().expect("stack underflow");
                if condition != 0 { yes } else { no }
            }
            operation => {
                let b = stack.pop().expect("stack underflow");
                let a = stack.pop().expect("stack underflow");
                match operation {
                    Instruction::Add => a + b, Instruction::Sub => a - b,
                    Instruction::Mul => a * b, Instruction::Div => div_exact(a, b),
                    Instruction::Mod => a % b, Instruction::Gt => (a > b) as i128,
                    Instruction::Lt => (a < b) as i128, Instruction::Eq => (a == b) as i128,
                    Instruction::And => (a != 0 && b != 0) as i128,
                    Instruction::Or => (a != 0 || b != 0) as i128,
                    _ => unreachable!(),
                }
            }
        };
        assert!(result.abs() <= 1_000_000_000_000_000_000, "numeric bound");
        stack.push(result);
        assert!(stack.len() <= 64, "stack limit");
    }
    assert!(stack.len() == 1, "program must return one weight");
    assert!((0..=9500).contains(&stack[0]), "long only 95% risk cap");
    stack[0] as u32
}

#[cfg(test)]
mod program_tests {
    use super::*;
    #[test]
    fn programmable_rules_and_state() {
        let mut state = [0; 16];
        let program = vec![Instruction::Const(5), Instruction::Store(0),
            Instruction::Load(0), Instruction::Const(5), Instruction::Eq,
            Instruction::Const(9000), Instruction::Const(0), Instruction::Select];
        assert_eq!(evaluate(&program, &[], &mut state), 9000);
        assert_eq!(state[0], 5);
    }
    #[test]
    #[should_panic]
    fn rejects_unbounded_exposure() { evaluate(&[Instruction::Const(9501)], &[], &mut [0; 16]); }
    #[test]
    #[should_panic]
    fn rejects_division_by_zero() {
        evaluate(&[Instruction::Const(1), Instruction::Const(0), Instruction::Div], &[], &mut [0; 16]);
    }
    #[test]
    fn commitment_binds_every_instruction() {
        let mut s = ProgramStrategy { program: vec![Instruction::Const(0)], commission_bps: 10, slippage_bps: 5 };
        let old = strategy_commitment(&s, &[1; 32]);
        s.program = vec![Instruction::Const(1)];
        assert_ne!(old, strategy_commitment(&s, &[1; 32]));
    }
}

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
pub struct ProgramStrategy {
    pub program: Vec<Instruction>,
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
    pub strategy: ProgramStrategy,
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

pub fn strategy_commitment(strategy: &ProgramStrategy, salt: &[u8; 32]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASPROGRAM1");
    hasher.update((strategy.program.len() as u32).to_be_bytes());
    for instruction in &strategy.program { instruction.commit(&mut hasher); }
    hasher.update(strategy.commission_bps.to_be_bytes());
    hasher.update(strategy.slippage_bps.to_be_bytes());
    hasher.update(salt);
    as_hex(hasher)
}

pub fn cost_model_commitment(strategy: &ProgramStrategy) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASPROGRAMCOST1");
    hasher.update(strategy.commission_bps.to_be_bytes());
    hasher.update(strategy.slippage_bps.to_be_bytes());
    hasher.update(b"next_open_affordable_long_only:v2");
    as_hex(hasher)
}

pub fn workflow_commitment() -> String {
    let mut hasher = Sha256::new();
    hasher.update(
        b"ATLASWORKFLOW2:closed_market>private_program>long_only_cap_9500bps>affordable_next_open>audit>output",
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
    assert!(!strategy.program.is_empty() && strategy.program.len() <= 256, "invalid program size");
    assert!(strategy.commission_bps <= 1_000, "commission too high");
    assert!(strategy.slippage_bps <= 1_000, "slippage too high");
    assert!(witness.initial_equity_micros > 0, "invalid initial equity");
    assert!(
        witness.market.bars.len() >= 3
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

// The SDK API applies standard SHA-256 padding; no raw/compression-only hashes.
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

fn curve_commitment(curve: &[ZkCurvePoint]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"ATLASCURVE1");
    hasher.update((curve.len() as u32).to_be_bytes());
    for point in curve {
        let mut encoded = [0u8; 24];
        encoded[..8].copy_from_slice(&point.time.to_be_bytes());
        encoded[8..16].copy_from_slice(&point.return_ppm.to_be_bytes());
        encoded[16..].copy_from_slice(&point.benchmark_return_ppm.to_be_bytes());
        hasher.update(encoded);
    }
    as_hex(hasher)
}

fn ppm_ratio(numerator: i128, denominator: i128) -> i64 {
    div_exact(numerator * MICROS, denominator) as i64
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
        win_rate_ppm: div_exact(wins as i128 * MICROS, returns.len() as i128) as i64,
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

    // Validated <=20,000 positive i64 closes: sum fits exactly in i128.
    let prefix = close_prefix(&strategy.program, bars);
    let mut stack = Vec::with_capacity(64);
    let mut state = [0i128; 16];
    for (index, bar) in bars.iter().enumerate() {
        let target_bps = if index == 0 { 0 } else { evaluate_cached(&strategy.program, &bars[..index], &mut state, &prefix, &mut stack) };
        let open = bar.open_micros as i128;
        let equity_at_open = cash + div_exact(quantity_micros * open, MICROS);
        let target_notional = div_exact(equity_at_open * target_bps as i128, BPS);
        let desired_quantity = div_exact(target_notional * MICROS, open);
        let mut delta = desired_quantity - quantity_micros;
        if delta > 0 {
            let execution_price = div_exact(open * (BPS + strategy.slippage_bps as i128), BPS);
            let affordable = div_exact(cash * MICROS * BPS, execution_price * (BPS + strategy.commission_bps as i128));
            delta = delta.min(affordable);
            let notional = div_exact(delta * execution_price, MICROS);
            let fee = div_exact(notional * strategy.commission_bps as i128, BPS);
            assert!(notional + fee <= cash, "insufficient cash");
            cash -= notional + fee;
            quantity_micros += delta;
        } else if delta < 0 {
            let execution_price = div_exact(open * (BPS - strategy.slippage_bps as i128), BPS);
            let notional = div_exact((-delta) * execution_price, MICROS);
            let fee = div_exact(notional * strategy.commission_bps as i128, BPS);
            cash += notional - fee;
            quantity_micros += delta;
        }
        assert!(
            cash >= 0 && quantity_micros >= 0,
            "long-only invariant failed"
        );
        let equity = cash + div_exact(quantity_micros * bar.close_micros as i128, MICROS);
        assert!(
            equity > 0 && equity <= i64::MAX as i128,
            "equity out of range"
        );
        let equity_i64 = equity as i64;
        equities.push(equity_i64);
        benchmarks.push(bar.close_micros);
        times.push(bar.time);
        let mut encoded = [0u8; 50];
        encoded[..14].copy_from_slice(b"ATLASDECISION1");
        encoded[14..22].copy_from_slice(&bar.time.to_be_bytes());
        encoded[22..26].copy_from_slice(&target_bps.to_be_bytes());
        encoded[26..34].copy_from_slice(&(cash as i64).to_be_bytes());
        encoded[34..42].copy_from_slice(&(quantity_micros as i64).to_be_bytes());
        encoded[42..].copy_from_slice(&equity_i64.to_be_bytes());
        leaves.push(hash_bytes_fast(&encoded));
    }

    let step = (bars.len() - 1).div_ceil(95);
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
        proof_profile: "atlas_program_backtest_risc0_v3_experimental".to_owned(),
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

#[cfg(test)]
mod reference;
#[cfg(test)]
mod equivalence;

// The expressions at each call site retain their original i128 operations.
// Checked signed paths preserve truncation; narrow MIN/-1 falls through.
// Out-of-range operands and final overflow/zero rejection retain original i128.
#[inline(always)]
fn div_exact(numerator: i128, denominator: i128) -> i128 {
    if let (Ok(a), Ok(b)) = (u32::try_from(numerator), u32::try_from(denominator)) {
        return (a / b) as i128;
    }
    if let (Ok(a), Ok(b)) = (u64::try_from(numerator), u64::try_from(denominator)) {
        return (a / b) as i128;
    }
    if let (Ok(a), Ok(b)) = (i32::try_from(numerator), i32::try_from(denominator)) {
        if let Some(quotient) = a.checked_div(b) { return quotient as i128; }
    }
    if let (Ok(a), Ok(b)) = (i64::try_from(numerator), i64::try_from(denominator)) {
        if let Some(quotient) = a.checked_div(b) { return quotient as i128; }
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
            i64::MIN as i128, i64::MIN as i128+1, i32::MIN as i128-1, i32::MIN as i128,
            i32::MAX as i128, i32::MAX as i128+1, -7, -3, -1, 0, 1, 3, 7,
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
            compare(a as i32 as i128, state as i32 as i128);
            compare(a as i64 as i128, state as i64 as i128);
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

#[cfg(test)]
mod hash_equivalence;

pub mod word_reader;
