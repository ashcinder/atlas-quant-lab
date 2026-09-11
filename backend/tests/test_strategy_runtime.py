from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore


def frame(count=60):
    index = pd.date_range("2024-01-01", periods=count, freq="D", tz="UTC")
    prices = [100 + value for value in range(count)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [value + 2 for value in prices],
            "low": [value - 2 for value in prices],
            "close": [value + 1 for value in prices],
            "volume": [10_000] * count,
        },
        index=index,
    )


class FakeData:
    def __init__(self):
        self.frame = frame()
        self.source = "fixture"
        self.stale = False

    def fetch(self, *_args, **_kwargs):
        return SimpleNamespace(
            frame=self.frame,
            source=self.source,
            is_stale=self.stale,
            fetched_at=self.frame.index[-1],
        )


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from app import strategy_runtime
    from app.trading import Exchange

    monkeypatch.setattr(Exchange, "spot_prices", lambda self: {})
    # The fixture replays 2024 bars, so activation also uses a historical clock.
    monkeypatch.setattr(
        strategy_runtime, "_now", lambda: pd.Timestamp("2023-12-31", tz="UTC").to_pydatetime()
    )
    data = FakeData()
    return StrategyRuntimeStore(data, tmp_path / "runtime.db"), data


def release(store, owner="alice", name="动量"):
    return store.create_release(
        owner,
        ReleaseCreate(
            name=name,
            source_kind="builtin",
            strategy_id="momentum",
            params={"lookback": 10, "smoothing": 2, "threshold": 0, "exit_threshold": -0.1},
            markets=["CRYPTO", "US", "CN"],
        ),
    )


def test_release_is_immutable_and_subscription_is_idempotent(runtime):
    store, _ = runtime
    first = release(store)
    second = release(store)
    assert first["version"] == 1
    assert second["version"] == 2
    assert first["content_hash"] == second["content_hash"]
    subscription = store.subscribe("bob", first["id"])
    again = store.subscribe("bob", first["id"])
    assert again["id"] == subscription["id"]
    assert again["status"] == "active"
    assert again["upgrade_release_id"] == second["id"]
    public = store.list_releases("bob", False)[0]
    assert "params" not in public
    assert "custom_strategy" not in public


def test_owner_must_subscribe_to_another_users_release(runtime):
    store, _ = runtime
    published = release(store)
    with pytest.raises(HTTPException) as error:
        store.create_run(
            "bob",
            RunCreate(release_id=published["id"], market="US", symbol="AAPL", initial_cash="10000"),
        )
    assert error.value.status_code == 403


def test_first_tick_only_anchors_and_next_bar_trades_once(runtime):
    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"], market="CRYPTO", symbol="BTC-USD", initial_cash="10000"
        ),
    )
    store.set_status("alice", run["id"], "start")
    anchored = store.tick("alice", run["id"])
    assert anchored["fills"] == []
    data.frame = frame(61)
    traded = store.tick("alice", run["id"])
    assert len(traded["fills"]) == 1
    assert traded["fills"][0]["side"] == "buy"
    assert float(traded["cash"]) < 10000
    assert float(traded["return_rate"]) > 0
    repeated = store.tick("alice", run["id"])
    assert len(repeated["fills"]) == 1


def test_mid_bar_start_never_fills_before_activation(runtime, monkeypatch):
    from app import strategy_runtime

    store, data = runtime
    activated = frame(61).index[-1] + pd.Timedelta(hours=12)
    monkeypatch.setattr(strategy_runtime, "_now", lambda: activated.to_pydatetime())
    version = release(store)
    run = store.create_run("alice", RunCreate(
        release_id=version["id"], market="CRYPTO", symbol="BTC-USD", initial_cash="200"
    ))
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    data.frame = frame(61)
    assert store.tick("alice", run["id"])["fills"] == []
    data.frame = frame(62)
    fills = store.tick("alice", run["id"])["fills"]
    assert len(fills) == 1
    assert pd.Timestamp(fills[0]["executed_at"]) >= activated
    store.set_status("alice", run["id"], "pause")
    resumed = frame(63).index[-1] + pd.Timedelta(hours=12)
    monkeypatch.setattr(strategy_runtime, "_now", lambda: resumed.to_pydatetime())
    store.set_status("alice", run["id"], "resume")
    store.tick("alice", run["id"])
    data.frame = frame(63)
    assert len(store.tick("alice", run["id"])["fills"]) == 1


