use atlas_program_core::{execute, StrategyWitness};
use risc0_zkvm::guest::env;

fn main() {
    let witness: StrategyWitness = env::read();
    env::commit(&execute(witness));
}
