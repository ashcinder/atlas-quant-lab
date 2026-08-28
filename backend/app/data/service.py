from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.catalog import find_asset
from app.config import CACHE_DIR
from app.data.providers import (
    BinanceProvider,
    DemoProvider,
    MarketDataProvider,
    ProviderError,
    SinaProvider,
    TencentProvider,
    YahooProvider,
)
from app.models import Asset


@dataclass
class DataBundle:
    asset: Asset
    frame: pd.DataFrame
    source: str
    source_note: str | None = None
    fetched_at: datetime | None = None
    cache_hit: bool = False
    is_stale: bool = False


class MarketDataService:
    CACHE_TTL_SECONDS = {"15m": 15, "1h": 30, "4h": 60, "1d": 120, "1wk": 300}

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.providers: dict[str, MarketDataProvider] = {
            "yahoo": YahooProvider(),
            "sina": SinaProvider(),
            "tencent": TencentProvider(),
            "binance": BinanceProvider(),
            "demo": DemoProvider(),
        }

    def _cache_path(
        self,
        provider: str,
        symbol: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> Path:
        key = json.dumps(
            [
                provider,
                symbol,
                interval,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
                adjustment,
            ],
            ensure_ascii=False,
        )
        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        return (
            self.cache_dir
            / f"{provider}_{symbol.replace('/', '_').replace('=', '-')}_{interval}_{digest}.csv.gz"
        )

    def _read_cache(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        try:
            frame = pd.read_csv(path, index_col=0, parse_dates=True)
            frame.index = pd.to_datetime(frame.index, utc=True)
            return frame
        except Exception:
            return None

    def _write_cache(self, path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, compression="gzip")

    @staticmethod
    def _cache_time(path: Path) -> datetime:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    def _cache_is_fresh(self, path: Path, interval: str, end: datetime | None) -> bool:
        if end is not None:
            end_time = pd.Timestamp(end)
            end_time = (
                end_time.tz_localize("UTC")
                if end_time.tzinfo is None
                else end_time.tz_convert("UTC")
            )
            if end_time < pd.Timestamp.now(tz="UTC"):
                return True
        age = (datetime.now(UTC) - self._cache_time(path)).total_seconds()
        return age <= self.CACHE_TTL_SECONDS[interval]

    def fetch(
        self,
        symbol: str,
        asset_class: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str = "auto",
        source: str = "auto",
        refresh: bool = False,
    ) -> DataBundle:
        asset = find_asset(symbol, asset_class)
        if asset.asset_class == "unknown":
            asset.asset_class = asset_class
        candidates = [source]
        if source in {"auto", "yahoo"}:
            if asset.asset_class == "crypto":
                candidates = ["binance", "yahoo"]
            elif asset.exchange == "HKEX":
                candidates = ["tencent", "yahoo"]
            else:
                candidates = ["sina", "yahoo"]
        errors: list[str] = []
        stale_fallbacks: list[DataBundle] = []
        minimum_bars = 8 if asset.exchange == "HKEX" and interval == "4h" else 30
        for provider_name in candidates:
            provider = self.providers[provider_name]
            if provider_name == "demo":
                frame = provider.fetch_bars(asset, interval, start, end, adjustment)
                return DataBundle(
                    asset=asset,
                    frame=frame,
                    source="demo",
                    source_note="离线演示数据，不是真实行情",
                    fetched_at=datetime.now(UTC),
                )
            cache_path = self._cache_path(
                provider_name, asset.symbol, interval, start, end, adjustment
            )
            cached = self._read_cache(cache_path)
            if (
                cached is not None
                and len(cached) >= minimum_bars
                and not refresh
                and self._cache_is_fresh(cache_path, interval, end)
            ):
                return DataBundle(
                    asset=asset,
                    frame=cached,
                    source=f"{provider_name}:cache",
                    source_note="真实行情缓存命中",
                    fetched_at=self._cache_time(cache_path),
                    cache_hit=True,
                )
            try:
                fetch_start = start
                if cached is not None and len(cached) >= 3 and end is None:
                    overlap_start = cached.index[-3].to_pydatetime()
                    fetch_start = max(start, overlap_start) if start else overlap_start
                fresh = provider.fetch_bars(asset, interval, fetch_start, end, adjustment)
                frame = (
                    pd.concat([cached, fresh])
                    .loc[lambda value: ~value.index.duplicated(keep="last")]
                    .sort_index()
                    if cached is not None
                    else fresh
                )
                if len(frame) < minimum_bars:
                    raise ProviderError(f"有效K线少于{minimum_bars}根")
                self._write_cache(cache_path, frame)
                return DataBundle(
                    asset=asset,
                    frame=frame,
                    source=provider_name,
                    source_note="已刷新至数据源最新可用K线",
                    fetched_at=datetime.now(UTC),
                )
            except ProviderError as exc:
                errors.append(str(exc))
                if cached is not None and len(cached) >= minimum_bars:
                    stale_fallbacks.append(
                        DataBundle(
                            asset=asset,
                            frame=cached,
                            source=f"{provider_name}:stale-cache",
                            source_note=f"实时刷新失败，当前显示上次真实缓存：{exc}",
                            fetched_at=self._cache_time(cache_path),
                            cache_hit=True,
                            is_stale=True,
                        )
                    )
        if stale_fallbacks:
            return stale_fallbacks[0]
        raise ProviderError("；".join(errors) or "真实数据源不可用")

    def convert_to_base_currency(
        self,
        bundle: DataBundle,
        base_currency: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        source: str,
    ) -> DataBundle:
        """Convert OHLC prices to the portfolio base currency using historical FX.

        USD and USDT are treated as equivalent for historical research. Demo
        data uses explicit fixed illustrative rates; real data uses the configured
        FX providers and never silently falls back to a made-up rate.
        """
        source_currency = bundle.asset.currency.upper()
        target_currency = base_currency.upper()
        if source_currency == target_currency or {
            source_currency,
            target_currency,
        } <= {"USD", "USDT"}:
            return bundle

        if bundle.source == "demo" or source == "demo":
            cny_value = {"CNY": 1.0, "USD": 7.2, "USDT": 7.2, "HKD": 0.92}
            if source_currency not in cny_value or target_currency not in cny_value:
                raise ProviderError(f"演示汇率暂不支持 {source_currency}/{target_currency}")
            rate = cny_value[source_currency] / cny_value[target_currency]
            converted = bundle.frame.copy()
            converted[["open", "high", "low", "close"]] *= rate
            return DataBundle(
                asset=bundle.asset.model_copy(update={"currency": target_currency}),
                frame=converted,
                source=bundle.source,
                source_note=(bundle.source_note or "")
                + f"；演示汇率 {source_currency}/{target_currency}={rate:.6f}",
            )

        frame_start = start or bundle.frame.index.min().to_pydatetime()
        frame_end = end or (bundle.frame.index.max() + pd.Timedelta(days=8)).to_pydatetime()
        rate = self._historical_fx_rate(
            source_currency,
            target_currency,
            interval,
            frame_start,
            frame_end,
        )
        aligned_rate = rate.reindex(bundle.frame.index, method="ffill")
        valid = aligned_rate.notna()
        if valid.sum() < 30:
            raise ProviderError(f"{source_currency}/{target_currency} 历史汇率与行情共同数据不足")
        converted = bundle.frame.loc[valid].copy()
        converted[["open", "high", "low", "close"]] = converted[
            ["open", "high", "low", "close"]
        ].mul(aligned_rate.loc[valid], axis=0)
        return DataBundle(
            asset=bundle.asset.model_copy(update={"currency": target_currency}),
            frame=converted,
            source=bundle.source,
            source_note=(bundle.source_note or "")
            + f"；已按历史汇率换算 {source_currency}→{target_currency}",
        )

    def _historical_fx_rate(
        self,
        source_currency: str,
        target_currency: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.Series:
        target = "USD" if target_currency == "USDT" else target_currency
        source = "USD" if source_currency == "USDT" else source_currency

        def fx_close(symbol: str) -> pd.Series:
            asset = Asset(
                symbol=symbol,
                name=symbol,
                asset_class="forex",
                exchange="FX",
                currency=target,
            )
            errors: list[str] = []
            for provider_name in ("yahoo", "sina"):
                try:
                    return self.providers[provider_name].fetch_bars(
                        asset, interval, start, end, "raw"
                    )["close"]
                except ProviderError as exc:
                    errors.append(str(exc))
            raise ProviderError("；".join(errors))

        if source == "USD" and target in {"CNY", "HKD"}:
            return fx_close(f"{target}=X")
        if target == "USD" and source in {"CNY", "HKD"}:
            return 1 / fx_close(f"{source}=X")
        if source == "HKD" and target == "CNY":
            try:
                return fx_close("HKDCNY=X")
            except ProviderError:
                return fx_close("CNY=X") / fx_close("HKD=X")
        if source == "CNY" and target == "HKD":
            try:
                return fx_close("CNYHKD=X")
            except ProviderError:
                return fx_close("HKD=X") / fx_close("CNY=X")
        try:
            return fx_close(f"{source}{target}=X")
        except ProviderError as direct_error:
            try:
                return 1 / fx_close(f"{target}{source}=X")
            except ProviderError as inverse_error:
                raise ProviderError(
                    f"无法取得 {source_currency}/{target_currency} 历史汇率: "
                    f"{direct_error}; {inverse_error}"
                ) from inverse_error
