# Atlas Strategy Lab

Atlas Strategy Lab is the unified development and validation plane behind QuantJudge. Its single lifecycle combines safe rule construction, AI workflow composition, IS/OOS and walk-forward validation, private version packages, and the developer SDK while keeping execution results auditable. QuantJudge remains the marketplace and publishing plane.

## Which strategy format should I use?

| Format | Best for | Production path | Notes |
|---|---|---|---|
| Python SDK | research teams and full portfolio logic | isolated runner | Native Atlas format; typed event and portfolio contracts |
| JSON rule DSL | no-code and simple technical rules | safe interpreter | No arbitrary code; easiest to inspect and reproduce |
| Remote Runner contract | proprietary or C++/Rust/institutional systems | signed HTTPS/gRPC adapter | Source never reaches Atlas; only signed inputs and decisions cross the boundary |
| ZK-native profile | privacy-preserving, publicly scored strategies | fixed reviewed zkVM guest | Phase 1 supports deterministic long-only SMA only; every new family needs a new image ID |
| Pine Script | TradingView prototypes | importer/converter | Import target, not the production runtime |
| Jupyter Notebook | exploration and reports | research attachment | Not deterministic enough to be a live strategy artifact |
| MQL/other broker scripts | existing broker strategies | adapter/converter | Convert signals or expose a private Runner |

The native `.qstrategy` file is a ZIP archive. Its root contains `strategy.json`; Python packages also include the declared entry module, JSON DSL packages include `rules.json`, and remote packages include `runner-contract.json`.

```text
risk_aware_momentum.qstrategy
├── strategy.json          # identity, permissions, parameters, validation policy
├── strategy.py            # private BaseStrategy implementation
├── README.md              # developer-only documentation
└── tests/…                # optional deterministic tests
```

Build the included example:

```bash
python tools/package_strategy.py examples/strategies/risk_aware_momentum
```

## Professional strategy “trunk”

Every workflow starts from a versioned directed acyclic graph:

```text
market data → causal features → strategy → baseline sizing
            → optional AI nodes → deterministic hard risk
            → execution/costs → audit commitments → results
```

The professional baseline includes next-bar execution, transaction cost configuration, corporate-action adjustment, deterministic risk, decision commitments, and an output receipt. A workflow may branch for reviews, but every decision-to-execution path must cross a hard-risk node. The API rejects reverse-stage edges, cycles, disabled-node edges, unaudited execution, and any hard-risk bypass.

## AI responsibilities and permissions

AI is an untrusted, typed workflow participant—not an unrestricted trading process.

| Role | Typical input | Allowed authority |
|---|---|---|
| Market regime | returns, volatility, liquidity state | advice or veto |
| Signal review | baseline signals and causal evidence | advice, veto, or bounded adjustment |
| Position management | baseline target weights and constraints | advice or bounded adjustment |
| Risk control | exposures, correlations, stress evidence | advice, veto, or bounded adjustment |
| Execution review | order intent and liquidity | advice or veto |

Each AI node declares a server-side `provider_ref`, timeout, failure policy, structured output, and—where applicable—the maximum adjustment in basis points. API keys and tokens are rejected from workflow documents. Use `deny` for a fail-closed risk officer, `use_baseline` when deterministic output remains acceptable, and `skip` only for advisory nodes. Regardless of AI authority, the deterministic hard-risk gate clamps positions, gross exposure, loss, drawdown, and participation limits afterward.

## Research and promotion gates

A package declares a research protocol. The default industrial baseline requires:

- a chronological holdout set of at least 20%;
- walk-forward validation;
- commissions, spread/slippage, and realistic execution timing;
- at least 30 trades before risk-adjusted metrics are trusted;
- bull, bear, sideways, and preferably high-volatility regime reports;
- parameter-count review to control overfitting.

Notebook results and in-sample metrics never promote a package to live status by themselves. Backtest and live results must reference the strategy version/content hash, workflow graph hash, market-data hash, and an append-only decision commitment chain.

