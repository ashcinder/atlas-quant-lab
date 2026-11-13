"""Scheduled market publication. HTTP consumers never fetch upstream data."""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import numpy as np

from app.compute_objects import ComputeObjects, canonical_bytes
from app.config import DB_PATH
from app.data.service import DataBundle
from app.models import Asset


def query_key(query: dict) -> str:
    normalized = {key: query.get(key, default) for key, default in (
        ("symbol", "BTC-USD"), ("asset_class", "crypto"), ("interval", "1d"),
        ("adjustment", "auto"), ("data_source", "auto"), ("base_currency", None),
    )}
    normalized["symbol"] = str(normalized["symbol"]).upper()
    # A published superset is sliced by the client. Source, adjustment and period
    # remain distinct; different adjusted snapshots are never spliced together.
    return hashlib.sha256(canonical_bytes(normalized)).hexdigest()


class MarketPublication:
    def __init__(self, path: Path = DB_PATH, objects: ComputeObjects | None = None):
        self.path = path
        self.objects = objects or ComputeObjects()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS market_publications (query_key TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, manifest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS market_versions (dataset_id TEXT PRIMARY KEY, manifest TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def publish(
        self,
        query: dict,
        bundle: DataBundle,
        conversions: dict | None = None,
        chunk_size: int = 1000,
        coverage: dict | None = None,
    ) -> dict:
        if bundle.frame.empty or bundle.frame.index.has_duplicates or not bundle.frame.index.is_monotonic_increasing:
            raise ValueError("行情必须非空、按时间递增且没有重复")
        if not 1 <= chunk_size <= 100_000:
            raise ValueError("行情分块大小超出允许范围")
        columns = ("open", "high", "low", "close", "volume")
        values = bundle.frame.loc[:, columns].to_numpy(dtype=float, copy=False)
        opens, highs, lows, closes, volumes = values.T
        invalid = (
            ~np.isfinite(values).all(axis=1)
            | (values[:, :4] <= 0).any(axis=1)
            | (highs < np.maximum(opens, closes))
            | (lows > np.minimum(opens, closes))
            | (volumes < 0)
        )
        if invalid.any():
            raise ValueError("行情包含无效价格或成交量")
        # Pandas preserves the incoming datetime resolution (for example,
        # Arrow-backed Parquet timestamps can be microseconds). Normalize to
        # nanoseconds before converting to Unix seconds so ``asi8`` is stable.
        seconds = bundle.frame.index.as_unit("ns").asi8 // 1_000_000_000
        bars = [
            {"time": int(stamp), "open": float(open_), "high": float(high_), "low": float(low_), "close": float(close_), "volume": float(volume)}
            for stamp, open_, high_, low_, close_, volume in zip(seconds, opens, highs, lows, closes, volumes, strict=True)
        ]
        chunks = []
        for offset in range(0, len(bars), chunk_size):
            part = bars[offset:offset + chunk_size]
            digest = self.objects.put("public", {"bars": part})
            chunks.append({"sha256": digest, "count": len(part), "start": part[0]["time"], "end": part[-1]["time"]})
        manifest = {"schema": "atlas.market/v1", "asset": bundle.asset.model_dump(mode="json"),
                    "interval": query.get("interval", "1d"), "adjustment": query.get("adjustment", "auto"),
                    "source": bundle.source, "source_note": bundle.source_note,
                    "fetched_at": int((bundle.fetched_at or datetime.now(UTC)).timestamp()),
                    "is_stale": bundle.is_stale, "start": bars[0]["time"], "end": bars[-1]["time"],
                    "count": len(bars), "chunks": chunks, "conversions": conversions or {}}
        # Requested coverage is distinct from candle timestamps: closed markets
        # legitimately have no weekend/holiday bars. This records the publisher's
        # query boundary, not a cryptographic guarantee of provider completeness.
        fetched = manifest["fetched_at"]
        def boundary(value, default):
            if value is None:
                return default
            stamp = pd.Timestamp(value)
            stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
            return int(stamp.timestamp())
        manifest["coverage"] = {"start": min(boundary(query.get("start"), bars[0]["time"]), bars[0]["time"]),
                                "end": min(boundary(query.get("end"), fetched), fetched),
                                "basis": "publisher_query_not_source_attestation"}
        if coverage is not None:
            if coverage["start"] > bars[0]["time"] or coverage["end"] < bars[-1]["time"]:
                raise ValueError("查询覆盖范围不能短于已发布行情")
            manifest["coverage"] = coverage
        identifier = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
        manifest["dataset_id"] = identifier
        encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO market_versions VALUES (?,?)", (identifier, encoded))
            db.execute("INSERT OR REPLACE INTO market_publications VALUES (?,?,?)", (query_key(query), identifier, encoded))
        return self.manifest(identifier)

    def manifest(self, identifier: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM market_versions WHERE dataset_id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        result = json.loads(row[0])
        result["chunks"] = [{**part, "url": self.objects.public_url(part["sha256"])} for part in result["chunks"]]
        return result

    def lookup(self, query: dict) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT dataset_id FROM market_publications WHERE query_key=?", (query_key(query),)).fetchone()
        return self.manifest(row[0]) if row else None

    def bundle(self, identifier: str, start: datetime | None = None, end: datetime | None = None) -> DataBundle:
        manifest = self.manifest(identifier)
        coverage = manifest.get("coverage", {"start": manifest["start"], "end": manifest["end"]})
        if start is not None and int(pd.Timestamp(start).timestamp()) < coverage["start"]:
            raise ValueError("已发布行情未覆盖请求开始日期")
        if end is not None and int(pd.Timestamp(end).timestamp()) > coverage["end"]:
            raise ValueError("已发布行情未覆盖请求结束日期")
        parts = [part for part in manifest["chunks"]
                 if (start is None or part['end'] >= start.timestamp())
                 and (end is None or part['start'] <= end.timestamp())]
        bars = [bar for part in parts for bar in self.objects.read("public", part["sha256"])["bars"]]
        if not bars:
            raise ValueError("区间内没有已发布行情")
        frame = pd.DataFrame(bars)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.set_index("time")
        if start is not None:
            frame = frame.loc[frame.index >= start]
        if end is not None:
            frame = frame.loc[frame.index <= end]
        if len(frame) < 3:
            raise ValueError("区间内有效行情少于3根")
        return DataBundle(asset=Asset.model_validate(manifest["asset"]), frame=frame,
                          source=manifest["source"], source_note=manifest["source_note"],
                          fetched_at=datetime.fromtimestamp(manifest["fetched_at"], UTC), cache_hit=True,
                          is_stale=manifest["is_stale"])
