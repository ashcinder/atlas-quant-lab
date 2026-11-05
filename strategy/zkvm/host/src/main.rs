use std::{fs, io::Read, path::{Path, PathBuf}, time::Instant};

use anyhow::{bail, Context, Result};
use atlas_zk_core::{execute, StrategyWitness, ZkPublicStatement};
use atlas_zk_methods::{ATLAS_BACKTEST_GUEST_ELF, ATLAS_BACKTEST_GUEST_ID};
use atlas_program_methods::{ATLAS_PROGRAM_GUEST_ELF, ATLAS_PROGRAM_GUEST_ID};
use clap::{Parser, Subcommand};
use risc0_zkvm::{get_prover_server, ExecutorEnv, ExecutorImpl, ProverOpts, Receipt, Segment, SessionEvents, VerifierContext};
use serde_json::json;

const EXPERIMENTAL_PROFILE: &str = "atlas_program_backtest_risc0_v3_experimental";
const MAX_PROOF_INPUT_BYTES: u64 = 16 * 1024 * 1024;

fn read_witness(path: &Path) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    fs::File::open(path)?.take(MAX_PROOF_INPUT_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_PROOF_INPUT_BYTES { bail!("proof input exceeds 16MiB"); }
    Ok(bytes)
}

fn validate_market_text(values: [&str; 4], bars: usize) -> Result<()> {
    for (name, value) in ["source", "symbol", "interval", "adjustment"].iter().zip(values) {
        if value.len() > 4096 { bail!("market {name} exceeds 4096 UTF-8 bytes"); }
    }
    if !(3..=20_000).contains(&bars) { bail!("market requires 3..20000 bars"); }
    Ok(())
}

macro_rules! validate_market {
    ($w:expr) => {
        validate_market_text([&$w.market.source, &$w.market.symbol, &$w.market.interval,
                              &$w.market.adjustment], $w.market.bars.len())?
    };
}

#[derive(Parser)]
#[command(
    name = "atlas-zkvm",
    version,
    about = "Atlas registered RISC Zero prover/verifier"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Prove {
        #[arg(long, default_value = "atlas_sma_backtest_risc0_v1")]
        profile: String,
        #[arg(long)]
        witness: PathBuf,
        #[arg(long)]
        receipt: PathBuf,
        /// Maximum cycles per proving segment, as a power of two.
        #[arg(long, default_value_t = 20, value_parser = clap::value_parser!(u32).range(16..=20))]
        segment_limit_po2: u32,
        #[arg(long)]
        segment_path: Option<PathBuf>,
    },
    /// Execute the complete guest and report cycles; does not generate a proof.
    Analyze {
        #[arg(long, default_value = "atlas_sma_backtest_risc0_v1")]
        profile: String,
        #[arg(long)]
        witness: PathBuf,
        #[arg(long, default_value_t = 20, value_parser = clap::value_parser!(u32).range(16..=20))]
        segment_limit_po2: u32,
        #[arg(long)]
        segment_path: Option<PathBuf>,
    },
    Verify {
        #[arg(long)]
        receipt: PathBuf,
        #[arg(long)]
        expected_image_id: String,
    },
    Inspect {
        #[arg(long, default_value = "atlas_sma_backtest_risc0_v1")]
        profile: String,
        #[arg(long)]
        witness: PathBuf,
    },
    Profile {
        #[arg(long, default_value = "atlas_sma_backtest_risc0_v1")]
        profile: String,
    },
}

fn image_id_hex(id: [u32; 8]) -> String {
    let bytes: Vec<u8> = id
        .iter()
        .flat_map(|word| word.to_le_bytes())
        .collect();
    hex::encode(bytes)
}

fn program(profile: &str) -> Result<bool> {
    match profile {
        "atlas_sma_backtest_risc0_v1" => Ok(false),
        "atlas_program_backtest_risc0_v2" => Ok(true),
        _ => bail!("unregistered profile"),
    }
}

struct SegmentProgress(Instant);

impl SessionEvents for SegmentProgress {
    fn on_post_prove_segment(&self, segment: &Segment) {
        // No witness values, strategy code, or journal in progress diagnostics.
        eprintln!("segment_completed={} po2={} proving_elapsed_seconds={:.3}",
                  segment.index, segment.po2(), self.0.elapsed().as_secs_f64());
    }
}

