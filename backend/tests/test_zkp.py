import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.quantjudge import QuantJudgeStore, ReceiptAttestor, sha256_hex
from app.quantjudge_models import QuantAgentCreate
from app.zkp import (
    VerifiedReceipt,
    ZkProofError,
    ZkProofStore,
    make_market_dataset,
    market_commitment,
)
from app.zkp_models import ZkPublicStatement

IMAGE_ID = "12" * 32


class FakeCryptographicVerifier:
    def __init__(self, statement: dict):
        self.statement = statement
        self.calls = 0

    def verify(self, _receipt_path: Path, expected_image_id: str) -> VerifiedReceipt:
        assert expected_image_id == IMAGE_ID
        self.calls += 1
        return VerifiedReceipt(
            image_id=IMAGE_ID,
            journal=self.statement,
            receipt_kind="test-receipt",
            verifier_version="test-only",
        )


def setup(tmp_path):
    db = tmp_path / "atlas.sqlite3"
    quant = QuantJudgeStore(
        db,
        attestor=ReceiptAttestor(tmp_path / "attestor.key"),
        seed_demo=False,
    )
    created = quant.create_agent(
        QuantAgentCreate(
            name="ZK SMA Agent",
            developer_alias="Proof Lab",
            category="timing",
            asset_classes=["crypto"],
            description="只发布固定 zkVM 程序验证后的确定性 SMA 回测结果。",
            strategy_commitment=sha256_hex("registered private strategy"),
        )
    )
    bars = []
    for index in range(25):
        close = 100 + index
        bars.append(
            {
                "time": 1_700_000_000 + index * 86_400,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000 + index,
            }
        )
    dataset = make_market_dataset(
        source="binance",
        symbol="BTC-USD",
        interval="1d",
        adjustment="raw",
        bars=bars,
    )
    curve = [
        {"time": bars[0]["time"], "return_ppm": 0, "benchmark_return_ppm": 0},
        {
            "time": bars[-1]["time"],
            "return_ppm": 100_000,
            "benchmark_return_ppm": 240_000,
        },
    ]
    statement = ZkPublicStatement.model_validate(
        {
            "schema": "atlas.quantjudge.zk.statement.v1",
            "proof_profile": "atlas_sma_backtest_risc0_v1",
            "agent_id": created["agent"]["id"],
            "strategy_commitment": created["agent"]["strategy_commitment"],
            "workflow_commitment": sha256_hex("fixed workflow"),
            "market_data_hash": market_commitment(dataset),
            "cost_model_hash": sha256_hex("cost model"),
            "report_type": "backtest",
            "period_start": bars[0]["time"],
            "period_end": bars[-1]["time"],
            "initial_equity_micros": 100_000_000,
            "final_equity_micros": 110_000_000,
            "decision_count": 25,
            "decision_merkle_root": sha256_hex("decisions"),
            "equity_curve_hash": "00" * 32,
            "previous_receipt_hash": None,
            "nullifier": sha256_hex("unique proof run"),
            "metrics": {
                "total_return_ppm": 100_000,
                "annualized_return_ppm": 120_000,
                "max_drawdown_ppm": -20_000,
                "annualized_volatility_ppm": 180_000,
                "sharpe_milli": 800,
                "win_rate_ppm": 600_000,
                "benchmark_return_ppm": 240_000,
                "observation_count": 25,
            },
            "public_curve": curve,
        }
    )
    statement = statement.model_copy(
        update={"equity_curve_hash": statement.curve_commitment()}
    )
    verifier = FakeCryptographicVerifier(statement.model_dump(mode="json", by_alias=True))
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "profiles": {
                    "atlas_sma_backtest_risc0_v1": {
                        "status": "active",
                        "image_id": IMAGE_ID,
                    }
                }
            }
        )
    )
    proofs = ZkProofStore(
        db,
        receipt_root=tmp_path / "receipts",
        market_root=tmp_path / "market",
        verifier=verifier,
        profiles_path=profiles,
    )
    proofs.register_market_dataset(dataset, fetched_at=datetime.now(UTC))
    quant.bind_proof_store(proofs)
    return quant, proofs, created, verifier


def test_verified_receipt_publishes_without_private_witness(tmp_path):
    quant, proofs, created, verifier = setup(tmp_path)
    proof = proofs.register_receipt(
        created["agent"]["id"],
        "atlas_sma_backtest_risc0_v1",
        b"opaque cryptographic receipt",
        created["developer_token"],
    )
    report = quant.publish_zk_report(
        created["agent"]["id"], proof["id"], created["developer_token"]
    )
    verification = quant.verify_report(report["id"], refresh_chain=False)

    assert verifier.calls == 2
    assert proof["private_witness_stored"] is False
    assert report["evidence_level"] == "zk_verified"
    assert report["metrics"]["total_return"] == pytest.approx(0.1)
    assert verification["external_proof_verified"] is True
    assert verification["proof_file_integrity_valid"] is True
    assert verification["proof_cryptographic_valid"] is True
    assert "strategy_salt" not in json.dumps(proof)


def test_proof_and_nullifier_cannot_be_replayed(tmp_path):
    _quant, proofs, created, _verifier = setup(tmp_path)
    proofs.register_receipt(
        created["agent"]["id"],
        "atlas_sma_backtest_risc0_v1",
        b"opaque cryptographic receipt",
        created["developer_token"],
    )
    with pytest.raises(ZkProofError, match="禁止重放"):
        proofs.register_receipt(
            created["agent"]["id"],
            "atlas_sma_backtest_risc0_v1",
            b"opaque cryptographic receipt",
            created["developer_token"],
        )


def test_tampered_receipt_revokes_public_verification(tmp_path):
    quant, proofs, created, _verifier = setup(tmp_path)
    proof = proofs.register_receipt(
        created["agent"]["id"],
        "atlas_sma_backtest_risc0_v1",
        b"opaque cryptographic receipt",
        created["developer_token"],
    )
    report = quant.publish_zk_report(
        created["agent"]["id"], proof["id"], created["developer_token"]
    )
    path = proofs.receipt_root / f"{proof['proof_hash']}.r0"
    path.write_bytes(b"tampered")

    verification = quant.verify_report(report["id"], refresh_chain=False)
    assert verification["external_proof_verified"] is False
    assert verification["proof_file_integrity_valid"] is False
