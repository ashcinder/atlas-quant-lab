"""Publish immutable market snapshots independently of HTTP computation requests."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.catalog import find_asset
from app.data.service import DataBundle, MarketDataService
from app.market_publication import MarketPublication
from app.models import Adjustment, Interval


class PublicationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=64)
    asset_class: str = Field(default="crypto", max_length=32)
    interval: Interval = "1d"
    adjustment: Adjustment = "auto"
    data_source: Literal["auto", "binance", "yahoo", "sina", "tencent", "demo"] = "auto"
    start: datetime | None = None
    end: datetime | None = None
    base_currencies: list[Literal["CNY", "USD", "USDT"]] = Field(default_factory=list, max_length=3)

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, value):
        return value.strip().upper()

    @field_validator("start", "end")
    @classmethod
    def utc_date(cls, value):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def dates(self):
        if not self.symbol or self.start and self.end and self.start >= self.end:
            raise ValueError("无效标的或日期区间")
        self.base_currencies = list(dict.fromkeys(self.base_currencies))
        return self


def cached_bundle(service: MarketDataService, query: PublicationQuery) -> DataBundle:
    asset = find_asset(query.symbol, query.asset_class)
    if asset.asset_class == "unknown":
        asset.asset_class = query.asset_class
    if query.data_source == "demo":
        raise ValueError("缓存发布不生成演示数据")
    if query.data_source != "auto":
        providers = [query.data_source]
    elif asset.asset_class == "crypto":
        providers = ["binance", "yahoo"]
    elif asset.exchange == "HKEX":
        providers = ["tencent", "yahoo"]
    else:
        providers = ["sina", "yahoo"]
    matches = []
    for provider in providers:
        path = service._cache_path(provider, asset.symbol, query.interval, query.start, query.end, query.adjustment)
        frame = service.store.read(path.name)
        stamp = service.store.timestamp(path.name)
        if frame is not None and stamp is not None and len(frame) >= 3:
            matches.append((provider, path, frame, stamp))
    if not matches:
        raise ValueError("没有匹配来源、复权和日期的精确缓存；请先独立采集")
    if len(matches) != 1:
        raise ValueError("auto 匹配多个来源缓存；请在配置中指定 data_source")
    provider, path, frame, stamp = matches[0]
    return DataBundle(asset=asset, frame=frame, source=f"{provider}:cache",
                      source_note="独立发布的精确历史缓存；未访问上游数据源", fetched_at=stamp,
                      cache_hit=True, is_stale=not service._cache_is_fresh(path, query.interval, query.end))


def publish_query(service, publications, query: PublicationQuery, cached_only: bool = False) -> dict:
    request = query.model_dump(exclude={"base_currencies"})
    bundle = cached_bundle(service, query) if cached_only else service.fetch(
        query.symbol, query.asset_class, query.interval, query.start, query.end,
        query.adjustment, query.data_source, refresh=True)
    # Some feeds return contradictory OHLC values on non-trading days. Do not
    # invent replacement prices or publish chunks that clients must reject.
    frame = bundle.frame
    valid = (frame[["open", "high", "low", "close", "volume"]].notna().all(axis=1)
             & (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
             & (frame["high"] >= frame[["open", "close"]].max(axis=1))
             & (frame["low"] <= frame[["open", "close"]].min(axis=1))
             & (frame["volume"] >= 0)
             & ~frame.isin([float("inf"), float("-inf")]).any(axis=1))
    rejected = int((~valid).sum())
    if rejected:
        bundle = replace(bundle, frame=frame.loc[valid].copy(),
                         source_note=f"{bundle.source_note or ''}；发布时剔除{rejected}根无效OHLC/成交量K线，未补造价格")
    if len(bundle.frame) < 3:
        raise ValueError("有效行情少于3根，保留原发布版本")
    source_currency = bundle.asset.currency.upper()
    # Cache-only means no provider calls at all, including hidden historical FX.
    if cached_only and any(currency != source_currency and not {currency, source_currency} <= {"USD", "USDT"}
                           for currency in query.base_currencies):
        raise ValueError("缓存发布不能抓取历史汇率；请去掉跨币种换算或使用独立正常采集")
    conversions = {}
    for currency in query.base_currencies:
        converted = service.convert_to_base_currency(bundle, currency, query.interval, query.start, query.end, query.data_source)
        converted = replace(converted, asset=converted.asset.model_copy(update={"currency": currency}),
                            fetched_at=bundle.fetched_at, is_stale=bundle.is_stale or converted.is_stale)
        conversion = publications.publish({**request, "base_currency": currency}, converted)
        conversions[currency] = conversion["dataset_id"]
    # Readers see the new base version only once every referenced conversion exists.
    manifest = publications.publish(request, bundle, conversions)
    return {"symbol": query.symbol, "dataset_id": manifest["dataset_id"], "count": manifest["count"],
            "source": manifest["source"], "is_stale": manifest["is_stale"], "conversions": conversions}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True, help="JSON array of explicit market query configurations")
    schedule = result.add_mutually_exclusive_group()
    schedule.add_argument("--once", action="store_true", help="Publish once and exit (default)")
    schedule.add_argument("--interval", type=int, metavar="SECONDS", help="Repeat independently; minimum 30 seconds")
    result.add_argument("--cached-only", action="store_true", help="Only exact SQLite snapshots; never fetch providers or FX")
    return result


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.interval is not None and args.interval < 30:
        arguments.error("--interval 至少30秒")
    try:
        raw = json.loads(args.config.read_text())
        if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
            raise ValueError("配置必须包含1–500项查询")
        queries = [PublicationQuery.model_validate(query) for query in raw]
    except (OSError, ValueError, TypeError):
        arguments.error("无法读取有效行情发布配置")
    service, publications = MarketDataService(), MarketPublication()
    try:
        while True:
            failed = False
            for query in queries:
                try:
                    print(json.dumps({"status": "published", **publish_query(service, publications, query, args.cached_only)}, ensure_ascii=False), flush=True)
                except Exception:
                    failed = True
                    print(json.dumps({"status": "failed", "symbol": query.symbol,
                                      "message": "采集、缓存或换算不满足发布条件；原已发布版本保留"}, ensure_ascii=False), flush=True)
            if args.interval is None:
                return int(failed)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
