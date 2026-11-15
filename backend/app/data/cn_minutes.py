"""Aggregate complete mainland China stock sessions using bar-open timestamps."""
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("Asia/Shanghai")
FIELDS = ("open", "high", "low", "close", "volume")


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
