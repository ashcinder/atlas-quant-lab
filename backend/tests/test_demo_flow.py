"""Full business flow with explicitly synthetic exchange transport and candle input."""

import runpy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app import demo_credentials, trading_api
from app.demo_execution import execute_demo_signal
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore
from app.trading import Exchange

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_example_subscription_signal_exchange_fill_and_assets(tmp_path, monkeypatch, venue):
    path = tmp_path / "flow.db"
    monkeypatch.setattr(trading_api, "DB_PATH", path)
    monkeypatch.setattr(demo_credentials, "DB_PATH", path)
    monkeypatch.setattr(demo_credentials, "KEY_PATH", tmp_path / ".account-key")
    monkeypatch.delenv("ATLAS_TRADING_OWNER_ID", raising=False)
    monkeypatch.setenv("ATLAS_TRADING_ENABLED", "0")
    demo_credentials.save(
        "subscriber",
        venue,
        {
            "api_key": "synthetic-key",
            "secret": "synthetic-secret",
            "passphrase": "synthetic-phrase",
        },
    )

    def frame(count):
        return pd.DataFrame(
            {
                "open": [160.0] * count,
                "high": [161.0] * count,
                "low": [159.0] * count,
                "close": [160.0] * count,
                "volume": [10000.0] * count,
            },
            index=pd.date_range("2024-01-01", periods=count, tz="UTC"),
        )

    data = SimpleNamespace(frame=frame(60))
    source = SimpleNamespace(
        fetch=lambda *a: SimpleNamespace(frame=data.frame, source="test-fixture", is_stale=False)
    )
    store = StrategyRuntimeStore(source, path)
    version = store.create_release(
        "author",
        ReleaseCreate.model_validate_json(
            (ROOT / "strategy/examples/exchange-demo/release.json").read_text()
        ),
    )
    subscription = store.subscribe("subscriber", version["id"])
    account = next(
        a for a in store.list_accounts("subscriber") if a["name"].lower().startswith(venue)
    )
    run = store.create_run(
        "subscriber",
        RunCreate(
            release_id=version["id"],
            subscription_id=subscription["id"],
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash="200",
            account_id=account["id"],
            environment="exchange_test",
            demo_auto=True,
        ),
    )
    store.set_status("subscriber", run["id"], "start")
    store.tick("subscriber", run["id"])
    data.frame = frame(61)
    store.tick("subscriber", run["id"])
    sent = []
    monkeypatch.setattr(Exchange, "ticker", lambda *a: Decimal("160"))
    monkeypatch.setattr(
        Exchange,
        "spot_rules",
        lambda *a: (Decimal(".01"), Decimal(".00001"), Decimal(".00001"), Decimal("1")),
    )
    monkeypatch.setattr(Exchange, "validate_order", lambda *a: Decimal("160"))
    monkeypatch.setattr(Exchange, "spot_prices", lambda *a: {"BTC": Decimal("160")})

    def balances(*a):
        qty = sent[0].quantity if sent else Decimal("0")
        cost = sent[0].price * qty if sent else Decimal("0")
        return [
            {
                "asset": "USDT",
                "available": str(Decimal("200") - cost * Decimal("1.001")),
                "locked": "0",
            },
            {"asset": "BTC", "available": str(qty), "locked": "0"},
        ]

    monkeypatch.setattr(Exchange, "account", balances)

    def place(self, order, client_id):
        assert self.mode == "demo"
        sent.append(order)
        return {
            "exchange_order_id": "fixture-order",
            "exchange_status": "FILLED",
            "filled_quantity": str(order.quantity),
        }

    monkeypatch.setattr(Exchange, "place", place)
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *a: [
            {
                "trade_id": "fixture-fill",
                "quantity": str(sent[0].quantity),
                "price": str(sent[0].price),
                "fee": str(sent[0].quantity * sent[0].price * Decimal(".001")),
                "fee_currency": "USDT",
                "executed_at": "2026-09-11T00:00:00Z",
            }
        ],
    )
    execute_demo_signal(store, "subscriber", run["id"])
    result = store.get_run("subscriber", run["id"], True)
    assert result["status"] == "active", result["latest_error"]
    assert len(sent) == len(result["fills"]) == 1
    assert Decimal(result["quantity"]) > 0
    ledger = store.ledger("subscriber", None, None, None, None, None, None, None, 50, 0)
    assert len(ledger["fills"]) == 1
    assets = store.account_assets("subscriber", account["id"])
    assert assets["valuation_complete"]
    assert Decimal(assets["total_value_usdt"]) < 200  # Actual test fees and limit price allowance.
    assert abs(Decimal(assets["total_value_usdt"]) - Decimal(result["equity"])) < Decimal(".000001")
    execute_demo_signal(StrategyRuntimeStore(source, path), "subscriber", run["id"])
    assert len(sent) == 1
    monkeypatch.setattr(Exchange, "spot_prices", lambda *a: {})
    incomplete = store.sync_account("subscriber", account["id"])
    assert not incomplete["valuation_complete"]
    assert incomplete["total_value_usdt"] is None
    assert Decimal(incomplete["known_value_usdt"]) > 0


def test_demo_launcher_discards_inherited_live_credentials():
    launcher = runpy.run_path(str(ROOT / "scripts/run-demo.py"))
    result = launcher["demo_environment"](
        {
            "ATLAS_TRADING_OWNER_ID": "owner",
            "ATLAS_OKX_API_KEY": "demo-key",
            "ATLAS_OKX_API_SECRET": "demo-secret",
            "ATLAS_OKX_PASSPHRASE": "demo-phrase",
        },
        {"ATLAS_BINANCE_API_KEY": "live-key", "ATLAS_TRADING_LIVE_ENABLED": "1", "PATH": "/bin"},
    )
    assert "ATLAS_BINANCE_API_KEY" not in result
    assert result["ATLAS_OKX_MODE"] == result["ATLAS_BINANCE_MODE"] == "demo"
    assert result["ATLAS_TRADING_LIVE_ENABLED"] == "0"
    assert result["PATH"] == "/bin"
