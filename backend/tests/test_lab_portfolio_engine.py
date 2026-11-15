from datetime import date
import json
from pathlib import Path
import runpy

import pytest

from app.lab_portfolio_engine import PortfolioEngine
from app.lab_portfolio_market import session_windows
from app.sandbox import RunnerFailure, portfolio_runner_status

A, B = "600001.SS", "600002.SS"


def setup(**overrides):
    return {"symbols": [A, B], "interval": "15m", "initial_capital": 10_000,
            "max_position": 1, "commission_rate": 0, "slippage_rate": 0,
            "sell_tax_rate": 0, "max_participation_rate": 0.1, **overrides}


def event(day, slot=0, prices=None, **extras):
    opening, closing = session_windows(date.fromisoformat(day), "15m")[slot]
    prices = prices or {A: 10, B: 10}
    return {"time": closing,
            "bars": {symbol: {"open": price, "high": price, "low": price, "close": price,
                              "volume": 10_000, "lot_size": 100, "limit_up": 11, "limit_down": 9,
                              "open_time": opening}
                     for symbol, price in prices.items()}, **extras}


def order(symbol, side="buy", quantity=600):
    return {"symbol": symbol, "side": side, "quantity": quantity}


def test_missing_corporate_settlement_does_not_advance_held_position():
    engine = PortfolioEngine(setup())
    engine.step(event("2025-01-02"), lambda _: {"orders": [order(A)]})
    engine.step(event("2025-01-02", 1), lambda _: {"orders": []})
    snapshot = engine.snapshot()
    with pytest.raises(RunnerFailure, match="缺少已核实的公司行动"):
        engine.step(event("2025-01-03", unresolved_actions=[A]), lambda _: {"orders": []})
    assert engine.snapshot() == snapshot


def test_shared_cash_next_open_and_t_plus_one():
    engine = PortfolioEngine(setup())
    first = engine.step(event("2025-01-02"), lambda ctx: {"orders": [order(B), order(A)]})
    assert first["trades"] == []
    next_bar = event("2025-01-02", 1, {A: 10, B: 10.5})

    def close_signal(ctx):
        assert ctx["time"] == next_bar["time"]
        assert ctx["sellable"] == {B: 0, A: 0}
        assert ctx["positions"] == {B: 600, A: 300}
        assert ctx["fills"][0]["time"] == first["time"]
        return {"orders": [order(B, "sell", 600)]}

    second = engine.step(next_bar, close_signal)
    assert [(fill["symbol"], fill["quantity"], fill["price"]) for fill in second["trades"]] == [(B, 600, 10.5), (A, 300, 10)]
    assert second["cash"] == 700
    blocked = engine.step(event("2025-01-02", 2), lambda ctx: {"orders": [order(B, "sell", 600)]})
    assert not blocked["trades"] and "T+1" in blocked["rejections"][0]["reason"]
    restored = PortfolioEngine(setup(), json.loads(json.dumps(engine.snapshot())))
    last = restored.step(event("2025-01-03"), lambda ctx: {"orders": []})
    assert last["cash"] == 6700
    assert last["trades"][0]["realized_pnl"] == -300
    assert last["positions"][0]["average_cost"] == 10


def test_next_open_uses_prior_liquidity_and_rejects_limits():
    engine = PortfolioEngine(setup())
    first = event("2025-01-02")
    first["bars"][A]["volume"] = 1000
    engine.step(first, lambda ctx: {"orders": [order(A), order(B)]})
    second = event("2025-01-02", 1, {A: 10, B: 11})
    result = engine.step(second, lambda ctx: {"orders": []})
    assert [(fill["symbol"], fill["quantity"]) for fill in result["trades"]] == [(A, 100)]
    assert [row["reason"] for row in result["rejections"]] == ["成交参与率限制", "开盘触及涨跌停"]


