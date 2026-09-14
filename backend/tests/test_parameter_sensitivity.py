import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import run_backtest
from app.backtest.portfolio import run_portfolio_backtest
from app.catalog import find_asset
from app.data.service import DataBundle
from app.models import BacktestRequest, PortfolioAssetInput, PortfolioBacktestRequest
from app.strategies.catalog import default_params, list_strategies
from app.strategies.schedule import contribution_schedule
from app.strategies.signals import generate_target_exposure

# Each pair changes one published parameter while keeping the rest of the strategy valid.
# The shared synthetic history contains trends, reversals, drawdowns, and noisy ranges so
# these are behavior checks rather than assertions that duplicate each indicator formula.
SINGLE_PARAMETER_CASES = [
    ("dca", "every_bars", 5, 30),
    ("dca", "amount_pct", 0.02, 0.2),
    ("dca", "start_delay", 0, 50),
    ("dca", "max_contributions", 2, 20),
    ("dip_dca", "every_bars", 5, 30),
    ("dip_dca", "amount_pct", 0.02, 0.2),
    ("dip_dca", "dip_threshold", 0.02, 0.3),
    ("dip_dca", "dip_multiplier", 1, 5),
    ("dip_dca", "drawdown_lookback", 10, 200),
    ("arithmetic_grid", "lower", 40, 90),
    ("arithmetic_grid", "upper", 110, 180),
    ("arithmetic_grid", "levels", 3, 50),
    ("arithmetic_grid", "base_position", 0, 0.5),
    ("geometric_grid", "lower", 40, 90),
    ("geometric_grid", "upper", 110, 180),
    ("geometric_grid", "levels", 3, 50),
    ("geometric_grid", "base_position", 0, 0.5),
    ("martingale", "rsi_period", 3, 30),
    ("martingale", "entry_rsi", 15, 50),
    ("martingale", "base_position", 0.05, 0.4),
    ("martingale", "multiplier", 1, 4),
    ("martingale", "drawdown_step", 0.01, 0.2),
    ("anti_martingale", "lookback", 2, 100),
    ("anti_martingale", "base_position", 0.05, 0.4),
    ("anti_martingale", "multiplier", 1, 3),
    ("anti_martingale", "level_step", 0.01, 0.2),
    ("anti_martingale", "max_levels", 1, 8),
    ("sma_cross", "fast", 2, 40),
    ("sma_cross", "slow", 41, 200),
    ("sma_cross", "confirm_bars", 1, 10),
    ("sma_cross", "min_gap", 0, 0.1),
    ("sma_cross", "trend_filter", 0, 200),
    ("ema_cross", "fast", 2, 20),
    ("ema_cross", "slow", 21, 200),
    ("ema_cross", "confirm_bars", 1, 10),
    ("ema_cross", "min_gap", 0, 0.1),
    ("ema_cross", "trend_filter", 0, 200),
    ("macd", "fast", 2, 20),
    ("macd", "slow", 21, 100),
    ("macd", "signal", 2, 50),
    ("macd", "confirm_bars", 1, 10),
    ("macd", "zero_line_filter", False, True),
    ("rsi_reversal", "period", 2, 50),
    ("rsi_reversal", "entry", 10, 50),
    ("rsi_reversal", "exit", 40, 90),
    ("rsi_reversal", "entry_confirm", 1, 10),
    ("rsi_reversal", "exit_confirm", 1, 10),
    ("bollinger", "period", 5, 100),
    ("bollinger", "std_dev", 0.5, 4),
    ("bollinger", "exit_ratio", 0, 1),
    ("bollinger", "min_bandwidth", 0, 0.5),
    ("breakout", "entry_lookback", 5, 200),
    ("breakout", "exit_lookback", 2, 100),
    ("breakout", "confirm_bars", 1, 10),
    ("breakout", "breakout_buffer", 0, 0.1),
    ("momentum", "lookback", 2, 200),
    ("momentum", "threshold", -0.1, 0.5),
    ("momentum", "smoothing", 1, 30),
    ("momentum", "exit_threshold", -0.2, 0.2),
]

SCHEDULE_PARAMETER_CASES = [
    ("every", {"every": 2, "unit": "days"}, {"every": 9, "unit": "days"}),
    ("unit", {"every": 2, "unit": "days"}, {"every": 2, "unit": "weeks"}),
    (
        "start_delay",
        {"every": 2, "unit": "days", "start_delay": 0},
        {"every": 2, "unit": "days", "start_delay": 7},
    ),
]

