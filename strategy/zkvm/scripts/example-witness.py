#!/usr/bin/env python3
import argparse
import hashlib
import json
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--market-dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--previous-receipt-hash")
    args = parser.parse_args()
    market = json.loads(args.market_dataset.read_text(encoding="utf-8"))
    workflow = hashlib.sha256(
        b"ATLASWORKFLOW1:market_data>sma_signal>target_sizer>hard_risk>next_open_execution>audit>output"
    ).hexdigest()
    witness = {
        "agent_id": args.agent_id,
        "workflow_commitment": workflow,
        "previous_receipt_hash": args.previous_receipt_hash,
        "strategy_salt": list(secrets.token_bytes(32)),
        "nullifier_nonce": list(secrets.token_bytes(32)),
        "initial_equity_micros": 100_000_000_000,
        "strategy": {
            "fast_period": 20,
            "slow_period": 60,
            "target_position_bps": 9_000,
            "commission_bps": 10,
            "slippage_bps": 5,
        },
        "market": market["dataset"],
    }
    args.output.write_text(json.dumps(witness, indent=2) + "\n", encoding="utf-8")
    print("Private witness written. Keep this file outside source control.")


if __name__ == "__main__":
    main()
