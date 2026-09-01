# Atlas ZKP protocol

Atlas uses a fixed RISC Zero zkVM guest to prove that a private strategy configuration was executed against an exact market dataset under deterministic backtest semantics. A proof is accepted only when the receipt verifies against a platform-registered image ID and every public journal field passes the server-side binding rules.

The first production profile is `atlas_sma_backtest_risc0_v1`. It proves one long-only SMA crossover backtest. It does **not** claim to prove arbitrary Python, an external LLM, live exchange fills, or every Strategy Lab artifact.

## Security claim and trust boundary

For an accepted report, the verifier establishes all of the following:

1. the registered guest program ran successfully;
2. the private SMA parameters and salt open to the public `strategy_commitment`;
3. the complete committed OHLCV dataset was processed in timestamp order;
4. signals use closed bars and orders execute at the next bar open;
5. commission and slippage are charged according to the committed cost model;
6. public metrics, sampled equity curve, decision Merkle root and final equity were produced by that execution;
7. the proof belongs to the Agent, dataset and previous receipt declared in the journal;
8. the nullifier and proof receipt have not been published before.

The platform still controls market-dataset registration and profile governance. The current Binance cache is not a provider-signed oracle, so the proof establishes computation over the registered dataset, not that Binance cryptographically signed each candle. A production oracle should add provider signatures or a separately attested ingestion pipeline.

## Public and private values

| Boundary | Values |
|---|---|
| Private witness | fast/slow SMA periods, strategy salt, full bar sequence, per-bar decisions, full equity path |
| Public journal | profile/schema, fixed image ID binding, Agent ID, strategy/workflow commitments, market/cost hashes, period, bar count, metrics, sampled curve, decision count/root, final equity, previous receipt, nullifier |
| Backend persistence | receipt bytes, public journal, verifier/image metadata, trusted dataset manifest, one-time consumption state |
| Explicitly not persisted | strategy salt, private parameters, source, prompts, full decisions, full equity path, witness file |

Market candles are downloadable by hash because they are the public statement being computed over. Keeping public historical data out of the HTTP API would not make a strategy more private; the parameters and decisions remain inside the witness.

## Deterministic execution profile

`atlas_sma_backtest_risc0_v1` uses integer fixed-point arithmetic for prices, cash and quantities. Risk metrics are calculated inside the deterministic guest and quantized to integer ppm/milli units before publication. The semantics are versioned with the guest image:

- bars must be strictly increasing and valid OHLC candles;
- an SMA is computed only from already-closed bars;
- a crossover produces an intent, and execution occurs at the next bar open;
- the strategy is long-only and cannot spend unavailable cash;
- commission and slippage are committed inputs;
- no network, wall clock, random source or mutable external service exists inside the guest;
- a bounded public curve is sampled from the proved full equity path.

Changing any semantic rule requires a new profile and image ID. Existing profiles remain verifiable and must not be silently repointed to another binary.

## Receipt lifecycle

```text
trusted bars -> market_data_hash
private params + salt -> strategy_commitment
witness -> fixed zkVM guest -> receipt + public journal
receipt -> backend fixed verifier -> verified proof record
verified proof record -> one-time QuantJudge report
report + proof hashes -> Supervisor anchor payload
```

The backend fails closed when the verifier binary, profile registration or exact image ID is unavailable. Browser flags, user-supplied verifier commands and self-declared proof summaries cannot create `evidence_level=zk_verified`.

Proof records are content addressed and protected against path traversal, duplicate receipt hashes and nullifier replay. Publishing consumes one proof atomically and checks the Agent's latest receipt hash again to prevent a forked append chain. Every public report-verification request also reloads the persisted receipt, verifies its file hash, reruns the fixed RISC Zero verifier against the registered image ID, and compares the decoded journal byte-for-byte with the registered public statement; a database `verified` flag alone is never treated as cryptographic evidence.

## Supervisor anchor v2

Supervisor remains read-only to Atlas; none of its source or configuration is modified. For ZKP reports the expected transaction input is:

```text
ASCII("ATLASZK2")
  || bytes32(report_receipt_hash)
  || bytes32(zk_receipt_hash)
  || bytes32(public_inputs_hash)
  || bytes32(nullifier)
```

The existing Supervisor integration anchors these commitments and verifies the transaction input and receipt status. It does not execute the RISC Zero verifier contract on-chain. Anyone can independently download the receipt and journal from Atlas and verify them using the registered image ID.

## Local build and proof generation

Install the RISC Zero toolchain, then build the fixed guest and host verifier:

```bash
PATH="$HOME/.risc0/bin:$PATH" strategy/zkvm/scripts/build.sh
```

The build writes the immutable image ID into `strategy/zkvm/profiles.json`. Generate a witness locally; never upload it:

```bash
strategy/zkvm/target/release/atlas-zkvm inspect --witness witness.json
strategy/zkvm/target/release/atlas-zkvm prove --witness witness.json --receipt receipt.bin
strategy/zkvm/target/release/atlas-zkvm verify --receipt receipt.bin
```

Use the inspect output when creating the QuantJudge Agent, register/download the exact market dataset in Strategy Lab, then upload only `receipt.bin`. The API re-verifies it; the local verify command is a developer convenience, not an authorization decision.

## Production controls

Before a public multi-tenant launch:

- reproduce guest builds in CI and publish image manifests and source tags;
- require reviewed, signed profile-registry changes and preserve revoked profiles for historical verification;
- run the verifier in a dedicated constrained service with request limits and observability;
- keep receipt and journal storage immutable with retention and backup policies;
- sign market ingestion manifests and define data-correction/version rules;
- move platform receipt signing to KMS/HSM with rotation and public key history;
- commission an independent review of the guest arithmetic, economics and host binding code;
- continuously test receipt corruption, journal substitution, replay, stale-chain, wrong-image and resource-exhaustion cases.

## Extension roadmap

Each additional strategy family needs a dedicated deterministic profile, test vectors and image ID. General Python uploads should run in an isolated reproducible runner first and then be proved with a general zkVM execution profile; they are not made private merely by hashing a package. AI nodes require either a reproducible model inside a proving/zkML runtime or an attested TEE whose measurement and signed output are committed into a later proof. Live performance additionally needs signed exchange/custodian fills and an append-only portfolio state transition proof.
