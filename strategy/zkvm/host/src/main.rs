use std::{fs, path::PathBuf};

use anyhow::{bail, Context, Result};
use atlas_zk_core::{execute, StrategyWitness, ZkPublicStatement};
use atlas_zk_methods::{ATLAS_BACKTEST_GUEST_ELF, ATLAS_BACKTEST_GUEST_ID};
use atlas_program_methods::{ATLAS_PROGRAM_GUEST_ELF, ATLAS_PROGRAM_GUEST_ID};
use clap::{Parser, Subcommand};
use risc0_zkvm::{default_prover, ExecutorEnv, Receipt};
use serde_json::json;

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

fn prove(witness_path: PathBuf, receipt_path: PathBuf, profile: String) -> Result<()> {
    let bytes = fs::read(&witness_path)?;
    let is_program = program(&profile)?;
    if is_program && image_id_hex(ATLAS_PROGRAM_GUEST_ID) != "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4" {
        bail!("program build does not reproduce its registered image ID; restore the exact reviewed sources and toolchain, never overwrite a registered profile");
    }
    if !is_program && image_id_hex(ATLAS_BACKTEST_GUEST_ID) != "91409cbbef6fe55f5e7ac6d5199e31d259b4167788facbbb26dc7ee09740ea43" {
        bail!("legacy SMA build does not reproduce its registered image ID; use the separately registered program v2 profile, never overwrite v1");
    }
    let (env, elf, id) = if is_program {
        let witness: atlas_program_core::StrategyWitness = serde_json::from_slice(&bytes)?;
        (ExecutorEnv::builder().write(&witness)?.build()?, ATLAS_PROGRAM_GUEST_ELF, ATLAS_PROGRAM_GUEST_ID)
    } else {
        let witness: StrategyWitness = serde_json::from_slice(&bytes)?;
        (ExecutorEnv::builder().write(&witness)?.build()?, ATLAS_BACKTEST_GUEST_ELF, ATLAS_BACKTEST_GUEST_ID)
    };
    let receipt = default_prover()
        .prove(env, elf)
        .context("generate production proof")?
        .receipt;
    receipt.verify(id)?;
    fs::write(&receipt_path, bincode::serialize(&receipt)?)
        .with_context(|| format!("write {}", receipt_path.display()))?;
    let statement: ZkPublicStatement = receipt.journal.decode()?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "valid": true,
            "image_id": image_id_hex(id),
            "proof_profile": statement.proof_profile,
            "journal": statement,
        }))?
    );
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
    let bytes = fs::read(&witness_path)?;
    let statement = if program(&profile)? {
        serde_json::to_value(atlas_program_core::execute(serde_json::from_slice(&bytes)?))?
    } else { serde_json::to_value(execute(serde_json::from_slice(&bytes)?))? };
    println!("{}", serde_json::to_string_pretty(&statement)?);
    Ok(())
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Prove { witness, receipt, profile } => prove(witness, receipt, profile),
        Command::Verify {
            receipt,
            expected_image_id,
        } => verify(receipt, expected_image_id),
        Command::Inspect { witness, profile } => inspect(witness, profile),
        Command::Profile { profile: profile_id } => profile(profile_id),
    }
}
