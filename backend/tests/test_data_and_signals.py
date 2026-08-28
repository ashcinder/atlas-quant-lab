from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.catalog import find_asset
from app.data.providers import DemoProvider, ProviderError
from app.data.service import DataBundle, MarketDataService
from app.strategies.catalog import list_strategies
from app.strategies.signals import generate_target_exposure


def demo_frame(symbol: str = "BTC-USD") -> pd.DataFrame:
    return DemoProvider().fetch_bars(
        find_asset(symbol, "crypto"),
        "1d",
        datetime(2021, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
        "auto",
    )


def test_demo_provider_is_deterministic_and_valid():
    first = demo_frame()
    second = demo_frame()
    pd.testing.assert_frame_equal(first, second)
    assert len(first) > 100
    assert (first["high"] >= first[["open", "close"]].max(axis=1)).all()
    assert (first["low"] <= first[["open", "close"]].min(axis=1)).all()
    assert (first["volume"] > 0).all()


def test_signal_has_no_future_dependency():
    frame = demo_frame()
    original, _ = generate_target_exposure(frame, "sma_cross", {"fast": 10, "slow": 30}, 0.95)
    changed = frame.copy()
    changed.loc[changed.index[-20] :, "close"] *= np.linspace(1, 4, 20)
    recalculated, _ = generate_target_exposure(changed, "sma_cross", {"fast": 10, "slow": 30}, 0.95)
    pd.testing.assert_series_equal(original.iloc[:-20], recalculated.iloc[:-20])


def test_demo_currency_conversion_is_explicit_and_deterministic(tmp_path):
    frame = demo_frame("AAPL")
    asset = find_asset("AAPL", "equity")
    bundle = DataBundle(asset=asset, frame=frame, source="demo", source_note="演示")
    converted = MarketDataService(tmp_path).convert_to_base_currency(
        bundle, "CNY", "1d", None, None, "demo"
    )
    assert converted.asset.currency == "CNY"
    assert np.isclose(converted.frame.close.iloc[0], frame.close.iloc[0] * 7.2)
    assert "演示汇率" in (converted.source_note or "")


class FailingProvider:
    def fetch_bars(self, *_args, **_kwargs):
        raise ProviderError("真实源测试失败")


class CountingProvider:
    def __init__(self):
        self.calls = 0
        self.frame = pd.DataFrame(
            {
                "open": np.arange(100, dtype=float) + 100,
                "high": np.arange(100, dtype=float) + 102,
                "low": np.arange(100, dtype=float) + 99,
                "close": np.arange(100, dtype=float) + 101,
                "volume": np.arange(100, dtype=float) + 1_000,
            },
            index=pd.date_range("2026-01-01", periods=100, freq="1D", tz="UTC"),
        )

    def fetch_bars(self, _asset, _interval, start, end, _adjustment):
        self.calls += 1
        frame = self.frame
        if start is not None:
            frame = frame.loc[frame.index >= pd.Timestamp(start)]
        if end is not None:
            frame = frame.loc[frame.index <= pd.Timestamp(end)]
        return frame.copy()


def test_auto_source_never_silently_falls_back_to_demo(tmp_path):
    service = MarketDataService(tmp_path)
    service.providers["binance"] = FailingProvider()  # type: ignore[assignment]
    service.providers["yahoo"] = FailingProvider()  # type: ignore[assignment]
    with pytest.raises(ProviderError, match="真实源测试失败"):
        service.fetch("BTC-USD", "crypto", "1d", None, None, source="auto")


def test_real_cache_has_ttl_and_supports_forced_incremental_refresh(tmp_path):
    provider = CountingProvider()
    service = MarketDataService(tmp_path)
    service.providers["binance"] = provider  # type: ignore[assignment]
    first = service.fetch("BTC-USD", "crypto", "1d", None, None, source="binance")
    cached = service.fetch("BTC-USD", "crypto", "1d", None, None, source="binance")
    refreshed = service.fetch(
        "BTC-USD", "crypto", "1d", None, None, source="binance", refresh=True
    )
    assert provider.calls == 2
    assert first.source == "binance"
    assert cached.source == "binance:cache"
    assert cached.cache_hit is True
    assert refreshed.source == "binance"
    assert len(refreshed.frame) == len(provider.frame)


def test_auto_non_crypto_source_uses_accessible_broad_provider(tmp_path):
    provider = CountingProvider()
    service = MarketDataService(tmp_path)
    service.providers["sina"] = provider  # type: ignore[assignment]
    service.providers["yahoo"] = FailingProvider()  # type: ignore[assignment]
    result = service.fetch("AAPL", "equity", "1d", None, None, source="auto")
    assert result.source == "sina"
    assert len(result.frame) == 100
    assert provider.calls == 1


def test_all_single_strategies_return_bounded_targets():
    frame = demo_frame()
    configurations = {
        "dca": {},
        "dip_dca": {},
        "arithmetic_grid": {
            "lower": frame.close.quantile(0.15),
            "upper": frame.close.quantile(0.85),
        },
        "geometric_grid": {
            "lower": frame.close.quantile(0.15),
            "upper": frame.close.quantile(0.85),
        },
        "martingale": {},
        "anti_martingale": {},
        "sma_cross": {},
        "ema_cross": {},
        "macd": {},
        "rsi_reversal": {},
        "bollinger": {},
        "breakout": {},
        "momentum": {},
    }
    for strategy_id, params in configurations.items():
        target, reasons = generate_target_exposure(frame, strategy_id, params, 0.95)
        assert len(target) == len(frame), strategy_id
        assert target.between(0, 0.95).all(), strategy_id
        assert reasons.notna().all(), strategy_id


def test_single_strategy_catalog_exposes_meaningful_parameter_depth():
    singles = list_strategies("single")
    assert singles
    assert all(4 <= len(strategy.parameters) <= 5 for strategy in singles)
    sma = next(strategy for strategy in singles if strategy.id == "sma_cross")
    assert {"fast", "slow", "confirm_bars", "min_gap", "trend_filter"} == {
        parameter.key for parameter in sma.parameters
    }


def test_sma_confirmation_and_gap_filters_change_exposure_without_future_data():
    frame = demo_frame()
    baseline, _ = generate_target_exposure(
        frame, "sma_cross", {"fast": 10, "slow": 30}, 0.95
    )
    filtered, _ = generate_target_exposure(
        frame,
        "sma_cross",
        {"fast": 10, "slow": 30, "confirm_bars": 5, "min_gap": 0.03},
        0.95,
    )
    assert filtered.sum() < baseline.sum()
