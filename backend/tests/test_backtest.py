from datetime import UTC, datetime

import pandas as pd
import pytest

from app.backtest.engine import run_backtest
from app.backtest.portfolio import run_portfolio_backtest
from app.catalog import find_asset
from app.data.providers import DemoProvider
from app.data.service import DataBundle
from app.models import BacktestRequest, PortfolioAssetInput, PortfolioBacktestRequest


def make_bundle() -> DataBundle:
    asset = find_asset("BTC-USD", "crypto")
    frame = DemoProvider().fetch_bars(
        asset,
        "1d",
        datetime(2018, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        "auto",
    )
    return DataBundle(asset=asset, frame=frame, source="demo", source_note="test")


def make_portfolio_bundle(symbol: str, daily_return: float) -> DataBundle:
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    values = pd.Series(
        [100 * (1 + daily_return) ** step for step in range(len(index))],
        index=index,
        dtype=float,
    )
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values * 1.01,
            "low": values * 0.99,
            "close": values * 1.002,
            "volume": 1_000_000.0,
        },
        index=index,
    )
    return DataBundle(asset=find_asset(symbol, "etf"), frame=frame, source="test")


def test_backtest_produces_auditable_result():
    request = BacktestRequest(
        symbol="BTC-USD",
        asset_class="crypto",
        interval="1d",
        data_source="demo",
        strategy_id="sma_cross",
        params={"fast": 10, "slow": 40},
        commission_rate=0.001,
        slippage_rate=0.0005,
        spread_rate=0.0005,
        persist=False,
    )
    result = run_backtest(request, make_bundle())
    assert len(result.bars) == len(result.equity)
    assert result.metrics["trade_count"] == len(result.trades)
    assert result.metrics["trade_count"] < 100
    assert result.metrics["fees_paid"] > 0
    assert result.metrics["max_drawdown"] <= 0
    assert result.metrics["benchmark_return"] is not None
    assert set(result.regime_metrics) == {"牛市", "熊市", "震荡"}
    assert any("下一根K线" in warning for warning in result.warnings)
    assert any("演示数据" in warning for warning in result.warnings)


def test_trade_execution_price_includes_costs():
    request = BacktestRequest(
        symbol="BTC-USD",
        asset_class="crypto",
        interval="1d",
        data_source="demo",
        strategy_id="dca",
        params={"every_bars": 10, "amount_pct": 0.05},
        commission_rate=0.002,
        slippage_rate=0.001,
        spread_rate=0.002,
        persist=False,
    )
    result = run_backtest(request, make_bundle())
    bars_by_time = {bar.time: bar for bar in result.bars}
    first_buy = next(trade for trade in result.trades if trade.side == "buy")
    assert first_buy.price > bars_by_time[first_buy.time].open
    assert first_buy.fee > 0
    assert first_buy.slippage_cost > 0


def test_portfolio_daily_bars_align_by_session_date_across_timezones():
    index = pd.date_range("2024-01-01", periods=90, freq="D", tz="UTC")

    def bundle(symbol: str, hour_shift: int) -> DataBundle:
        shifted = index.shift(hour_shift, freq="h")
        values = pd.Series(range(100, 190), index=shifted, dtype=float)
        frame = pd.DataFrame(
            {
                "open": values,
                "high": values * 1.01,
                "low": values * 0.99,
                "close": values * 1.005,
                "volume": 1_000.0,
            },
            index=shifted,
        )
        return DataBundle(asset=find_asset(symbol, "etf"), frame=frame, source="test")

    request = PortfolioBacktestRequest(
        assets=[
            PortfolioAssetInput(symbol="SPY", asset_class="etf", weight=0.6),
            PortfolioAssetInput(symbol="GLD", asset_class="etf", weight=0.4),
        ],
        strategy_id="sixty_forty",
        interval="1d",
        initial_capital=100_000,
        persist=False,
    )
    result = run_portfolio_backtest(request, [bundle("SPY", 4), bundle("GLD", -8)])

    assert len(result.equity) == 90
    assert any("按交易日期规范化" in warning for warning in result.warnings)


def test_portfolio_parameters_control_allocation_and_execution_costs():
    bundles = [make_portfolio_bundle("SPY", 0.001), make_portfolio_bundle("TLT", 0.0002)]
    request = PortfolioBacktestRequest(
        assets=[
            PortfolioAssetInput(symbol="SPY", asset_class="etf", weight=0.5),
            PortfolioAssetInput(symbol="TLT", asset_class="etf", weight=0.5),
        ],
        strategy_id="sixty_forty",
        params={"equity_target": 0.7, "rebalance_band": 0.02, "min_trade_rate": 0.0},
        interval="1d",
        initial_capital=100_000,
        commission_rate=0.002,
        slippage_rate=0.001,
        spread_rate=0.002,
        cash_buffer=0.1,
        max_asset_weight=0.8,
        persist=False,
    )

    result = run_portfolio_backtest(request, bundles)
    initial_weights = result.weight_history[0]["weights"]
    assert 0.61 < initial_weights["SPY"] < 0.65
    assert 0.25 < initial_weights["TLT"] < 0.29
    assert sum(initial_weights.values()) < 0.92
    first_trade = result.trades[0]
    first_open = float(bundles[0].frame.iloc[0]["open"])
    assert first_trade.price > first_open
    assert first_trade.fee > 0
    assert any("现金缓冲" in warning for warning in result.warnings)


def test_portfolio_rejects_unknown_or_out_of_range_strategy_parameters():
    bundles = [make_portfolio_bundle("SPY", 0.001), make_portfolio_bundle("TLT", 0.0002)]
    common = {
        "assets": [
            PortfolioAssetInput(symbol="SPY", asset_class="etf", weight=0.6),
            PortfolioAssetInput(symbol="TLT", asset_class="etf", weight=0.4),
        ],
        "strategy_id": "risk_parity",
        "data_source": "demo",
        "persist": False,
    }

    with pytest.raises(ValueError, match="未知参数"):
        run_portfolio_backtest(
            PortfolioBacktestRequest(**common, params={"unsupported": 1}), bundles
        )
    with pytest.raises(ValueError, match="协方差收缩 不能大于"):
        run_portfolio_backtest(
            PortfolioBacktestRequest(**common, params={"covariance_shrinkage": 1.1}),
            bundles,
        )