def test_volume_participation_caps_a_simulated_fill(runtime):
    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            market="CRYPTO",
            symbol="BTC-USD",
            initial_cash="10000",
            max_participation="0.0001",
        ),
    )
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    data.frame = frame(61)
    traded = store.tick("alice", run["id"])
    assert Decimal(traded["fills"][0]["quantity"]) <= Decimal("1")


def test_partial_stop_loss_keeps_exiting_on_following_bars(runtime):
    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            market="CRYPTO",
            symbol="BTC-USD",
            initial_cash="10000",
            max_participation="0.01",
            stop_loss="0.10",
        ),
    )
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    with store._connect() as connection:
        connection.execute(
            "UPDATE strategy_runs SET cash='0',quantity='1',average_cost='100',"
            "pending_target='1' WHERE id=?",
            (run["id"],),
        )
    extra_index = pd.date_range(data.frame.index[-1] + pd.Timedelta(days=1), periods=2, freq="D")
    extra = pd.DataFrame(
        {
            "open": [80, 120],
            "high": [82, 122],
            "low": [78, 118],
            "close": [81, 121],
            "volume": [10, 10],
        },
        index=extra_index,
    )
    data.frame = pd.concat([data.frame, extra])
    result = store.tick("alice", run["id"])
    assert [item["side"] for item in result["fills"][-2:]] == ["sell", "sell"]
    assert result["quantity"] == "0.80000000"
    with store._connect() as connection:
        state = connection.execute(
            "SELECT exit_pending,pending_target FROM strategy_runs WHERE id=?", (run["id"],)
        ).fetchone()
    assert dict(state) == {"exit_pending": "1", "pending_target": "0.00000000"}


def test_external_account_conflict_is_rechecked_when_starting(runtime, monkeypatch):
    store, _ = runtime
    monkeypatch.setenv("ATLAS_TRADING_OWNER_ID", "alice")
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "key")
    monkeypatch.setenv("ATLAS_BINANCE_API_SECRET", "secret")
    account = next(
        item for item in store.list_accounts("alice") if item["environment"] == "exchange_test"
    )
    published = release(store)
    request = RunCreate(
        release_id=published["id"],
        account_id=account["id"],
        market="CRYPTO",
        environment="exchange_test",
        symbol="BTC-USDT",
        initial_cash="10000",
    )
    first = store.create_run("alice", request)
    second = store.create_run("alice", request)
    store.set_status("alice", first["id"], "start")
    with pytest.raises(HTTPException) as error:
        store.set_status("alice", second["id"], "start")
    assert error.value.status_code == 409


def test_demo_and_stale_data_fail_closed(runtime):
    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(release_id=published["id"], market="US", symbol="AAPL", initial_cash="10000"),
    )
    store.set_status("alice", run["id"], "start")
    data.source = "demo"
    with pytest.raises(HTTPException) as error:
        store.tick("alice", run["id"])
    assert "演示行情" in error.value.detail
    assert store.get_run("alice", run["id"])["status"] == "error"


def test_cancel_subscription_stops_its_runs_and_ledger_isolated(runtime):
    store, data = runtime
    published = release(store, "author")
    subscription = store.subscribe("alice", published["id"])
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            subscription_id=subscription["id"],
            market="CRYPTO",
            symbol="BTC-USD",
            initial_cash="5000",
        ),
    )
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    data.frame = frame(61)
    store.tick("alice", run["id"])
    assert store.ledger("alice", None, None, None, None, None, None, None, 50, 0)["fills"]
    assert store.ledger("bob", None, None, None, None, None, None, None, 50, 0)["fills"] == []
    store.cancel_subscription("alice", subscription["id"])
    assert store.get_run("alice", run["id"])["status"] == "stopped"