fn execution(witness_path: PathBuf, profile: &str, segment_limit_po2: u32, segment_path: Option<PathBuf>)
    -> Result<(ExecutorEnv<'static>, &'static [u8], [u32; 8], serde_json::Value)> {
    let started = Instant::now();
    let bytes = read_witness(&witness_path)?;
    let read_seconds = started.elapsed().as_secs_f64();
    let is_program = program(profile)?;
    if is_program && image_id_hex(ATLAS_PROGRAM_GUEST_ID) != "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4" {
        bail!("program build does not reproduce its registered image ID; restore the exact reviewed sources and toolchain, never overwrite a registered profile");
    }
    if !is_program && image_id_hex(ATLAS_BACKTEST_GUEST_ID) != "91409cbbef6fe55f5e7ac6d5199e31d259b4167788facbbb26dc7ee09740ea43" {
        bail!("legacy SMA build does not reproduce its registered image ID; use the separately registered program v2 profile, never overwrite v1");
    }
    let mut builder = ExecutorEnv::builder();
    builder.segment_limit_po2(segment_limit_po2);
    if let Some(path) = segment_path {
        if !path.is_dir() { bail!("segment directory must already exist"); }
        builder.segment_path(path);
    }
    let parse_started = Instant::now();
    let parse_seconds;
    let serialization_started;
    let (elf, id) = if is_program {
        let witness: atlas_program_core::StrategyWitness = serde_json::from_slice(&bytes)?;
        validate_market!(witness);
        parse_seconds = parse_started.elapsed().as_secs_f64();
        serialization_started = Instant::now();
        builder.write(&witness)?;
        (ATLAS_PROGRAM_GUEST_ELF, ATLAS_PROGRAM_GUEST_ID)
    } else {
        let witness: StrategyWitness = serde_json::from_slice(&bytes)?;
        validate_market!(witness);
        parse_seconds = parse_started.elapsed().as_secs_f64();
        serialization_started = Instant::now();
        builder.write(&witness)?;
        (ATLAS_BACKTEST_GUEST_ELF, ATLAS_BACKTEST_GUEST_ID)
    };
    let serialization_seconds = serialization_started.elapsed().as_secs_f64();
    // Also check the ELF itself when packaging with prebuilt guests.
    if risc0_zkvm::compute_image_id(elf)? != id.into() {
        bail!("embedded guest does not match its registered image ID");
    }
    Ok((builder.build()?, elf, id, json!({
        "input_bytes": bytes.len(), "read_seconds": read_seconds,
        "json_parse_seconds": parse_seconds, "serialization_seconds": serialization_seconds,
        "total_seconds": started.elapsed().as_secs_f64(),
    })))
}

fn prove(witness_path: PathBuf, receipt_path: PathBuf, profile: String, segment_limit_po2: u32, segment_path: Option<PathBuf>) -> Result<()> {
    let started = Instant::now();
    let (env, elf, id, prepare) = execution(witness_path, &profile, segment_limit_po2, segment_path)?;
    // The same SDK local path as LocalProver, split only to time its stages.
    // Keep all segments in one Session so SDK continuation verification applies.
    let stage = Instant::now();
    let mut session = ExecutorImpl::from_elf(env, elf)?.run()?;
    let execution_seconds = stage.elapsed().as_secs_f64();
    let stage = Instant::now();
    session.add_hook(SegmentProgress(stage));
    let info = get_prover_server(&ProverOpts::default())?
        .prove_session(&VerifierContext::default(), &session)
        .context("generate production proof")?;
    let proving_seconds = stage.elapsed().as_secs_f64();
    let receipt = info.receipt;
    let stage = Instant::now();
    receipt.verify(id)?;
    let verification_seconds = stage.elapsed().as_secs_f64();
    let stage = Instant::now();
    fs::write(&receipt_path, bincode::serialize(&receipt)?)
        .with_context(|| format!("write {}", receipt_path.display()))?;
    let receipt_write_seconds = stage.elapsed().as_secs_f64();
    let statement: ZkPublicStatement = receipt.journal.decode()?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "valid": true,
            "image_id": image_id_hex(id),
            "proof_profile": statement.proof_profile,
            "journal": statement,
            "stats": info.stats,
            "segment_limit_po2": segment_limit_po2,
            "elapsed_seconds": started.elapsed().as_secs_f64(),
            "timings": {"prepare": prepare, "execution_seconds": execution_seconds,
                "proving_seconds": proving_seconds, "verification_seconds": verification_seconds,
                "receipt_write_seconds": receipt_write_seconds},
        }))?
    );
    Ok(())
}

