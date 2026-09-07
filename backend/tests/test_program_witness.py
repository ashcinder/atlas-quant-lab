import json
import stat
import subprocess
import sys
from pathlib import Path


def test_local_witness_is_private_fresh_non_overwriting_and_bindable(tmp_path):
    script = Path(__file__).resolve().parents[2] / "strategy/zkvm/scripts/program_witness.py"
    market, strategy = tmp_path / "market.json", tmp_path / "program.json"
    market.write_text(json.dumps({"dataset": {"bars": []}}))
    strategy.write_text(
        json.dumps({"program": [{"const": 0}], "commission_bps": 10, "slippage_bps": 5})
    )
    draft, bound = tmp_path / "draft.json", tmp_path / "bound.json"
    command = [
        sys.executable,
        str(script),
        "--market",
        str(market),
        "--strategy",
        str(strategy),
        "--output",
        str(draft),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    original = draft.read_bytes()
    witness = json.loads(original)
    assert stat.S_IMODE(draft.stat().st_mode) == 0o600
    assert len(witness["strategy_salt"]) == len(witness["nullifier_nonce"]) == 32
    assert witness["strategy_salt"] != witness["nullifier_nonce"]
    assert "program" not in result.stdout and "strategy_salt" not in result.stdout
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert draft.read_bytes() == original
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--bind-existing",
            str(draft),
            "--agent-id",
            "qja_actual_id",
            "--output",
            str(bound),
        ],
        check=True,
        capture_output=True,
    )
    rebound = json.loads(bound.read_text())
    assert rebound.pop("agent_id") == "qja_actual_id"
    witness.pop("agent_id")
    assert rebound == witness
