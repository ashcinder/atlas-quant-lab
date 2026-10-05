# Atlas local Supervisor source

This is the MIT-licensed `brokerchain-supervisor` source supplied for the Atlas development test on 2026-09-30. `LICENSE` retains the upstream notice. It is included so a clean checkout can build and validate the loopback, test-only chain without another checkout at a machine-specific path.

Before inclusion, the unreachable upstream cloud credential helper was removed and the SMTP helper was disabled with `contracts/isolated-supervisor/scripts/sanitize-copy.py`; the reviewed bootstrap patch and the two overlay files were applied. `config/config.yml` was replaced with local placeholder values, with historical credential comments removed. `.git`, IDE state, generated binaries, local logs, databases, and private keys were excluded. The source is marked `.atlas-hardened` so the validation runner does not apply the patch twice. The original supplied directory was not edited.

Use `contracts/isolated-supervisor/scripts/run-validation.sh` or the root `start.sh`; do not launch upstream `main.go` against an existing database. The local bootstrap seeds test balances in a fresh isolated database. It does not prove production consensus or crash atomicity across MySQL, trie, and block storage, and must not be connected to formal Atlas data or an existing paid order from another genesis.
