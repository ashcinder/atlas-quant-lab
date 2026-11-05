use atlas_program_core::{execute, StrategyWitness};
use risc0_zkvm::guest::env;
use serde::Deserialize;

fn main() {
    let input = atlas_program_core::word_reader::WordReader::new(env::stdin());
    let witness = StrategyWitness::deserialize(&mut risc0_zkvm::serde::Deserializer::new(input)).unwrap();
    env::commit(&execute(witness));
}