PORTFOLIO_PARAMETER_CASES = [
    ("all_weather", "rebalance_band", 0, 0.5),
    ("all_weather", "min_trade_rate", 0, 0.05),
    ("risk_parity", "lookback", 40, 300),
    ("risk_parity", "covariance_shrinkage", 0, 1),
    ("risk_parity", "rebalance_band", 0, 0.5),
    ("risk_parity", "min_trade_rate", 0, 0.05),
    ("sixty_forty", "equity_target", 0.2, 0.8),
    ("sixty_forty", "rebalance_band", 0, 0.5),
    ("sixty_forty", "min_trade_rate", 0, 0.05),
]


@pytest.fixture(scope="module")
def signal_frame() -> pd.DataFrame:
    count = 720
    index = pd.date_range("2024-01-01", periods=count, freq="D", tz="UTC")
    step = np.arange(count)
    random = np.random.default_rng(20260914)
    returns = 0.001 * np.sin(step / 4) + 0.004 * np.sin(step / 17) + random.normal(0, 0.012, count)
    returns[100:130] -= 0.02
    returns[130:180] += 0.025
    returns[300:340] -= 0.03
    returns[340:410] += 0.02
    returns[520:580] = 0.005
    close = 100 * np.exp(np.cumsum(returns))
    open_price = close * (1 + random.normal(0, 0.002, count))
    return pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(open_price, close) * 1.02,
            "low": np.minimum(open_price, close) * 0.98,
            "close": close,
            "volume": 1_000_000_000.0,
        },
        index=index,
    )


@pytest.fixture(scope="module")
def constant_bundle() -> DataBundle:
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000_000.0,
        },
        index=index,
    )
    return DataBundle(asset=find_asset("BTC-USD", "crypto"), frame=frame, source="test")


@pytest.fixture(scope="module")
def portfolio_inputs() -> tuple[list[PortfolioAssetInput], list[DataBundle]]:
    index = pd.date_range("2022-01-03", periods=540, freq="D", tz="UTC")
    step = np.arange(len(index))
    symbols = ["SPY", "TLT", "IEF", "GLD", "DBC"]
    paths = [
        100 * np.exp(0.001 * step + 0.05 * np.sin(step / 13)),
        100 * np.exp(-0.0001 * step + 0.08 * np.sin(step / 29 + 1)),
        100 * np.exp(0.0002 * step + 0.025 * np.sin(step / 41 + 2)),
        100 * np.exp(0.0004 * step + 0.10 * np.sin(step / 17 + 3)),
        100 * np.exp(0.00005 * step + 0.14 * np.sin(step / 23 + 4)),
    ]
    bundles = []
    for symbol, close in zip(symbols, paths, strict=True):
        open_price = close * (1 + 0.002 * np.sin(step / 7 + len(symbol)))
        frame = pd.DataFrame(
            {
                "open": open_price,
                "high": np.maximum(open_price, close) * 1.01,
                "low": np.minimum(open_price, close) * 0.99,
                "close": close,
                "volume": 10_000_000.0,
            },
            index=index,
        )
        bundles.append(DataBundle(asset=find_asset(symbol, "etf"), frame=frame, source="test"))
    assets = [PortfolioAssetInput(symbol=symbol, asset_class="etf") for symbol in symbols]
    return assets, bundles


def test_parameter_matrix_covers_every_published_builtin_parameter():
    published = {
        (strategy.id, parameter.key)
        for strategy in list_strategies()
        for parameter in strategy.parameters
    }
    covered = {(strategy, parameter) for strategy, parameter, *_ in SINGLE_PARAMETER_CASES}
    covered.update(("scheduled_dca", parameter) for parameter, *_ in SCHEDULE_PARAMETER_CASES)
    covered.add(("scheduled_dca", "amount"))
    covered.update((strategy, parameter) for strategy, parameter, *_ in PORTFOLIO_PARAMETER_CASES)
    assert covered == published