def test_corporate_actions_adjust_quantity_basis_and_dividend_and_gap_discards_orders():
    engine = PortfolioEngine(setup())
    engine.step(event("2025-01-02"), lambda ctx: {"orders": [order(A, quantity=300)]})
    engine.step(event("2025-01-02", 1), lambda ctx: {"orders": [order(B)], "checkpoint": {"n": 1}})
    gap = event("2025-01-06", corporate_actions={A: {"split_ratio": 2, "cash_dividend": 1}})
    gap["bars"][A].update(open=5, high=5, low=5, close=5, limit_up=6, limit_down=4)
    result = engine.step(gap, None, allow_fills=False)
    assert result["positions"][0]["quantity"] == 600
    assert result["positions"][0]["average_cost"] == 5
    assert result["positions"][0]["sellable"] == 600
    assert result["cash"] == 7300
    assert result["corporate_actions"][0]["cash_dividend"] == 300
    assert not result["trades"] and not engine.snapshot()["pending"]
    assert engine.snapshot()["strategy_state"] == {"n": 1}


@pytest.mark.parametrize("response", [
    {"orders": [order("000001.SZ")]},
    {"orders": [order(A, quantity=float("nan"))]},
    {"orders": [order(A, quantity=1.5)]},
    {"targets": [{"symbol": A, "target_weight": 0.6}, {"symbol": B, "target_weight": 0.6}]},
    {"targets": [], "orders": []},
])
def test_untrusted_proposals_rejected_without_advancing_account(response):
    engine = PortfolioEngine(setup())
    previous = engine.snapshot()
    with pytest.raises(RunnerFailure):
        engine.step(event("2025-01-02"), lambda ctx: response)
    assert engine.snapshot() == previous


def test_absent_prices_need_explicit_suspension_and_preserve_ranking():
    engine = PortfolioEngine(setup())
    with pytest.raises(RunnerFailure, match="缺少标的"):
        engine.step(event("2025-01-02", prices={A: 10}), lambda ctx: {"orders": []})
    item = event("2025-01-02", prices={A: 10}, eligible=[B, A], suspended=[B])

    def inspect(ctx):
        assert ctx["symbols"] == [B, A]
        assert ctx["suspended"] == [B]
        return {"orders": []}

    engine.step(item, inspect)


def test_daily_metadata_is_causal_even_without_intraday_quotes():
    engine = PortfolioEngine(setup())
    daily = {B: {"open": 10, "high": 10, "low": 10, "close": 10, "volume": 1000}}
    with pytest.raises(RunnerFailure, match="收盘"):
        engine.step(event("2025-01-02", daily=daily), lambda ctx: {"orders": []})

    def inspect(ctx):
        assert B in ctx["daily"] and B not in ctx["bars"]
        return {"orders": []}

    engine.step(event("2025-01-02", 15, prices={A: 10}, suspended=[B], daily=daily), inspect)


def test_unconfigured_runner_reports_unavailable(monkeypatch):
    monkeypatch.delenv("ATLAS_RUNNER_SOCKET", raising=False)
    available, reason = portfolio_runner_status()
    assert not available and "gVisor" in reason


def test_worker_restores_strategy_state_and_only_supplies_closed_bars(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "strategy/sdk/python"))
    protocol = runpy.run_path(str(root / "strategy/runner/worker.py"))["PortfolioProtocol"]
    from atlas_strategy_sdk import OrderIntent

    # Trusted test fixture. User-defined strategy code only runs in gVisor.
    class Strategy:
        def initialize(self, _):
            self.steps = 0

        def import_state(self, value):
            self.steps = value["steps"]

        def export_state(self):
            return {"steps": self.steps}

        def generate_orders(self, context):
            self.steps += 1
            assert len(context.history(A, 100)) == self.steps
            assert all(bar.timestamp <= context.now for bars in context.bars.values() for bar in bars)
            assert context.symbols == (B, A)
            if self.steps == 1:
                return [OrderIntent(B, "buy", 100)]
            assert context.fills[0]["symbol"] == B
            return []

    engine = PortfolioEngine(setup())
    runner = protocol(Strategy, {}, None)
    engine.step(event("2025-01-02", eligible=[B, A]), lambda payload: runner.step({**payload, "save_state": True}))
    engine = PortfolioEngine(setup(), json.loads(json.dumps(engine.snapshot())))
    runner = protocol(Strategy, {}, engine.strategy_state)
    runner.seed(engine.history())
    second = engine.step(event("2025-01-02", 1, eligible=[B, A]), lambda payload: runner.step({**payload, "save_state": True}))
    assert second["trades"][0]["quantity"] == 100
    assert engine.strategy_state == {"steps": 2}