@pytest.mark.parametrize(
    "market,symbol,currency",
    [
        ("US", "AAPL", "USD"),
        ("CN", "600519.SS", "CNY"),
        ("CRYPTO", "BTC-USD", "USD"),
        ("CRYPTO", "BTC-USDT", "USDT"),
    ],
)
def test_three_market_buy_sell_cash_and_fees_reconcile(runtime, market, symbol, currency):
    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            market=market,
            symbol=symbol,
            initial_cash="100000",
            max_participation="1",
            commission_rate="0.001",
            slippage_rate="0.0005",
        ),
    )
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    data.frame = frame(61)
    bought = store.tick("alice", run["id"])
    assert bought["currency"] == currency
    assert Decimal(bought["quantity"]) > 0
    if market == "CN":
        assert Decimal(bought["quantity"]) % 100 == 0
    with store._connect() as connection:
        connection.execute("UPDATE strategy_runs SET pending_target='0' WHERE id=?", (run["id"],))
    data.frame = frame(62)
    sold = store.tick("alice", run["id"])
    assert Decimal(sold["quantity"]) == 0
    cash = Decimal("100000")
    for fill in sold["fills"]:
        gross = Decimal(fill["quantity"]) * Decimal(fill["price"])
        cash += gross if fill["side"] == "sell" else -gross
        cash -= Decimal(fill["fee"])
        assert fill["fee_currency"] == currency
    assert abs(cash - Decimal(sold["cash"])) < Decimal("0.00001")
    assert abs(
        (cash - Decimal("100000")) / Decimal("100000") - Decimal(sold["return_rate"])
    ) < Decimal("0.00000001")
    assert len(sold["orders"]) == 2
    assert sold["fund_events"][0]["event_type"] == "initial_allocation"
    restarted = StrategyRuntimeStore(data, store.path)
    assert len(restarted.tick("alice", run["id"])["fills"]) == 2


def test_account_snapshot_separates_unattributed_assets_and_flags_shortfall(runtime, monkeypatch):
    from app.trading import Exchange

    store, _ = runtime
    monkeypatch.setenv("ATLAS_TRADING_OWNER_ID", "alice")
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "key")
    monkeypatch.setenv("ATLAS_BINANCE_API_SECRET", "secret")
    account = next(
        item for item in store.list_accounts("alice") if item["environment"] == "exchange_test"
    )
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            account_id=account["id"],
            market="CRYPTO",
            environment="exchange_test",
            symbol="BTC-USDT",
            initial_cash="1000",
        ),
    )
    with store._connect() as connection:
        connection.execute("UPDATE strategy_runs SET quantity='2' WHERE id=?", (run["id"],))
    monkeypatch.setattr(
        Exchange,
        "account",
        lambda self: [
            {"asset": "BTC", "available": "0.5", "locked": "0.5"},
            {"asset": "ETH", "available": "3", "locked": "0"},
        ],
    )
    result = store.sync_account("alice", account["id"])
    assert result["status"] == "reconciliation_required"
    assert result["balances"][0]["reconciliation_shortfall"] == "-1.0"
    assert result["balances"][1]["unattributed_quantity"] == "3"
    assert Decimal(store.get_run("alice", run["id"])["cash"]) == 1000
    with pytest.raises(HTTPException):
        store.account_assets("bob", account["id"])


def test_private_version_runs_without_being_published(runtime):
    store, _ = runtime
    private = store.create_release(
        "alice",
        ReleaseCreate(
            name="私有规则",
            source_kind="builtin",
            strategy_id="momentum",
            markets=["US"],
            params={"lookback": 10, "smoothing": 2, "threshold": 0, "exit_threshold": -0.1},
            published=False,
        ),
    )
    assert store.list_releases("bob") == []
    with pytest.raises(HTTPException):
        store.subscribe("bob", private["id"])
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=private["id"],
            market="US",
            symbol="AAPL",
            initial_cash="1000",
        ),
    )
    assert run["release_id"] == private["id"]
    store.publish_release("alice", private["id"])
    assert store.subscribe("bob", private["id"])["status"] == "active"
    with pytest.raises(HTTPException):
        store.publish_release("bob", private["id"])


def test_manual_link_is_explicit_live_only_and_owner_bound(runtime, monkeypatch):
    import json

    store, _ = runtime
    monkeypatch.setenv("ATLAS_TRADING_OWNER_ID", "alice")
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "key")
    monkeypatch.setenv("ATLAS_BINANCE_API_SECRET", "secret")
    monkeypatch.setenv("ATLAS_BINANCE_MODE", "live")
    accounts = store.list_accounts("alice")
    live = next(account for account in accounts if account["environment"] == "live")
    simulated = next(account for account in accounts if account["environment"] == "platform_sim")
    with store._connect() as connection:
        connection.execute("CREATE TABLE ledgers (owner_id TEXT PRIMARY KEY,data TEXT)")
        connection.execute(
            "INSERT INTO ledgers VALUES (?,?)",
            (
                "alice",
                json.dumps(
                    {"accounts": [{"id": "manual-1", "name": "已有账户", "currency": "USD"}]}
                ),
            ),
        )
    assert store.account_assets("alice", live["id"])["manual_account_id"] is None
    with pytest.raises(HTTPException):
        store.link_account("alice", simulated["id"], "manual-1")
    with pytest.raises(HTTPException):
        store.link_account("bob", live["id"], "manual-1")
    store.link_account("alice", live["id"], "manual-1")
    assert store.account_assets("alice", live["id"])["manual_account_id"] == "manual-1"
    store.link_account("alice", live["id"], None)
    assert store.account_assets("alice", live["id"])["manual_account_id"] is None


