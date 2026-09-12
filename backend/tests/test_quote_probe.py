import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import quote_probe, strategy_runtime
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore


def test_probe_subscription_buy_sell_curve_restart_and_pause(tmp_path, monkeypatch):
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    monkeypatch.setattr(strategy_runtime, "_now", lambda: clock[0])
    monkeypatch.setattr(
        quote_probe,
        "quote",
        lambda: {
            "bidPrice": Decimal("99"),
            "askPrice": Decimal("100"),
            "bidQty": Decimal("10"),
            "askQty": Decimal("10"),
        },
    )
    store = StrategyRuntimeStore(SimpleNamespace(), tmp_path / "probe.db")
    body = json.loads(
        (Path(__file__).parents[2] / "strategy/examples/quote-probe/release.json").read_text()
    )
    release = store.create_release("author", ReleaseCreate.model_validate(body))
    with pytest.raises(HTTPException):
        store.create_run(
            "subscriber",
            RunCreate(
                release_id=release["id"], market="CRYPTO", symbol="BTC-USDT", initial_cash="200"
            ),
        )
    sub = store.subscribe("subscriber", release["id"])
    for environment in ("exchange_test", "live"):
        with pytest.raises(HTTPException):
            store.create_run(
                "subscriber",
                RunCreate(
                    release_id=release["id"],
                    subscription_id=sub["id"],
                    market="CRYPTO",
                    symbol="BTC-USDT",
                    initial_cash="200",
                    environment=environment,
                ),
            )
    run = store.create_run(
        "subscriber",
        RunCreate(
            release_id=release["id"],
            subscription_id=sub["id"],
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash="200",
        ),
    )
    store.set_status("subscriber", run["id"], "start")
    assert store.tick("subscriber", run["id"])["fills"] == []
    for count in range(12):
        clock[0] += timedelta(seconds=10)
        result = store.tick("subscriber", run["id"])
        assert len(result["fills"]) == count + 1
        if count == 0:
            store = StrategyRuntimeStore(SimpleNamespace(), tmp_path / "probe.db")
            assert len(store.tick("subscriber", run["id"])["fills"]) == 1
    assert result["status"] == "paused"
    assert {f["side"] for f in result["fills"]} == {"buy", "sell"}
    assert Decimal(result["quantity"]) == 0
    assert Decimal(result["equity"]) < 200  # Bid/ask spread, fees and slippage are charged.
    assert len(result["curve"]) == 13
    assert all(
        f["environment"] == "platform_sim" and f["external_trade_id"] is None
        for f in result["fills"]
    )
    ledger = store.ledger("subscriber", None, None, run["id"], None, None, None, None, 50, 0)
    assert len(ledger["fills"]) == 12
    assert ledger["runs"][0]["equity"] == result["equity"]
    assert store.ledger("outsider", None, None, None, None, None, None, None, 50, 0)["fills"] == []


def test_quote_read_retries_once_and_never_falls_back(monkeypatch):
    calls = []

    def unavailable():
        calls.append(1)
        raise HTTPException(422, "unavailable")

    monkeypatch.setattr(quote_probe, "_fetch_quote", unavailable)
    with pytest.raises(HTTPException):
        quote_probe.quote()
    assert len(calls) == 2


def test_stale_quote_rejected(monkeypatch):
    monkeypatch.setattr(
        quote_probe.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            headers={"date": "Thu, 01 Jan 1970 00:00:00 GMT"},
            json=lambda: {"bidPrice": "99", "askPrice": "100", "bidQty": "10", "askQty": "10"},
        ),
    )
    with pytest.raises(HTTPException, match="缓存补单"):
        quote_probe._fetch_quote()
