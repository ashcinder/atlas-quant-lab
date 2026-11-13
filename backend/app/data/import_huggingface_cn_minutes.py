"""Import the pinned Hugging Face A-share snapshot for charts and research backtests.

The upstream snapshot is huge; this command downloads only mainland equities
already present in this project's catalog. Its provenance is not disclosed and
cross-source daily OHLCV can disagree. Keep this an explicit, immutable source;
never splice it with live quotes or claim exchange-level verification.

Run from ``backend`` with PyArrow installed:
    python -m app.data.import_huggingface_cn_minutes
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from app.catalog import ASSETS, find_asset
from app.config import DATA_DIR
from app.data.service import DataBundle
from app.market_publication import MarketPublication, query_key

REPO = "neigezhu/china-a-share-1min-ohlcv"
REVISION = "ba589a11534825044fe5a6b84838f50ba8d8d188"
EXCHANGE = {"SS": "SH", "SZ": "SZ"}
PERIODS = {"5m": 5, "15m": 15, "1h": 60}
CHUNK_SIZE = 2000
SOURCE = "hf-ohlcv"
SCHEMA = "hf-session-open-v3"
TZ = ZoneInfo("Asia/Shanghai")
FIELDS = ("open", "high", "low", "close", "volume")


def project_equities() -> dict[str, str]:
    return {
        asset.symbol: asset.name
        for asset in ASSETS
        if asset.asset_class == "equity"
        and asset.exchange in ("SSE", "SZSE")
        and asset.symbol.endswith((".SS", ".SZ"))
    }


def fetch_file(client: httpx.Client, path: Path, filename: str) -> bytes:
    if path.exists():
        return path.read_bytes()
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{filename}"
    response = client.get(url)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(response.content)
    temporary.replace(path)
    return response.content


def normalize_bars(path: Path, symbol: str, exchange: str, expected_rows: int) -> pd.DataFrame:
    frame = pq.read_table(path).to_pandas()
    if len(frame) != expected_rows:
        raise ValueError(f"{symbol} 根数与上游覆盖清单不符: {len(frame)} != {expected_rows}")
    if frame.empty or frame["symbol"].nunique() != 1 or str(frame["symbol"].iloc[0]) != symbol:
        raise ValueError(f"{symbol} Parquet 内容与证券代码不符")
    if frame["exchange"].nunique() != 1 or str(frame["exchange"].iloc[0]) != exchange:
        raise ValueError(f"{symbol} Parquet 交易所代码不符")
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"))).tz_localize(TZ).tz_convert("UTC")
    frame = frame[list(FIELDS)].astype(float).sort_index()
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol} 分钟时间重复或乱序")
    prices = frame[["open", "high", "low", "close"]]
    invalid = (
        ~np.isfinite(frame[list(FIELDS)]).all(axis=1)
        | (prices <= 0).any(axis=1)
        | (frame.high < prices[["open", "close"]].max(axis=1))
        | (frame.low > prices[["open", "close"]].min(axis=1))
        | (frame.volume < 0)
    )
    if invalid.any():
        raise ValueError(f"{symbol} 有 {int(invalid.sum())} 根 OHLCV 无效")
    return frame


def aggregate_minutes(frame: pd.DataFrame, period: int) -> pd.DataFrame:
    """Fold the opening observation into the first minute; label bars at open.

    Source labels are 09:30, 09:31..11:30, 13:01..15:00. A complete
    first bucket has period+1 observations. Never pad, interpolate or cross lunch.
    """
    if period not in (1, 5, 15, 60):
        raise ValueError("unsupported minute period")
    local = frame.tz_convert(TZ)
    clock = local.index.hour * 60 + local.index.minute
    morning = (clock >= 570) & (clock <= 690)
    afternoon = (clock >= 781) & (clock <= 900)
    if not (morning | afternoon).all() or local.index.has_duplicates:
        raise ValueError("数据包含重复或沪深常规交易时段以外的记录")
    starts = np.where(morning, 570, 780)
    offsets = np.maximum(0, clock - starts - 1)
    bucket_open = starts + (offsets // period) * period
    labels = local.index.normalize() + pd.to_timedelta(bucket_open, unit="min")
    work = local.copy()
    work["_label"] = labels
    result = work.groupby("_label", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), count=("volume", "size"))
    expected = np.where((result.index.hour * 60 + result.index.minute) == 570, period + 1, period)
    result = result.loc[result["count"].to_numpy() == expected, list(FIELDS)]
    if result.empty:
        raise ValueError(f"无法生成完整的 {period} 分钟K线")
    return result.tz_convert("UTC")


def aggregate_days(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame.tz_convert(TZ)
    result = local.groupby(local.index.normalize()).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), count=("volume", "size"))
    result = result.loc[result["count"] == 241, list(FIELDS)]
    result.index = result.index + pd.Timedelta(hours=9, minutes=30)
    return result.tz_convert("UTC")


def aggregate_weeks(daily: pd.DataFrame, trading_days: set[str]) -> pd.DataFrame:
    local = daily.tz_convert(TZ)
    labels = local.index.normalize() - pd.to_timedelta(local.index.weekday, unit="d")
    work = local.copy()
    work["_week"] = labels
    output = []
    for week, group in work.groupby("_week", sort=True):
        expected = {str((week + pd.Timedelta(days=i)).date()) for i in range(7)} & trading_days
        actual = {str(t.date()) for t in group.index}
        if not expected or actual != expected:
            continue
        output.append(dict(time=week + pd.Timedelta(hours=9, minutes=30), open=group.open.iloc[0],
            high=group.high.max(), low=group.low.min(), close=group.close.iloc[-1], volume=group.volume.sum()))
    if not output:
        raise ValueError("没有完整周线")
    return pd.DataFrame(output).set_index("time").tz_convert("UTC")


def publish_frame(
    publications: MarketPublication,
    symbol: str,
    interval: str,
    frame: pd.DataFrame,
    fetched_at: datetime,
    first_source_time: str,
    last_source_time: str,
) -> dict:
    asset = find_asset(symbol, "equity")
    note = (
        f"Hugging Face 数据集 {REPO}，固定版本 {REVISION}；不复权，成交量单位股。"
        "上游不披露底层数据提供方；数据集自报交易日覆盖审计，但无法独立核验提供方。"
        "与其他来源日线可能存在 OHLCV 差异；作为独立历史源用于研究回测，未声称经交易所独立核验。"
        f"原始标签范围（北京时间 {first_source_time} 至 {last_source_time}）；规范化版本 {SCHEMA}。"
        "09:30开盘观察并入首根1分钟；所有周期使用UTC开盘时间。仅完整分钟组聚合，不跨午休、不插值；零成交记录保留但不得成交。"
        "快照构建于 2026-08-21；2026-08-07 仅有截至 10:21 的部分时段，完整交易日数据截至 2026-08-06。"
    )
    bundle = DataBundle(asset=asset, frame=frame, source=SOURCE, source_note=note, fetched_at=fetched_at)
    query = {
        "symbol": symbol, "asset_class": "equity", "interval": interval,
        "adjustment": "raw", "data_source": "huggingface",
        "start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat(),
    }
    coverage_end = frame.index[-1].tz_convert(TZ).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    if interval in ("1m", "5m", "15m", "1h"):
        # Do not claim the partial final snapshot session as an entire day.
        last_close = frame.index[-1] + pd.Timedelta(minutes={"1m":1,"5m":5,"15m":15,"1h":60}[interval])
        if last_close.tz_convert(TZ).hour < 15:
            coverage_end = last_close
    if interval == "1wk":
        coverage_end = frame.index[-1].tz_convert(TZ).normalize() + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    coverage = {"start": int(frame.index[0].tz_convert(TZ).normalize().timestamp()),
        "end": int(coverage_end.timestamp()), "basis": "complete-session-calendar; partial final session bounded"}
    manifest = publications.publish(query, bundle, chunk_size=CHUNK_SIZE, coverage=coverage)
    encoded = json.dumps({k: v for k, v in manifest.items() if k != "status"}, ensure_ascii=False, allow_nan=False)
    with publications.connect() as db:
        for adjustment in ("auto", "raw"):
            db.execute(
                "INSERT OR REPLACE INTO market_publications VALUES (?,?,?)",
                (query_key({**query, "adjustment": adjustment}), manifest["dataset_id"], encoded),
            )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", help="项目目录中的沪深 A 股代码，默认全部 35 只")
    parser.add_argument("--download-only", action="store_true", help="只下载并校验 Parquet，不发布到图表")
    args = parser.parse_args(argv)
    universe = project_equities()
    selected = args.symbols or list(universe)
    if any(symbol not in universe for symbol in selected):
        parser.error("仅支持项目目录中的沪深 A 股代码")

    root = DATA_DIR / "cn-tech" / "huggingface"
    metadata_dir = root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(
        trust_env=True, timeout=180, follow_redirects=True,
        headers={"User-Agent": "AtlasQuantLocalImport/1.0"},
    )
    try:
        coverage_path = root / "coverage_by_instrument.csv"
        fetch_file(client, coverage_path, "metadata/coverage_by_instrument.csv")
        fetch_file(client, root / "LICENSE", "LICENSE")
        for metadata_name in ("source_provenance.json", "summary.json", "market_calendar.csv"):
            fetch_file(client, metadata_dir / metadata_name, f"metadata/{metadata_name}")
        with coverage_path.open(encoding="utf-8", newline="") as handle:
            coverage = {row["symbol"]: row for row in csv.DictReader(handle)}
        with (metadata_dir / "market_calendar.csv").open(encoding="utf-8", newline="") as handle:
            trading_days = {row["date"] for row in csv.DictReader(handle) if row["calendar_status"] == "trading_day"}
        reports = []
        publications = MarketPublication()
        fetched_at = datetime.now(UTC)
        for symbol in selected:
            code, suffix = symbol.split(".")
            exchange = EXCHANGE[suffix]
            info = coverage.get(code)
            if info is None or info["exchange"] != exchange:
                raise ValueError(f"{symbol} 不在固定版本的上游清单中")
            if int(info["audited_missing_trading_days"]) != 0:
                raise ValueError(f"{symbol} 上游审计记录仍有未解决的交易日缺口")
            filename = f"data/stock_1m/{exchange}/{code}.parquet"
            path = root / filename
            raw = fetch_file(client, path, filename)
            frame = normalize_bars(path, code, exchange, int(info["records"]))
            local = frame.tz_convert(TZ)
            source_sha256 = hashlib.sha256(raw).hexdigest()
            if args.download_only:
                reports.append({"symbol": symbol, "rows": len(frame), "sha256": hashlib.sha256(raw).hexdigest(), "status": "downloaded"})
                print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
                continue

            daily = None
            for interval in ("1m", *PERIODS, "4h", "1d", "1wk"):
                existing = publications.lookup({
                    "symbol": symbol, "asset_class": "equity", "interval": interval,
                    "adjustment": "raw", "data_source": "huggingface",
                })
                if existing and existing["source"] == SOURCE and SCHEMA in (existing.get("source_note") or ""):
                    reports.append({"symbol": symbol, "interval": interval, "rows": existing["count"],
                        "dataset_id": existing["dataset_id"], "source_sha256": source_sha256, "status": "already-published"})
                    continue
                if interval in ("1m", *PERIODS):
                    bars = aggregate_minutes(frame, 1 if interval == "1m" else PERIODS[interval])
                else:
                    if daily is None:
                        daily = aggregate_days(frame)
                    bars = aggregate_weeks(daily, trading_days) if interval == "1wk" else daily
                manifest = publish_frame(
                    publications, symbol, interval, bars, fetched_at,
                    local.index[0].isoformat(), local.index[-1].isoformat(),
                )
                reports.append({
                    "symbol": symbol, "interval": interval, "rows": len(bars),
                    "first": bars.index[0].isoformat(), "last": bars.index[-1].isoformat(),
                    "dataset_id": manifest["dataset_id"], "source_sha256": source_sha256, "status": "published",
                })
                print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
                checkpoint = {
                    "dataset": REPO, "revision": REVISION, "license": "Apache-2.0",
                    "created_at": fetched_at.isoformat(), "symbols": selected, "datasets": reports,
                }
                (metadata_dir / "project-import-report.json").write_text(
                    json.dumps(checkpoint, ensure_ascii=False, indent=2)
                )
        report = {
            "dataset": REPO, "revision": REVISION, "license": "Apache-2.0",
            "created_at": fetched_at.isoformat(), "symbols": selected, "datasets": reports,
        }
        (metadata_dir / "project-import-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({"report": str(metadata_dir / "project-import-report.json"), "datasets": len(reports)}, ensure_ascii=False))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
