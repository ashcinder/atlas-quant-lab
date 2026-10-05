# Isolated Supervisor bootstrap

This package creates a fresh local MySQL database and an RPC-only Supervisor copy for Atlas development acceptance. It uses the sanitized, patched source in `contracts/supervisor-src` by default, copies it into a private temporary directory, never connects to any existing Supervisor database, and binds MySQL and JSON-RPC to `127.0.0.1`.

The bootstrap command migrates the upstream Supervisor models plus a persistent account nonce table, seeds `roothash`, `gasprice`, `shardid`, and three test-only accounts, then starts `BuildBlockChain` plus `RunEthRpc`. It intentionally does not start the HTTP facade, schedulers, PBFT listeners, claim faucet, or 24-hour workload.

The source patch:

- gives both genesis constructors a positive UTC creation timestamp that is persisted with the chain;
- corrects the invalid `type:string` GORM tag that prevents `contract_invoke` creation on a clean MySQL database;
- returns the signed raw transaction hash, rejects the wrong chain ID, and makes duplicate submission idempotent;
- returns a JSON-RPC error object instead of a null error;
- enforces a literal loopback RPC address in Go and rejects browser Origin headers;
- persists account nonce with successful balances and receipt rows, rejects stale/future nonce, wrong chain/type/gas price and insufficient value-plus-fee balance;
- executes `eth_call` with SQL rollback and a throwaway state snapshot, without receipt/root/block writes;
- uses unique account/config/receipt indexes and password-protected MySQL root, with networking disabled until root is secured.

Run the complete empty-database, signed-transfer, duplicate-submit, stop/restart, and persistence check with:

```bash
contracts/isolated-supervisor/scripts/run-validation.sh
```

The script copies `contracts/supervisor-src` into a new mode-0700 `/tmp/atlas-supervisor-remediation-*` directory. A new random payer wallet is stored only in that directory as a mode-0600 file. The repository receives only the sanitized JSON report under `results/`; it contains public test addresses and transaction/block hashes, never a private key or database password. All processes started by the script are stopped when validation finishes, while the temporary directory is retained for diagnosis.

Optional environment variables select unused ports or an explicit temporary/result path:

```bash
ATLAS_SUPERVISOR_MYSQL_PORT=19316 \
ATLAS_SUPERVISOR_RPC_PORT=42519 \
ATLAS_SUPERVISOR_RUN_ROOT=/tmp/atlas-supervisor-remediation-manual \
ATLAS_SUPERVISOR_RESULT_FILE=/absolute/path/result.json \
contracts/isolated-supervisor/scripts/run-validation.sh
```

`ATLAS_SUPERVISOR_SOURCE` may point to an external upstream checkout for reapplying the sanitizer, patch, and overlay in a disposable copy. The repository source has already received those changes and is marked `.atlas-hardened`; it is never patched twice. `./start.sh` uses this validation runner with `ATLAS_SUPERVISOR_KEEP_RUNNING=1`, then points the local Atlas API at its loopback RPC. The resulting chain is new test state each time and cannot satisfy orders bound to another chain's genesis hash.

This is an isolated development chain with test balances seeded directly into its new database. A successful result proves only that this copied Supervisor can bootstrap, accept one locally signed chain-1051 transfer, and preserve that state across restart. It does not establish compatibility with an existing Supervisor network, production consensus, live asset custody, price provenance, or TEE/zkTLS behavior.

For a subsequent local integration test, the script can deliberately leave the validated MySQL and Supervisor processes running:

```bash
ATLAS_SUPERVISOR_KEEP_RUNNING=1 \
contracts/isolated-supervisor/scripts/run-validation.sh
```

The command still uses fresh state, performs the restart validation first, and writes `supervisor.pid` plus `mysql-launch.pid` under the printed diagnostics directory. The caller must reuse the printed loopback RPC port and read the mode-0600 wallet/database secrets only from that directory. Stop the retained processes after the integration test with `kill "$(cat <run-root>/supervisor.pid)"` followed by `/usr/local/mysql/bin/mysqladmin --defaults-extra-file=<run-root>/secrets/mysql-root.cnf shutdown`. The default remains `ATLAS_SUPERVISOR_KEEP_RUNNING=0`, which stops both processes before returning.

## Validation boundary and upstream findings

The 2026-09-30 hardened validation also exercises wrong nonce/chain/gas price, insufficient balance, stale-nonce re-signing, Origin rejection, read-only value calls, and nonce persistence. The runner uses `exec` so stop/restart targets the actual Supervisor process. Earlier pre-hardening restart results were invalidated after an orphan process was found; only a fresh successful hardened run establishes restart evidence.

This does **not** prove crash atomicity across MySQL, the state trie, and the block store; arbitrary process-kill recovery, contract deployment, malicious contract call behavior, and consensus remain pending. Keep this RPC isolated and use only newly generated test wallets. It is not a production chain migration.

The supplied upstream security helper contains unreachable hardcoded cloud credentials. `sanitize-copy.py` removes that helper body and its unused cloud imports in the private build copy, retaining the existing immediate-true behavior. The original upstream source is not changed; its owner must revoke/rotate any real credentials. Never publish the supplied source or private diagnostic directories.