## Strategy Project: the lifecycle spine

The Strategy Lab does not treat the rule builder, AI workflow and research screen as unrelated tools. A **Strategy Project** is the versioned aggregate that binds their immutable artifacts into one reproducible research line:

```text
falsifiable hypothesis
  -> rule / private package content hash
  -> AI workflow graph hash + deterministic hard-risk gate
  -> OOS and walk-forward research job
  -> frozen semantic version + commitment hash
  -> QuantJudge publication candidate
```

Create a project before editing a strategy. Record one testable hypothesis, a fixed asset and interval, benchmark, and primary objective. Saving a visual rule, workflow, research result or package attaches only its identifier and content hash to the project; private source, prompts and raw decisions are not copied into the project row. Changing the hypothesis, asset, interval, benchmark or objective increments the project revision and invalidates incompatible validation or a previously frozen version.

Promotion is controlled by server-derived gates. The browser cannot mark them complete manually. The current baseline requires:

1. a falsifiable hypothesis;
2. a bound strategy artifact;
3. a valid workflow with at least one deterministic hard-risk gate;
4. a completed OOS research result using non-zero commission and slippage;
5. the robustness threshold to pass;
6. at least three completed walk-forward windows;
7. at least 30 out-of-sample trades;
8. an immutable semantic version commitment.

The project API uses optimistic concurrency. Every mutation must send the current `revision`; stale editors receive HTTP `409` instead of silently overwriting another revision. Freezing hashes the project definition, selected artifact hashes and research context into a reproducible commitment. Any later mutation returns the project to an unfrozen state and requires a new version.

### Recommended operating sequence

1. **DRAFT** — state the market hypothesis, build a causal rule or upload a validated private package, and run a cheap smoke backtest.
2. **COMPOSE** — add optional typed AI reviewers, define timeout/failure behavior, and ensure every execution path crosses deterministic hard risk.
3. **VALIDATE** — bind the project rule, compare it with simple baselines, then run chronological IS/OOS and walk-forward validation with realistic costs.
4. **VERSION** — review all server gates, freeze a semantic version, and retain the returned commitment hash.
5. **PUBLISH** — submit only the frozen version and verifiable result material to QuantJudge; never publish an unfrozen working copy.

### ZKP promotion path

The ZKP path is deliberately narrower than the general Strategy Lab. A normal visual rule, Python package or AI workflow can be researched and platform-attested, but it is not automatically a zero-knowledge program. To receive the `zk_verified` evidence level, select a registered ZK-native profile, generate its witness locally, prove it with the fixed guest, upload only the receipt, and publish the server-verified journal. The first profile proves long-only SMA crossover semantics; unsupported nodes and deployment modes are blocked rather than relabelled as ZKP.

See [ZKP.md](ZKP.md) for the exact public/private boundary, threat model, Supervisor payload and extension requirements.

## Isolation and privacy boundary

Uploading does not execute user code in the API process. Archives are bounded by compressed size, expanded size, file count and compression ratio; traversal paths, symlinks, unsupported binaries and credential files are rejected. Python AST and entrypoint checks happen before encrypted storage. Packages and workflows are AES-256-GCM encrypted with associated data binding their owner and version.

Production Python execution still requires an isolated worker with no default network access, a read-only filesystem, CPU/memory/time limits, pinned dependencies, deterministic seed/clock injection, and an explicit data capability allowlist. The current API validates and stores packages; it deliberately does not pretend that executing arbitrary uploads inside the web process is safe.

## SDK contract

Install the local SDK into a strategy development environment:

```bash
pip install -e sdk/python
```

Implement `BaseStrategy.generate_targets(context)`. `StrategyContext` provides closed historical bars, immutable parameters, a portfolio snapshot, a run ID, and deterministic seed. Return target positions, not broker orders; Atlas owns AI reviews, hard risk, execution modeling and audit commitments. See `examples/strategies/risk_aware_momentum`.
