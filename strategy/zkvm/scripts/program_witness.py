"""Prepare a private v2 witness locally. Never send it to the Atlas API.

This only assembles inputs; atlas-zkvm inspect/prove validates the program and
accounting. Use inspect's commitment to create an Agent, then bind its ID with
--bind-existing. Binding preserves the private program, salt and costs.
"""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets

WORKFLOW = "b20cf36a741d831aa114db85c39ae9c78d9ab144e16c0a26db2a68a31dba5a32"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", type=Path, help="Registered downloaded dataset JSON")
    parser.add_argument("--strategy", type=Path, help="Private program + commission_bps + slippage_bps JSON")
    parser.add_argument("--capital", default="100000")
    parser.add_argument("--agent-id", default="qja_localdraft")
    parser.add_argument("--bind-existing", type=Path, help="Existing witness to bind without changing commitment")
    parser.add_argument("--output", type=Path, required=True, help="New private file; existing files are never overwritten")
    args = parser.parse_args()
    if not args.agent_id.startswith("qja_") or len(args.agent_id) > 100:
        parser.error("Expected a QuantJudge qja_ Agent ID")
    if args.bind_existing:
        if args.market or args.strategy:
            parser.error("Binding cannot also replace market or strategy")
        witness = json.loads(args.bind_existing.read_text())
        witness["agent_id"] = args.agent_id
    else:
        if not args.market or not args.strategy:
            parser.error("--market and --strategy are required for a new witness")
        capital = Decimal(args.capital) * 1_000_000
        if not capital.is_finite() or capital != capital.to_integral_value() or not 0 < capital <= 10**15:
            parser.error("Capital must be positive, at most 1e9, with at most 6 decimal places")
        market = json.loads(args.market.read_text())
        if "dataset" in market:
            market = market["dataset"]
        witness = {
            "agent_id": args.agent_id,
            "workflow_commitment": WORKFLOW,
            "previous_receipt_hash": None,
            "strategy_salt": list(secrets.token_bytes(32)),
            "nullifier_nonce": list(secrets.token_bytes(32)),
            "initial_equity_micros": int(capital),
            "strategy": json.loads(args.strategy.read_text()),
            "market": market,
        }
    encoded = json.dumps(witness, allow_nan=False, separators=(",", ":")).encode()
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
    print("Private witness created (0600). Run inspect locally; upload only the resulting receipt.")


if __name__ == "__main__":
    main()