fn analyze(witness_path: PathBuf, profile: String, segment_limit_po2: u32, segment_path: Option<PathBuf>) -> Result<()> {
    let started = Instant::now();
    let (env, elf, id, prepare) = execution(witness_path, &profile, segment_limit_po2, segment_path)?;
    let stage = Instant::now();
    let session = ExecutorImpl::from_elf(env, elf)?.run()?;
    let execution_seconds = stage.elapsed().as_secs_f64();
    let statement: ZkPublicStatement = session.journal.as_ref().context("missing journal")?.decode()?;
    let segments = session.segments.iter().map(|s| {
        let segment = s.resolve()?;
        Ok(json!({"po2": segment.po2()}))
    }).collect::<Result<Vec<_>>>()?;
    println!("{}", serde_json::to_string(&json!({
        "execution_only": true,
        "image_id": image_id_hex(id),
        "journal": statement,
        "stats": session.stats(),
        "segments": segments,
        "timings": {"prepare": prepare, "execution_seconds": execution_seconds},
        "segment_limit_po2": segment_limit_po2,
        "elapsed_seconds": started.elapsed().as_secs_f64(),
    }))?);
    Ok(())
}

fn verify(receipt_path: PathBuf, expected_image_id: String) -> Result<()> {
    // Verification does not need the guest ELF. The HTTP boundary selects this
    // ID from its immutable registry, not from untrusted uploaded metadata.
    let digest = hex::decode(&expected_image_id).context("invalid expected image ID")?;
    if digest.len() != 32 || expected_image_id != expected_image_id.to_lowercase() {
        bail!("expected image ID must be 32 lowercase hexadecimal bytes");
    }
    let mut id = [0u32; 8];
    for (word, chunk) in id.iter_mut().zip(digest.chunks_exact(4)) {
        *word = u32::from_le_bytes(chunk.try_into().unwrap());
    }
    let image_id = image_id_hex(id);
    let bytes =
        fs::read(&receipt_path).with_context(|| format!("read {}", receipt_path.display()))?;
    let receipt: Receipt = bincode::deserialize(&bytes).context("decode receipt")?;
    receipt
        .verify(id)
        .context("cryptographic receipt verification")?;
    let statement: ZkPublicStatement = receipt.journal.decode().context("decode journal")?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "valid": true,
            "image_id": image_id,
            "receipt_kind": "risc0-receipt",
            "verifier_version": env!("CARGO_PKG_VERSION"),
            "journal": statement,
        }))?
    );
    Ok(())
}

fn profile(profile_id: String) -> Result<()> {
    let is_program = program(&profile_id)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "id": profile_id,
            "image_id": image_id_hex(if is_program { ATLAS_PROGRAM_GUEST_ID } else { ATLAS_BACKTEST_GUEST_ID }),
            "status": "active",
            "proof_system": "risc0-zkvm",
            "guest_version": if is_program { "0.2.0" } else { env!("CARGO_PKG_VERSION") },
            "scope": if is_program { "private_bounded_integer_program_long_only_backtest" } else { "deterministic_sma_long_only_backtest" },
        }))?
    );
    Ok(())
}