@pytest.mark.parametrize(
    ("strategy_id", "parameter", "first_value", "second_value"),
    SINGLE_PARAMETER_CASES,
    ids=[f"{strategy}-{parameter}" for strategy, parameter, *_ in SINGLE_PARAMETER_CASES],
)
def test_single_strategy_parameter_changes_target_exposure(
    signal_frame: pd.DataFrame,
    strategy_id: str,
    parameter: str,
    first_value: object,
    second_value: object,
):
    params = default_params(strategy_id)
    if strategy_id in {"arithmetic_grid", "geometric_grid"}:
        params.update(lower=60, upper=160)
    if strategy_id in {"sma_cross", "ema_cross", "macd"}:
        params.update(fast=10, slow=60)

    first_target, _ = generate_target_exposure(
        signal_frame, strategy_id, params | {parameter: first_value}, 0.95
    )
    second_target, _ = generate_target_exposure(
        signal_frame, strategy_id, params | {parameter: second_value}, 0.95
    )

    assert not np.allclose(first_target.to_numpy(), second_target.to_numpy())

    bundle = DataBundle(asset=find_asset("BTC-USD", "crypto"), frame=signal_frame, source="fixture")
    results = [
        run_backtest(
            BacktestRequest(
                strategy_id=strategy_id,
                params=params | {parameter: value},
                max_position=0.95,
                persist=False,
            ),
            bundle,
        )
        for value in (first_value, second_value)
    ]
    assert [trade.model_dump() for trade in results[0].trades] != [
        trade.model_dump() for trade in results[1].trades
    ] or not np.allclose(
        [point.equity for point in results[0].equity],
        [point.equity for point in results[1].equity],
    )


@pytest.mark.parametrize(
    ("parameter", "first_params", "second_params"),
    SCHEDULE_PARAMETER_CASES,
    ids=[parameter for parameter, *_ in SCHEDULE_PARAMETER_CASES],
)
def test_scheduled_dca_calendar_parameter_changes_due_dates(
    parameter: str,
    first_params: dict[str, object],
    second_params: dict[str, object],
):
    del parameter
    index = pd.date_range("2025-01-01", periods=120, freq="D", tz="UTC")
    first = contribution_schedule(
        index,
        int(first_params["every"]),
        str(first_params["unit"]),
        int(first_params.get("start_delay", 0)),
    )
    second = contribution_schedule(
        index,
        int(second_params["every"]),
        str(second_params["unit"]),
        int(second_params.get("start_delay", 0)),
    )
    assert first != second


def test_scheduled_dca_amount_changes_actual_trade_budget(constant_bundle: DataBundle):
    def run(amount: float):
        return run_backtest(
            BacktestRequest(
                strategy_id="scheduled_dca",
                params={"amount": amount, "every": 20, "unit": "days"},
                persist=False,
            ),
            constant_bundle,
        )

    smaller = run(250)
    larger = run(750)
    assert smaller.trades and larger.trades
    assert smaller.trades[0].notional + smaller.trades[0].fee == pytest.approx(250)
    assert larger.trades[0].notional + larger.trades[0].fee == pytest.approx(750)


@pytest.mark.parametrize(
    ("strategy_id", "parameter", "first_value", "second_value"),
    PORTFOLIO_PARAMETER_CASES,
    ids=[f"{strategy}-{parameter}" for strategy, parameter, *_ in PORTFOLIO_PARAMETER_CASES],
)
def test_portfolio_strategy_parameter_changes_orders_weights_or_equity(
    portfolio_inputs: tuple[list[PortfolioAssetInput], list[DataBundle]],
    strategy_id: str,
    parameter: str,
    first_value: object,
    second_value: object,
):
    assets, bundles = portfolio_inputs
    params = default_params(strategy_id)

    def run(value: object):
        return run_portfolio_backtest(
            PortfolioBacktestRequest(
                assets=assets,
                strategy_id=strategy_id,
                rebalance="monthly",
                params=params | {parameter: value},
                commission_rate=0.001,
                slippage_rate=0.001,
                spread_rate=0.001,
                persist=False,
            ),
            bundles,
        )

    first = run(first_value)
    second = run(second_value)
    weights_changed = any(
        not np.isclose(first.weights[symbol], second.weights[symbol]) for symbol in first.weights
    )
    assert (
        len(first.trades) != len(second.trades)
        or weights_changed
        or not np.isclose(first.equity[-1].equity, second.equity[-1].equity)
    )


def test_backtest_execution_cost_inputs_change_reported_costs(constant_bundle: DataBundle):
    common = {
        "strategy_id": "dca",
        "params": {"every_bars": 10, "amount_pct": 0.1},
        "persist": False,
    }
    free = run_backtest(
        BacktestRequest(**common, commission_rate=0, slippage_rate=0, spread_rate=0),
        constant_bundle,
    )
    costly = run_backtest(
        BacktestRequest(
            **common,
            commission_rate=0.01,
            slippage_rate=0.01,
            spread_rate=0.02,
        ),
        constant_bundle,
    )

    assert free.metrics["fees_paid"] == 0
    assert costly.metrics["fees_paid"] > 0
    assert sum(trade.slippage_cost for trade in free.trades) == 0
    assert sum(trade.slippage_cost for trade in costly.trades) > 0
    assert costly.equity[-1].equity < free.equity[-1].equity
