use std::{fs, path::PathBuf};

use anyhow::{bail, Context, Result};
use atlas_zk_core::{execute, StrategyWitness, ZkPublicStatement};
use atlas_zk_methods::{ATLAS_BACKTEST_GUEST_ELF, ATLAS_BACKTEST_GUEST_ID};
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
        #[arg(long)]
        witness: PathBuf,
    },
    Profile,
}

fn image_id_hex() -> String {
    let bytes: Vec<u8> = ATLAS_BACKTEST_GUEST_ID
        .iter()
        .flat_map(|word| word.to_le_bytes())
        .collect();
    hex::encode(bytes)
}

fn prove(witness_path: PathBuf, receipt_path: PathBuf) -> Result<()> {
    let witness: StrategyWitness = serde_json::from_slice(
        &fs::read(&witness_path).with_context(|| format!("read {}", witness_path.display()))?,
    )
    .context("parse witness JSON")?;
    let env = ExecutorEnv::builder().write(&witness)?.build()?;
    let receipt = default_prover()
        .prove(env, ATLAS_BACKTEST_GUEST_ELF)
        .context("generate production proof")?
        .receipt;
    receipt.verify(ATLAS_BACKTEST_GUEST_ID)?;
    fs::write(&receipt_path, bincode::serialize(&receipt)?)
        .with_context(|| format!("write {}", receipt_path.display()))?;
    let statement: ZkPublicStatement = receipt.journal.decode()?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "valid": true,
            "image_id": image_id_hex(),
            "proof_profile": statement.proof_profile,
            "journal": statement,
        }))?
    );
    Ok(())
}

fn verify(receipt_path: PathBuf, expected_image_id: String) -> Result<()> {
    let image_id = image_id_hex();
    if expected_image_id != image_id {
        bail!("expected image id does not match the compiled registered guest");
    }
    let bytes =
        fs::read(&receipt_path).with_context(|| format!("read {}", receipt_path.display()))?;
    let receipt: Receipt = bincode::deserialize(&bytes).context("decode receipt")?;
    receipt
        .verify(ATLAS_BACKTEST_GUEST_ID)
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

fn profile() -> Result<()> {
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "id": "atlas_sma_backtest_risc0_v1",
            "image_id": image_id_hex(),
            "status": "active",
            "proof_system": "risc0-zkvm",
            "guest_version": env!("CARGO_PKG_VERSION"),
            "scope": "deterministic_sma_long_only_backtest",
        }))?
    );
    Ok(())
}

fn inspect(witness_path: PathBuf) -> Result<()> {
    let witness: StrategyWitness = serde_json::from_slice(
        &fs::read(&witness_path).with_context(|| format!("read {}", witness_path.display()))?,
    )
    .context("parse witness JSON")?;
    let statement = execute(witness);
    println!("{}", serde_json::to_string_pretty(&statement)?);
    Ok(())
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Prove { witness, receipt } => prove(witness, receipt),
        Command::Verify {
            receipt,
            expected_image_id,
        } => verify(receipt, expected_image_id),
        Command::Inspect { witness } => inspect(witness),
        Command::Profile => profile(),
    }
}
