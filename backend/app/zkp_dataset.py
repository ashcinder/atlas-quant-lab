"""Select a deterministic interval of fully closed bars for proving."""
from datetime import UTC, datetime, timedelta
from app.zkp import ZkProofError

SECONDS = {'15m': 900, '1h': 3600, '4h': 14400, '1d': 86400, '1wk': 604800}

def validate_period(start, end):
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise ZkProofError('证明区间必须包含时区，例如 UTC 的 Z 后缀')
    if start is not None and end is not None and start >= end:
        raise ZkProofError('证明开始时间必须早于结束时间')

def closed_frame(frame, interval, start=None, end=None, now=None):
    validate_period(start, end)
    boundary = min(end, now or datetime.now(UTC)) if end else now or datetime.now(UTC)
    selected = frame.loc[(frame.index + timedelta(seconds=SECONDS[interval])) <= boundary]
    if start is not None:
        selected = selected.loc[selected.index >= start]
    if not 3 <= len(selected) <= 20000:
        raise ZkProofError('所选证明区间需要 3–20000 根已收盘 K 线；结束时间为排他边界')
    return selected
