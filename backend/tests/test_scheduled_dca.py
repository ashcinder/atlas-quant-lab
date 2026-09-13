import pandas as pd
import pytest
from app.backtest.engine import run_backtest
from app.models import BacktestRequest
from app.strategies.schedule import contribution_schedule
from tests.test_backtest import make_bundle


def test_calendar_month_end_does_not_drift():
    dates = pd.date_range("2025-01-31", "2025-04-01", tz="UTC")
    due = contribution_schedule(dates, 1, "months")
    assert [d.strftime("%m-%d") for d, yes in zip(dates, due) if yes] == ["01-31", "02-28", "03-31"]


def test_fixed_amount_includes_fees_and_runs_through_horizon():
    bundle = make_bundle()
    bundle.frame = bundle.frame.iloc[:100].copy()
    bundle.frame[["open", "high", "low", "close"]] = 100.
    bundle.frame["volume"] = 1000000.
    result = run_backtest(BacktestRequest(strategy_id="scheduled_dca", params={"amount": 1000, "every": 1, "unit": "weeks"}, persist=False), bundle)
    assert len(result.trades) == 15
    assert all(t.notional + t.fee == pytest.approx(1000) for t in result.trades)
    assert result.trades[0].time == int(bundle.frame.index[1].timestamp())
    assert result.trades[-1].time == int(bundle.frame.index[99].timestamp())


def test_small_contributions_still_reviewed_by_ai(monkeypatch):
    import app.ai_runtime
    calls = []
    class Guard:
        def review(self, *args, **kwargs):
            calls.append(args)
            return 0, {"status": "inference_completed"}
    monkeypatch.setattr(app.ai_runtime, "LocalAIGuard", Guard)
    bundle = make_bundle()
    bundle.frame = bundle.frame.iloc[:60]
    result = run_backtest(BacktestRequest(strategy_id="scheduled_dca", params={"amount": 1}, persist=False,
        execution_pipeline={"ai_stages": [{"stage": "entry", "enabled": True, "authority": "veto"}]}), bundle)
    assert calls and not result.trades


def test_zero_interval_rejected():
    with pytest.raises(ValueError):
        run_backtest(BacktestRequest(strategy_id="scheduled_dca", params={"every": 0}), make_bundle())
