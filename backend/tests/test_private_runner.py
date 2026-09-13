import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from pydantic import ValidationError

from app import private_runner, strategy_runtime
from app.private_runner import PrivateDecision, PrivateRunnerStore, signing_bytes
from app.strategy_anchor import StrategyAnchorStore
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr(private_runner.time, "time", lambda: clock[0])
    monkeypatch.setattr(strategy_runtime, "_now", lambda: datetime.fromtimestamp(clock[0], UTC))
    monkeypatch.setattr(
        private_runner.quote_probe,
        "quote",
        lambda: {
            "bidPrice": Decimal("99"),
            "askPrice": Decimal("100"),
            "bidQty": Decimal("100"),
            "askQty": Decimal("100"),
        },
    )
    key = Ed25519PrivateKey.generate()
    store = StrategyRuntimeStore(SimpleNamespace(), tmp_path / "runtime.db")
    body = dict(
        name="Private local strategy",
        strategy_id="private_test",
        markets=["CRYPTO"],
        source_kind="private_runner",
        execution_mode="private_runner",
        code_commitment="a" * 64,
        runner_public_key=key.public_key().public_bytes_raw().hex(),
    )
    release = store.create_release("author", ReleaseCreate(**body))
    subscription = store.subscribe("subscriber", release["id"])
    run = store.create_run(
        "subscriber",
        RunCreate(
            release_id=release["id"],
            subscription_id=subscription["id"],
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash="200",
        ),
    )
    store.set_status("subscriber", run["id"], "start")
    runner = PrivateRunnerStore(store)

    def decision(target="0.1", **overrides):
        payload = dict(
            domain="atlas.private-decision/v1",
            run_id=run["id"],
            release_id=release["id"],
            content_hash=release["content_hash"],
            issued_at=clock[0],
            target=target,
            nonce=uuid4().hex,
        )
        payload.update(overrides)
        return PrivateDecision(**payload, signature=key.sign(signing_bytes(payload)).hex())

    return store, runner, release, run, clock, decision, body


def test_private_source_absent_and_signed_buy_sell_persist(setup):
    store, runner, release, run, clock, decision, body = setup
    with pytest.raises(ValidationError):
        ReleaseCreate(**body, source="def secret_strategy(): pass")
    with store._connect() as conn:
        snapshot = json.loads(conn.execute("SELECT snapshot FROM strategy_releases").fetchone()[0])
    assert set(snapshot) == {"execution_mode", "code_commitment", "runner_public_key"}
    assert store.tick("subscriber", run["id"])["fills"] == []
    clock[0] += 2
    first = decision()
    assert runner.submit(first)["accepted"]
    clock[0] += 12
    with pytest.raises(HTTPException):
        runner.submit(first)
    runner = PrivateRunnerStore(StrategyRuntimeStore(SimpleNamespace(), store.path))
    assert runner.submit(decision("0"))["accepted"]
    result = store.get_run("subscriber", run["id"], True)
    assert [fill["side"] for fill in result["fills"]] == ["sell", "buy"]
    assert len(result["curve"]) == 2
    assert Decimal(result["equity"]) < 200
    assert Decimal(result["quantity"]) == 0
    assert {s["status"] for s in result["signals"]} == {"filled"}
    assert store.ledger("outsider", None, None, None, None, None, None, None, 50, 0)["fills"] == []


def test_invalid_signature_expiry_pause_and_cross_version(setup):
    store, runner, release, run, clock, decision, _ = setup
    clock[0] += 2
    for body in [
        decision().model_copy(update={"signature": "0" * 128}),
        decision(content_hash="b" * 64),
        decision(issued_at=clock[0] - 40),
    ]:
        with pytest.raises(HTTPException):
            runner.submit(body)
    store.set_status("subscriber", run["id"], "pause")
    with pytest.raises(HTTPException):
        runner.submit(decision())
    assert store.get_run("subscriber", run["id"], True)["fills"] == []


def test_pause_during_quote_discards_signal(setup, monkeypatch):
    store, runner, _, run, clock, decision, _ = setup
    clock[0] += 2
    original = private_runner.quote_probe.quote

    def pause():
        store.set_status("subscriber", run["id"], "pause")
        return original()

    monkeypatch.setattr(private_runner.quote_probe, "quote", pause)
    with pytest.raises(HTTPException):
        runner.submit(decision())
    assert store.get_run("subscriber", run["id"], True)["fills"] == []


def test_anchor_verifies_payload_wallet_receipt_and_chain(setup):
    store, _, release, _, _, _, _ = setup
    address, tx_hash, block_hash = "0x" + "1" * 40, "0x" + "2" * 64, "0x" + "3" * 64
    client = SimpleNamespace(
        status=lambda: SimpleNamespace(connected=True, chain_id=1051, block_number=12)
    )
    anchors = StrategyAnchorStore(store, client)
    prepared = anchors.prepare("author", release["id"], address)
    tx = dict(hash=tx_hash, input=prepared["data"], value="0x0", to=address, blockHash=block_hash)
    tx["from"] = address
    client.transaction = lambda _: tx
    client.transaction_receipt = lambda _: dict(
        transactionHash=tx_hash, status="0x1", blockNumber="0xc", blockHash=block_hash
    )
    client._call = lambda *_: {"hash": block_hash}
    with pytest.raises(HTTPException):
        anchors.prepare("subscriber", release["id"], address)
    tx["input"] = "0xdead"
    with pytest.raises(HTTPException):
        anchors.confirm("author", release["id"], tx_hash)
    tx["input"] = prepared["data"]
    result = anchors.confirm("author", release["id"], tx_hash)
    assert result["anchor"]["status"] == "confirmed"
    assert result["commitment"]["code_commitment"] == "a" * 64
    client._call = lambda *_: {"hash": "0xreorg"}
    assert anchors.confirm("author", release["id"], tx_hash)["anchor"]["status"] == "unreachable"


def test_only_signed_signal_route_uses_signature_authentication():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    try:
        assert client.post("/api/v1/private-runner/signals", json={}).status_code == 422
        assert client.get("/api/v1/private-runner/signals").status_code == 401
        assert client.post("/api/v1/strategy-releases", json={}).status_code == 401
        assert (
            client.post("/api/v1/strategy-releases/rel_test/anchor/prepare", json={}).status_code
            == 401
        )
    finally:
        client.close()
