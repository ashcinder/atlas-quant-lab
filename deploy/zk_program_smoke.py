"""Verify a real local receipt end-to-end using ONLY a disposable database.

Usage: backend/.venv/bin/python deploy/zk_program_smoke.py witness.json proof.r0
Use a synthetic fixture, not a user's private strategy. No chain writes.
"""
from datetime import datetime, UTC
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.quantjudge import QuantJudgeStore  # noqa: E402
from app.quantjudge_models import QuantAgentCreate  # noqa: E402
from app.zkp import Risc0ReceiptVerifier, ZkProofError, ZkProofStore  # noqa: E402


def main():
    witness = json.loads(Path(sys.argv[1]).read_text())
    receipt = Path(sys.argv[2]).resolve()
    profile = json.loads((REPO / "strategy/zkvm/profiles.json").read_text())["profiles"]["atlas_program_backtest_risc0_v2"]
    verifier = Risc0ReceiptVerifier()
    verified = verifier.verify(receipt, profile["image_id"])
    with tempfile.TemporaryDirectory(prefix="atlas-real-zk-test-") as directory:
        root = Path(directory)
        db = root / "test.sqlite3"
        quant = QuantJudgeStore(db, seed_demo=False)
        created = quant.create_agent(QuantAgentCreate(
            name="Real proof integration fixture", developer_alias="Fixture only",
            category="timing", asset_classes=["crypto"],
            description="Synthetic fixture used only in a disposable local integration database.",
            strategy_commitment=verified.journal["strategy_commitment"]))
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE qj_agents SET id=? WHERE id=?", (witness["agent_id"], created["agent"]["id"]))
        proofs = ZkProofStore(db, receipt_root=root / "receipts", market_root=root / "market")
        proofs.register_market_dataset(witness["market"], fetched_at=datetime.now(UTC), trust_model="synthetic_integration_fixture_only")
        quant.bind_proof_store(proofs)
        proof = proofs.register_receipt(witness["agent_id"], "atlas_program_backtest_risc0_v2", receipt.read_bytes(), created["developer_token"])
        report = quant.publish_zk_report(witness["agent_id"], proof["id"], created["developer_token"])
        assert report["evidence_level"] == "zk_verified"
        assert quant.verify_report(report["id"], refresh_chain=False)["external_proof_verified"]
        assert not proof["private_witness_stored"]
        for forbidden in ("strategy_salt", "nullifier_nonce", '"program"'):
            assert forbidden not in json.dumps(report)
        try:
            proofs.register_receipt(witness["agent_id"], "atlas_program_backtest_risc0_v2", receipt.read_bytes(), created["developer_token"])
        except ZkProofError:
            pass
        else:
            raise AssertionError("Replay accepted")
        altered = bytearray(receipt.read_bytes())
        altered[len(altered) // 2] ^= 1
        corrupt = root / "corrupted.r0"
        corrupt.write_bytes(altered)
        for path, expected in ((corrupt, profile["image_id"]), (receipt, "ab" * 32)):
            try:
                verifier.verify(path, expected)
            except ZkProofError:
                pass
            else:
                raise AssertionError("Corrupt or wrong-image receipt accepted")
    print("Real program ZKP passed: proof verification, private-witness exclusion, report publication, re-verification, replay/corruption/wrong-image rejection. No production DB or chain was modified.")


if __name__ == "__main__":
    main()