fn inspect(witness_path: PathBuf, profile: String) -> Result<()> {
    // Read-only replay of the exact frozen experiment, as in the experimental
    // driver. This is never a proving path or an arbitrary profile fallback.
    let experimental = profile == EXPERIMENTAL_PROFILE;
    // Legacy public-example replay is verification, not new generation. Keep
    // its previous input semantics; new generation is bounded above and by the
    // author/paid entrypoints before calling this native preflight.
    let bytes = if experimental { read_witness(&witness_path)? } else { fs::read(&witness_path)? };
    let mut statement = if experimental || program(&profile)? {
        let witness: atlas_program_core::StrategyWitness = serde_json::from_slice(&bytes)?;
        if experimental { validate_market!(witness); }
        serde_json::to_value(atlas_program_core::execute(witness))?
    } else {
        let witness: StrategyWitness = serde_json::from_slice(&bytes)?;
        serde_json::to_value(execute(witness))?
    };
    if experimental { statement["proof_profile"] = json!(EXPERIMENTAL_PROFILE); }
    println!("{}", serde_json::to_string_pretty(&statement)?);
    Ok(())
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Prove { witness, receipt, profile, segment_limit_po2, segment_path } => prove(witness, receipt, profile, segment_limit_po2, segment_path),
        Command::Analyze { witness, profile, segment_limit_po2, segment_path } => analyze(witness, profile, segment_limit_po2, segment_path),
        Command::Verify {
            receipt,
            expected_image_id,
        } => verify(receipt, expected_image_id),
        Command::Inspect { witness, profile } => inspect(witness, profile),
        Command::Profile { profile: profile_id } => profile(profile_id),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use risc0_zkvm::{FakeReceipt, InnerReceipt, ReceiptClaim};

    #[test]
    fn experimental_replay_is_not_a_registered_prover() {
        assert!(program(EXPERIMENTAL_PROFILE).is_err());
        assert!(program("atlas_program_backtest_risc0_v3_other").is_err());
    }

    #[test]
    fn metadata_limit_is_utf8_bytes_and_preserves_bar_limit() {
        let legal = "行".repeat(1365) + "x";
        assert!(validate_market_text([&legal, "T", "1d", "none"], 20_000).is_ok());
        assert!(validate_market_text([&(legal + "x"), "T", "1d", "none"], 3).is_err());
        assert!(validate_market_text(["s", "T", "1d", "none"], 20_001).is_err());
    }

    #[test]
    fn packaged_guests_match_the_immutable_registry() {
        assert_eq!(image_id_hex(ATLAS_PROGRAM_GUEST_ID), "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4");
        assert_eq!(risc0_zkvm::compute_image_id(ATLAS_PROGRAM_GUEST_ELF).unwrap(), ATLAS_PROGRAM_GUEST_ID.into());
        assert_eq!(risc0_zkvm::compute_image_id(ATLAS_BACKTEST_GUEST_ELF).unwrap(), ATLAS_BACKTEST_GUEST_ID.into());
    }

    #[test]
    fn development_receipt_is_rejected() {
        let receipt = Receipt::new(
            InnerReceipt::Fake(FakeReceipt::new(ReceiptClaim::ok(ATLAS_PROGRAM_GUEST_ID, vec![]))),
            vec![],
        );
        // disable-dev-mode rejects a forged receipt even if the caller supplies
        // RISC0_DEV_MODE=1 (the SDK deliberately panics for that combination).
        let verified = std::panic::catch_unwind(|| receipt.verify(ATLAS_PROGRAM_GUEST_ID));
        assert!(verified.map_or(true, |result| result.is_err()));
    }

    #[test]
    #[ignore = "requires ATLAS_REAL_RECEIPT_TEST_PATH pointing to a genuine multi-segment v2 proof"]
    fn rejects_missing_reordered_and_replaced_segments() {
        let path = std::env::var("ATLAS_REAL_RECEIPT_TEST_PATH").unwrap();
        let original: Receipt = bincode::deserialize(&fs::read(path).unwrap()).unwrap();
        original.verify(ATLAS_PROGRAM_GUEST_ID).unwrap();
        for mutation in 0..3 {
            let mut receipt = original.clone();
            let InnerReceipt::Composite(ref mut composite) = receipt.inner else { panic!("expected composite"); };
            assert!(composite.segments.len() >= 2);
            match mutation {
                0 => { composite.segments.remove(0); },
                1 => composite.segments.swap(0, 1),
                _ => { composite.segments[0] = composite.segments[1].clone(); },
            }
            assert!(receipt.verify(ATLAS_PROGRAM_GUEST_ID).is_err(), "mutation {mutation} accepted");
        }
    }
}
