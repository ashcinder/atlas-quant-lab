from datetime import UTC, datetime

import pandas as pd

from app.backtest.portfolio import run_portfolio_backtest
from app.backtest.engine import run_backtest
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
