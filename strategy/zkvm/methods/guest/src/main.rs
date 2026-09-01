use atlas_zk_core::{execute, StrategyWitness};
use risc0_zkvm::guest::env;

fn main() {
    let witness: StrategyWitness = env::read();
    let statement = execute(witness);
    env::commit(&statement);
}
