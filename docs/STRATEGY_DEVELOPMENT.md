# Atlas Strategy Lab

Atlas Strategy Lab is the unified development and validation plane behind QuantJudge. Its single lifecycle combines safe rule construction, AI workflow composition, IS/OOS and walk-forward validation, private version packages, and the developer SDK while keeping execution results auditable. QuantJudge remains the marketplace and publishing plane.

## Which strategy format should I use?

| Format | Best for | Production path | Notes |
|---|---|---|---|
| Python SDK | research teams and full portfolio logic | isolated runner | Native Atlas format; typed event and portfolio contracts |
| JSON rule DSL | no-code and simple technical rules | safe interpreter | No arbitrary code; easiest to inspect and reproduce |
| Remote Runner contract | proprietary or C++/Rust/institutional systems | signed HTTPS/gRPC adapter | Source never reaches Atlas; only signed inputs and decisions cross the boundary |
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

## Isolation and privacy boundary

Uploading does not execute user code in the API process. Archives are bounded by compressed size, expanded size, file count and compression ratio; traversal paths, symlinks, unsupported binaries and credential files are rejected. Python AST and entrypoint checks happen before encrypted storage. Packages and workflows are AES-256-GCM encrypted with associated data binding their owner and version.

Production Python execution still requires an isolated worker with no default network access, a read-only filesystem, CPU/memory/time limits, pinned dependencies, deterministic seed/clock injection, and an explicit data capability allowlist. The current API validates and stores packages; it deliberately does not pretend that executing arbitrary uploads inside the web process is safe.

## SDK contract

Install the local SDK into a strategy development environment:

```bash
pip install -e sdk/python
```

Implement `BaseStrategy.generate_targets(context)`. `StrategyContext` provides closed historical bars, immutable parameters, a portfolio snapshot, a run ID, and deterministic seed. Return target positions, not broker orders; Atlas owns AI reviews, hard risk, execution modeling and audit commitments. See `examples/strategies/risk_aware_momentum`.