@pytest.mark.parametrize("delay", [0, 2])
def test_dca_calendar_excludes_warmup_and_survives_restart(runtime, delay):
    store, data = runtime
    published = store.create_release(
        "alice",
        ReleaseCreate(
            name="每周定投",
            source_kind="builtin",
            strategy_id="scheduled_dca",
            markets=["US"],
            params={"amount": 100, "every": 1, "unit": "weeks", "start_delay": delay},
        ),
    )
    run = store.create_run(
        "alice",
        RunCreate(
            release_id=published["id"],
            market="US",
            symbol="AAPL",
            initial_cash="10000",
            commission_rate="0.01",
            slippage_rate="0.01",
        ),
    )
    store.set_status("alice", run["id"], "start")
    assert store.tick("alice", run["id"])["fills"] == []
    data.frame = frame(60 + delay)
    assert store.tick("alice", run["id"])["fills"] == []
    data.frame = frame(61 + delay)
    first = store.tick("alice", run["id"])
    assert len(first["fills"]) == 1
    assert abs(Decimal(first["cash"]) - Decimal("9900")) < Decimal("0.00001")
    restored = StrategyRuntimeStore(data, store.path)
    data.frame = frame(67 + delay).iloc[10:]
    waiting = restored.tick("alice", run["id"])
    assert len(waiting["fills"]) == 1
    assert waiting["quantity"] == first["quantity"]
    data.frame = frame(68 + delay).iloc[10:]
    second = restored.tick("alice", run["id"])
    assert len(second["fills"]) == 2
    assert abs(Decimal(second["cash"]) - Decimal("9800")) < Decimal("0.00001")


@pytest.mark.parametrize("recovery", ["restart", "resume"])
def test_recovery_skips_offline_trades_and_preserves_holdings(runtime, recovery):
    from app.strategy_runtime import StrategyRuntimeScheduler

    store, data = runtime
    published = release(store)
    run = store.create_run(
        "alice",
        RunCreate(release_id=published["id"], market="US", symbol="AAPL", initial_cash="10000"),
    )
    store.set_status("alice", run["id"], "start")
    store.tick("alice", run["id"])
    data.frame = frame(61)
    before = store.tick("alice", run["id"])
    assert len(before["fills"]) == 1
    if recovery == "restart":
        scheduler = StrategyRuntimeScheduler(store, interval_seconds=3600)
        scheduler.start()
        scheduler.stop()
    else:
        store.set_status("alice", run["id"], "pause")
        store.set_status("alice", run["id"], "resume")
    data.frame = frame(66)
    recovered = store.tick("alice", run["id"])
    assert recovered["cash"] == before["cash"]
    assert recovered["quantity"] == before["quantity"]
    assert len(recovered["fills"]) == 1
    assert recovered["last_bar_time"] == int(data.frame.index[-1].timestamp())
    assert Decimal(recovered["equity"]) > Decimal(before["equity"])
    assert recovered["curve"][-1]["cash"] == before["cash"]


def test_published_example_subscription_execution_and_asset_ledger(runtime):
    import json
    from pathlib import Path

    store, data = runtime
    example = Path(__file__).parents[2] / "strategy/examples/exchange-demo/release.json"
    version = store.create_release(
        "author", ReleaseCreate.model_validate(json.loads(example.read_text()))
    )
    subscription = store.subscribe("subscriber", version["id"])
    run = store.create_run(
        "subscriber",
        RunCreate(
            release_id=version["id"],
            subscription_id=subscription["id"],
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash="200",
            interval="1d",
        ),
    )
    store.set_status("subscriber", run["id"], "start")
    assert not store.tick("subscriber", run["id"])["fills"]
    data.frame = frame(61)
    result = store.tick("subscriber", run["id"])
    assert len(result["fills"]) == 1
    assert result["fills"][0]["side"] == "buy"
    ledger = store.ledger("subscriber", None, None, run["id"], None, None, None, None, 50, 0)
    assert len(ledger["fills"]) == 1
    assert len(ledger["positions"]) == 1
    assert ledger["runs"][0]["quantity"] == result["quantity"]
    assert store.ledger("outsider", None, None, None, None, None, None, None, 50, 0)["fills"] == []
