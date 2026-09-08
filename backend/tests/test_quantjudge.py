from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.quantjudge import QuantJudgeStore, ReceiptAttestor, merkle_root, sha256_hex
from app.quantjudge_models import PerformanceReportCreate, QuantAgentCreate
from app.supervisor_client import SupervisorStatus


class FakeSupervisor:
    expected_hash = ""

    def status(self):
        return SupervisorStatus(True, "http://supervisor.test", 1051, 2048)

    def transaction_receipt(self, _transaction_hash: str):
        return {"status": "0x1", "blockNumber": "0x800"}

    def transaction(self, _transaction_hash: str):
        return {"input": "0x" + b"ATLASQJ1".hex() + self.expected_hash}

    def submit_signed_transaction(self, _raw: str):
        return "0x" + "ab" * 32


def make_store(tmp_path):
    return QuantJudgeStore(
        tmp_path / "quantjudge.sqlite3",
        attestor=ReceiptAttestor(tmp_path / "attestor.key"),
        supervisor=FakeSupervisor(),  # type: ignore[arg-type]
        seed_demo=False,
    )


def create_agent(store: QuantJudgeStore):
    return store.create_agent(
        QuantAgentCreate(
            name="Private Momentum Agent",
            developer_alias="Cipher Lab",
            category="timing",
            asset_classes=["crypto"],
            description="基于私密信号的趋势跟随与动态仓位管理策略。",
            strategy_commitment=sha256_hex("secret strategy plus salt"),
        )
    )


def make_report():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return PerformanceReportCreate(
        report_type="live",
        period_start=start,
        period_end=start + timedelta(days=4),
        equity_points=[
            {"time": int((start + timedelta(days=day)).timestamp()), "equity": value, "benchmark": 100 + day}
            for day, value in enumerate([100, 102, 101, 106, 109])
        ],
        decision_commitments=[sha256_hex(f"private decision {index}") for index in range(3)],
        market_data_hash=sha256_hex("market bars"),
    )


def test_private_inputs_are_committed_signed_and_not_returned(tmp_path):
    store = make_store(tmp_path)
    created = create_agent(store)
    token = created["developer_token"]
    agent_id = created["agent"]["id"]
    request = make_report()

    report = store.publish_report(agent_id, request, token)
    verified = store.verify_report(report["id"], refresh_chain=False)
    public_agent = store.get_agent(agent_id)

    assert report["decision_merkle_root"] == merkle_root(request.decision_commitments)
    assert report["metrics"]["total_return"] == pytest.approx(0.09)
    assert verified["receipt_hash_valid"] is True
    assert verified["attestation_signature_valid"] is True
    assert verified["record_integrity_valid"] is True
    assert verified["public_curve_integrity_valid"] is True
    assert verified["calculation_verified"] is True
    assert "developer_token" not in public_agent
    assert "decision_commitments" not in str(public_agent)
    assert "equity_points" not in str(public_agent)
    assert all(set(point) == {"time", "return", "benchmark_return"} for point in report["public_curve"])


def test_developer_token_and_chain_confirmation_boundaries(tmp_path):
    store = make_store(tmp_path)
    created = create_agent(store)
    agent_id = created["agent"]["id"]
    with pytest.raises(PermissionError):
        store.publish_report(agent_id, make_report(), "wrong-token")

    report = store.publish_report(agent_id, make_report(), created["developer_token"])
    store.supervisor.expected_hash = report["receipt_hash"]  # type: ignore[attr-defined]
    attached = store.attach_transaction(
        report["id"], "0x" + "12" * 32, created["developer_token"]
    )
    assert attached["chain"]["status"] == "confirmed"
    assert attached["chain"]["block_number"] == 2048


def test_score_market_and_overview_are_public_only(tmp_path):
    store = make_store(tmp_path)
    created = create_agent(store)
    store.publish_report(created["agent"]["id"], make_report(), created["developer_token"])
    agents = store.list_agents()
    overview = store.overview()

    assert agents[0]["rank"] == 1
    assert 0 <= agents[0]["latest_report"]["score"] <= 100
    assert overview["agents"] == 1
    assert overview["attestation"]["algorithm"] == "Ed25519"
    assert store.chain_status()["read_only_source_policy"] is True


def test_concurrent_report_appends_do_not_fork_receipt_chain(tmp_path):
    store = make_store(tmp_path)
    created = create_agent(store)
    agent_id = created["agent"]["id"]
    token = created["developer_token"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _index: store.publish_report(agent_id, make_report(), token), range(2)))

    roots = [report["previous_receipt_hash"] for report in reports]
    assert roots.count(None) == 1
    first_hash = next(report["receipt_hash"] for report in reports if report["previous_receipt_hash"] is None)
    assert next(root for root in roots if root is not None) == first_hash


def test_signed_receipt_detects_tampered_public_record(tmp_path):
    store = make_store(tmp_path)
    created = create_agent(store)
    report = store.publish_report(
        created["agent"]["id"], make_report(), created["developer_token"]
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE qj_reports SET metrics_json = ?, curve_json = ? WHERE id = ?",
            ('{"total_return":999}', '[]', report["id"]),
        )

    verification = store.verify_report(report["id"], refresh_chain=False)
    assert verification["attestation_signature_valid"] is True
    assert verification["record_integrity_valid"] is False
    assert verification["public_curve_integrity_valid"] is False
    assert verification["calculation_verified"] is False
