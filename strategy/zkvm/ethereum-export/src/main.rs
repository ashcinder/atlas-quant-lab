use anyhow::{ensure, Result};
use risc0_zkvm::{default_prover, sha::Digest, ProverOpts, Receipt};
use std::{env,fs,path::Path};

fn main() -> Result<()> {
    let args:Vec<String> = env::args().collect();
    ensure!(args.len()==4,"usage: exporter receipt.r0 expected-image-id output.json");
    ensure!(!Path::new(&args[3]).exists(),"output already exists");
    let image = Digest::try_from(hex::decode(&args[2])?).map_err(|_| anyhow::anyhow!("image must be 32 bytes"))?;
    let receipt:Receipt = bincode::deserialize(&fs::read(&args[1])?)?;
    receipt.verify(image)?;
    // Compress the existing proof, never rerun or expose private strategy inputs.
    let compressed = default_prover().compress(&ProverOpts::groth16(), &receipt)?;
    compressed.verify(image)?;
    ensure!(compressed.journal.bytes == receipt.journal.bytes,"journal changed");
    let groth16 = compressed.inner.groth16()?;
    let mut seal = groth16.verifier_parameters.as_bytes()[..4].to_vec();
    seal.extend_from_slice(&groth16.seal);
    let output = serde_json::json!({"imageId":format!("0x{}",image),
        "seal":format!("0x{}",hex::encode(seal)),
        "journal":format!("0x{}",hex::encode(&compressed.journal.bytes)),
        "locallyVerified":true,"onchainVerified":false});
    fs::write(&args[3],serde_json::to_vec_pretty(&output)?)?;
    println!("Verified Groth16 export written; no chain confirmation claimed");
    Ok(())
}
