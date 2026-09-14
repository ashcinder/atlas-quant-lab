from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.backtest.engine import run_backtest
from app.catalog import find_asset
from app.data.service import DataBundle
from app.models import BacktestRequest
from app.python_strategy import compile_program, generate_python_targets
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore


def bars(count=50):
    prices = [100 + i % 10 for i in range(count)]
    return pd.DataFrame(
        {
            "open": prices,
            "close": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "volume": [10000] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="D", tz="UTC"),
    )


@pytest.mark.parametrize(
    "source",
    [
        "import os\ndef target_bps(index, close, sma):\n return 0",
        'def target_bps(index, close, sma):\n return __import__("os").system("echo invalid")',
        "def target_bps(index, close, sma):\n while True: pass\n return 0",
        "def target_bps(index, close, sma):\n return 9501",
        "def target_bps(index, close, sma):\n return 100 // 0",
    ],
)
def test_unsupported_or_unbounded_python_is_rejected(source):
    with pytest.raises(ValueError):
        compile_program(source)


def test_price_lags_warmup_and_signal_are_causal():
    source = "def target_bps(index, close, sma):\n return 5000 if close(0) > sma(3) else 0"
    program = compile_program(source)
    history = bars()
    before, _ = generate_python_targets(history, program)
    history.loc[history.index[-1], "close"] = 100000
    after, _ = generate_python_targets(history, program)
    pd.testing.assert_series_equal(before.iloc[:-1], after.iloc[:-1])
    assert before.iloc[0] == 0.5  # Unavailable SMA returns zero, as documented by the compiler.
    lag, _ = generate_python_targets(
        history,
        compile_program("def target_bps(index, close, sma):\n return 2000 if close(1) > 0 else 0"),
    )
    assert lag.iloc[0] == 0 and lag.iloc[1] == 0.2
    assert set(after) == {0, 0.5}


def test_code_backtest_charges_fees_and_obeys_next_open():
    source = "def target_bps(index, close, sma):\n return 5000 if index % 2 == 0 else 0"
    bundle = DataBundle(asset=find_asset("BTC-USD", "crypto"), frame=bars(), source="fixture")
    request = BacktestRequest(
        strategy_id="python_bounded", python_source=source, max_position=0.2, commission_rate=0.001
    )
    result = run_backtest(request, bundle)
    assert result.trades and result.trades[0].time == int(bundle.frame.index[2].timestamp())
    assert all(t.fee > 0 for t in result.trades)
    assert any(t.side == "sell" for t in result.trades)
    assert result.strategy.id == "python_bounded"
    assert max(point.exposure for point in result.equity) < 0.22


def test_code_release_subscription_runtime_pause_and_resume(tmp_path, monkeypatch):
    from app import strategy_runtime
    from app.trading import Exchange

    monkeypatch.setattr(Exchange, "spot_prices", lambda self: {})
    monkeypatch.setattr(
        strategy_runtime, "_now", lambda: pd.Timestamp("2023-12-31", tz="UTC").to_pydatetime()
    )
    bundle = SimpleNamespace(frame=bars(), source="fixture", is_stale=False)
    store = StrategyRuntimeStore(
        SimpleNamespace(fetch=lambda *args: bundle), tmp_path / "runtime.db"
    )
    source = "def target_bps(index, close, sma):\n return 2000"
    release = store.create_release(
        "alice",
        ReleaseCreate(
            name="Python验收",
            source_kind="python",
            strategy_id="python_bounded",
            python_source=source,
            markets=["CRYPTO"],
        ),
    )
    sub = store.subscribe("bob", release["id"])
    public = store.list_releases("bob", False)[0]
    assert "python_source" not in public and "python_program" not in public
    run = store.create_run(
        "bob",
        RunCreate(
            release_id=release["id"],
            subscription_id=sub["id"],
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash=Decimal("10000"),
        ),
    )
    store.set_status("bob", run["id"], "start")
    assert store.tick("bob", run["id"])["fills"] == []
    bundle.frame = bars(51)
    traded = store.tick("bob", run["id"])
    assert len(traded["fills"]) == 1 and traded["fills"][0]["side"] == "buy"
    store.set_status("bob", run["id"], "pause")
    bundle.frame = bars(52)
    with pytest.raises(HTTPException) as paused:
        store.tick("bob", run["id"])
    assert paused.value.status_code == 409
    assert len(store.get_run("bob", run["id"], True)["fills"]) == 1
    store.set_status("bob", run["id"], "resume")
    assert len(store.tick("bob", run["id"])["fills"]) == 1
    assert (
        StrategyRuntimeStore(store.data_service, store.path).get_run("bob", run["id"])["status"]
        == "active"
    )
    changed = store.create_release(
        "alice",
        ReleaseCreate(
            name="新版本",
            source_kind="python",
            strategy_id="python_bounded",
            python_source=source.replace("2000", "4000"),
            markets=["CRYPTO"],
        ),
    )
    assert changed["content_hash"] != release["content_hash"]
    assert store.get_run("bob", run["id"])["release_id"] == release["id"]
    with pytest.raises(HTTPException):
        store.create_release(
            "alice",
            ReleaseCreate(
                name="不支持的代码",
                source_kind="python",
                strategy_id="python_bounded",
                python_source="import os",
                markets=["CRYPTO"],
            ),
        )
