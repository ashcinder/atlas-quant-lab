"""Point-in-time action inputs from the same bundle as RQAlpha."""
from datetime import datetime, time
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def local_stamp(day):
    date = datetime.strptime(str(day), "%Y%m%d").date()
    return int(datetime.combine(date, time(0), tzinfo=SHANGHAI).timestamp())


def load_daily_actions(payload):
    import h5py

    request = payload["request"]
    symbol = request["symbol"].replace(".SS", ".XSHG").replace(".SZ", ".XSHE")
    start = datetime.fromtimestamp(request["from"], SHANGHAI).date()
    end = datetime.fromtimestamp(request["to"], SHANGHAI).date()
    first, last = (int(date.strftime("%Y%m%d")) for date in (start, end))
    root = Path(payload["bundle_path"])
    with h5py.File(root / "stocks.h5", "r") as quotes:
        rows = quotes.get(symbol)
        if rows is None or not len(rows) or not int(rows[0]["datetime"]) // 1000000 <= first <= last <= int(rows[-1]["datetime"]) // 1000000:
            raise ValueError("RQAlpha bundle 未覆盖本次日线的分红送转数据")

    with h5py.File(root / "ex_cum_factor.h5", "r") as source:
        records = source.get(symbol)
        factors = []
        baseline = 1.0
        for row in (() if records is None else records[:]):
            day = int(row["start_date"]) // 1000000
            factor = float(row["ex_cum_factor"])
            if day <= first:
                baseline = factor
            elif day <= last:
                factors.append({"time": local_stamp(day), "factor": factor})

    with h5py.File(root / "dividends.h5", "r") as source:
        records = source.get(symbol)
        dividends = []
        for row in (() if records is None else records[:]):
            day = int(row["ex_dividend_date"])
            if first < day <= last:
                payable = int(row["payable_date"])
                dividends.append({"time": local_stamp(day), "payable": local_stamp(max(day, payable)),
                                  "per_share": float(row["dividend_cash_before_tax"] / row["round_lot"])})

    with h5py.File(root / "split_factor.h5", "r") as source:
        records = source.get(symbol)
        splits = [{"time": local_stamp(day), "ratio": float(row["split_factor"])}
                  for row in (() if records is None else records[:])
                  if first < (day := int(row["ex_date"]) // 1000000) <= last]

    factors.sort(key=lambda row: row["time"])
    dividends.sort(key=lambda row: row["time"])
    splits.sort(key=lambda row: row["time"])
    if any(not isfinite(x) or x <= 0 for x in [baseline, *(r["factor"] for r in factors), *(r["ratio"] for r in splits)]) \
            or any(not isfinite(r["per_share"]) or r["per_share"] < 0 for r in dividends):
        raise ValueError("RQAlpha bundle 存在无效的分红送转数据")
    result = {"base_factor": baseline, "factors": factors, "dividends": dividends, "splits": splits}
    return {**result, "version": sha256(json.dumps([symbol, first, last, result], sort_keys=True).encode()).hexdigest()}


def research_bars(bars, actions):
    if not actions:
        return bars
    factor = actions["base_factor"]
    changes = iter(actions["factors"])
    change = next(changes, None)
    output = []
    for bar in bars:
        while change and change["time"] <= bar["time"]:
            factor = change["factor"]
            change = next(changes, None)
        scale = factor / actions["base_factor"]
        output.append({**bar, **{field: bar[field] * scale for field in ("open", "high", "low", "close")}})
    return output


class DailyActions:
    def __init__(self, actions):
        dividends = [(row["time"], 0, row) for row in actions["dividends"]]
        splits = [(row["time"], 1, row) for row in actions["splits"]]
        self.events = sorted(dividends + splits, key=lambda event: event[:2])
        self.index = 0
        self.receivables = []

    def apply(self, stamp, quantity, average):
        ratio = 1.0
        while self.index < len(self.events) and self.events[self.index][0] <= stamp:
            _, kind, event = self.events[self.index]
            self.index += 1
            if kind == 0:
                dividend = event["per_share"]
                self.receivables.append((event["payable"], quantity * dividend))
                average = max(0, average - dividend)
            else:
                split = event["ratio"]
                quantity *= split
                average /= split
                ratio *= split
        payable = sum(amount for due, amount in self.receivables if due <= stamp)
        self.receivables = [(due, amount) for due, amount in self.receivables if due > stamp]
        outstanding = sum(amount for _, amount in self.receivables)
        return quantity, average, ratio, payable, outstanding
