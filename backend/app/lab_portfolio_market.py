"""Operator-published A-share data for the portfolio lab.

Candle, calendar and execution rule facts come from the publisher together.
A generic chart OHLCV snapshot does not establish executable A-share coverage.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.compute_objects import canonical_bytes

CHINA = ZoneInfo("Asia/Shanghai")
MAX_EVENTS = 20_000
RULE_VERSION = "atlas.cn.sim/v1"
SYMBOL = re.compile(r"(?:[036][0-9]{5}\.(?:SS|SZ)|[489][0-9]{5}\.BJ)")
FRESH_SECONDS = {"15m": 120, "1d": 600}


class PortfolioMarketError(ValueError):
    pass


def session_windows(day, interval):
    def stamp(hours, minutes):
        return int(datetime.combine(day, time(hours, minutes), CHINA).timestamp())

    if interval == "1d":
        return [(stamp(9, 30), stamp(15, 0))]
    return [(start + offset * 900, start + (offset + 1) * 900)
            for start in (stamp(9, 30), stamp(13, 0)) for offset in range(8)]


def validate_event(event, symbols, opened, closed):
    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)

    if not isinstance(event, dict) or type(event.get("time")) is not int or event["time"] != closed:
        raise PortfolioMarketError("行情事件缺失或未按 A 股收盘时间对齐")
    bars, suspended, eligible = event.get("bars"), event.get("suspended", []), event.get("eligible", symbols)
    if (not isinstance(bars, dict) or not isinstance(suspended, list) or not isinstance(eligible, list)
            or any(not isinstance(s, str) for s in [*suspended, *eligible])
            or set(bars) & set(suspended) or set(bars) | set(suspended) != set(symbols)
            or not set(eligible) <= set(symbols) or len(set(eligible)) != len(eligible)
            or len(set(suspended)) != len(suspended)):
        raise PortfolioMarketError("每个候选标的必须有行情或明确的不可交易记录")
    for bar in bars.values():
        if not isinstance(bar, dict) or type(bar.get("open_time")) is not int or bar["open_time"] != opened:
            raise PortfolioMarketError("行情开盘时间不匹配")
        if type(bar.get("lot_size")) is not int or bar["lot_size"] < 1:
            raise PortfolioMarketError("缺少有效的证券申报数量规则")
        if "lot_step" in bar and (type(bar["lot_step"]) is not int or bar["lot_step"] < 1):
            raise PortfolioMarketError("申报股数递增单位无效")
        if "sell_tax_rate" in bar and (not finite_number(bar["sell_tax_rate"]) or not 0 <= bar["sell_tax_rate"] <= .1):
            raise PortfolioMarketError("卖出税率无效")
        prices = [bar.get(k) for k in ("open", "high", "low", "close")]
        if (not all(finite_number(p) and p > 0 for p in prices)
                or not finite_number(bar.get("volume")) or bar["volume"] < 0):
            raise PortfolioMarketError("行情价格或成交量无效")
        op, high, low, close = prices
        if high < max(op, close) or low > min(op, close):
            raise PortfolioMarketError("OHLC 行情无效")
        if "limit_up" not in bar or "limit_down" not in bar:
            raise PortfolioMarketError("缺少涨跌停规则，无价格限制须显式标明")
        up, down = bar["limit_up"], bar["limit_down"]
        if not (up is None and down is None or
                finite_number(up) and finite_number(down) and 0 < down < up and down <= low <= high <= up):
            raise PortfolioMarketError("涨跌停规则与行情不一致")
        for key in ("split_ratio", "cash_dividend", "research_close", "reference"):
            if key in bar and (not finite_number(bar[key]) or bar[key] < 0 or key != "cash_dividend" and bar[key] == 0):
                raise PortfolioMarketError("公司行动或研究价格无效")
        first_open = session_windows(datetime.fromtimestamp(closed, CHINA).date(), "1d")[0][0]
        if (bar.get("split_ratio", 1) != 1 or bar.get("cash_dividend", 0) != 0) and opened != first_open:
            raise PortfolioMarketError("公司行动须发布在当日首根行情")
    daily = event.get("daily", {})
    if (not isinstance(daily, dict) or not set(daily) <= set(symbols)
            or daily and closed != session_windows(datetime.fromtimestamp(closed, CHINA).date(), "1d")[0][1]):
        raise PortfolioMarketError("日线补充数据只能发布在当日收盘")
    for bar in daily.values():
        if not isinstance(bar, dict):
            raise PortfolioMarketError("日线补充数据无效")
        op, high, low, close, volume = (bar.get(k) for k in ("open", "high", "low", "close", "volume"))
        if not (all(finite_number(p) for p in (op, high, low, close, volume))
                and 0 < low <= min(op, close) <= max(op, close) <= high and volume >= 0):
            raise PortfolioMarketError("日线补充数据无效")
    actions = event.get("corporate_actions", {})
    if not isinstance(actions, dict) or not set(actions) <= set(suspended):
        raise PortfolioMarketError("独立公司行动只用于当前不可交易证券")
    if actions and opened != session_windows(datetime.fromtimestamp(closed, CHINA).date(), "1d")[0][0]:
        raise PortfolioMarketError("公司行动须发布在当日首根行情")
    for action in actions.values():
        if (not isinstance(action, dict) or action.keys() - {"split_ratio", "cash_dividend"}
                or not finite_number(action.get("split_ratio", 1)) or action.get("split_ratio", 1) <= 0
                or not finite_number(action.get("cash_dividend", 0)) or action.get("cash_dividend", 0) < 0):
            raise PortfolioMarketError("公司行动数据无效")
    unresolved = event.get("unresolved_actions", [])
    if (not isinstance(unresolved, list) or any(not isinstance(s, str) or s not in symbols for s in unresolved)
            or len(set(unresolved)) != len(unresolved)
            or unresolved and opened != session_windows(datetime.fromtimestamp(closed, CHINA).date(), "1d")[0][0]):
        raise PortfolioMarketError("未核实的公司行动记录无效")
    return {"time": closed, "bars": bars, "suspended": suspended, "eligible": eligible, "daily": daily,
            "corporate_actions": actions, "unresolved_actions": unresolved}


class PortfolioMarket:
    def __init__(self, connect, objects):
        self.connect, self.objects = connect, objects

    def publish(self, manifest, events):
        """Validate and atomically publish an operator-supplied event stream."""
        if not isinstance(manifest, dict) or manifest.get("schema") != "atlas.cn.market/v1":
            raise PortfolioMarketError("行情发布清单版本无效")
        interval, symbols = manifest.get("interval"), manifest.get("symbols")
        if (interval not in FRESH_SECONDS or not isinstance(symbols, list) or not 2 <= len(symbols) <= 150
                or any(not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in symbols)
                or len(set(symbols)) != len(symbols)):
            raise PortfolioMarketError("行情股票池或周期无效")
        profile, universe = manifest.get("profile"), manifest.get("universe")
        source = manifest.get("source")
        action_source = manifest.get("corporate_action_source_sha256")
        if action_source is not None and (not isinstance(action_source, str)
                                          or not re.fullmatch(r"[a-f0-9]{64}", action_source)):
            raise PortfolioMarketError("公司行动来源摘要无效")
        if (profile not in ("historical", "live") or universe not in (None, "semiconductor", "defense", "space", "robotics")
                or not isinstance(source, str) or not source.strip() or len(source) > 100
                or "demo" in source.lower()):
            raise PortfolioMarketError("行情来源、用途或行业无效")
        if not isinstance(manifest.get("sessions"), list) or not 1 <= len(manifest["sessions"]) <= MAX_EVENTS:
            raise PortfolioMarketError("交易日历缺失或超出限制")
        try:
            dates = [date.fromisoformat(item) for item in manifest["sessions"]]
        except (TypeError, ValueError):
            raise PortfolioMarketError("交易日历格式无效") from None
        if sorted(set(dates)) != dates:
            raise PortfolioMarketError("交易日历必须按交易日排序且无重复")
        now = int(datetime.now(UTC).timestamp())
        windows = [window for day in dates for window in session_windows(day, interval) if window[1] <= now]
        if (not windows or len(windows) > MAX_EVENTS
                or profile == "historical" and windows[-1] != session_windows(dates[-1], interval)[-1]):
            raise PortfolioMarketError("行情快照时间无效或超出回测容量")
        through = dates[-1]
        if profile == "live":
            try:
                through = date.fromisoformat(manifest["calendar_through"])
            except (KeyError, TypeError, ValueError):
                raise PortfolioMarketError("持续模拟需要声明交易日历覆盖截止日") from None
            if through < dates[-1]:
                raise PortfolioMarketError("交易日历截止日早于已声明交易日")
        stream, chunks, chunk_ends, part = iter(events), [], [], []
        for opened, closed in windows:
            try:
                event = next(stream)
            except StopIteration:
                raise PortfolioMarketError("行情未覆盖完整交易日历") from None
            item = validate_event(event, symbols, opened, closed)
            if universe is None and set(item["eligible"]) != set(symbols):
                raise PortfolioMarketError("静态股票池行情不能包含动态成员筛选")
            part.append(item)
            if len(part) >= 64:
                chunks.append(self.objects.put("private", part))
                chunk_ends.append(part[-1]["time"])
                part = []
        if next(stream, sentinel := object()) is not sentinel:
            raise PortfolioMarketError("行情含未收盘或日历之外的事件")
        if part:
            chunks.append(self.objects.put("private", part))
            chunk_ends.append(part[-1]["time"])
        entry = {"profile": profile, "universe": universe, "source": source.strip(), "interval": interval,
                 "symbols": sorted(symbols), "rule_version": RULE_VERSION, "start": windows[0][1],
                 "end": windows[-1][1], "count": len(windows), "chunks": chunks,
                 "sessions": manifest["sessions"], "calendar_through": through.isoformat(), "chunk_ends": chunk_ends}
        if action_source is not None:
            entry["corporate_action_source_sha256"] = action_source
        digest = hashlib.sha256(canonical_bytes(entry)).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO lab_multi_market VALUES (?,?,?,?,?,?,?)",
                       (digest, profile, interval, universe or "", entry["start"], entry["end"],
                        json.dumps(entry, allow_nan=False)))
        return digest

    def resolve(self, settings, profile):
        wanted = set(settings.symbols)
        if len(wanted) < 2:
            raise PortfolioMarketError("请为多股策略配置至少两只股票")
        start = int(settings.start.timestamp()) if profile == "historical" and settings.start else None
        end = int(settings.end.timestamp()) if profile == "historical" and settings.end else None
        missing = wanted
        complete_pool = False
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM lab_multi_market WHERE profile=? AND interval=? AND universe=?
                   ORDER BY end DESC, rowid DESC""",
                (profile, settings.interval, settings.universe or ""),
            )
            for row in rows:
                entry = json.loads(row["manifest"])
                absent = wanted - set(entry["symbols"])
                if len(absent) < len(missing):
                    missing = absent
                complete_pool = complete_pool or not absent
                # A date-only UI commonly sets the start at local midnight.
                first_day = datetime.fromtimestamp(entry["start"], CHINA).date()
                last_day = datetime.fromtimestamp(entry["end"], CHINA).date()
                if (not absent
                        and (start is None or datetime.fromtimestamp(start, CHINA).date() >= first_day)
                        and (end is None or datetime.fromtimestamp(end, CHINA).date() <= last_day)):
                    return {"digest": row["digest"], **entry}
        message = "未发布完整覆盖该股票池、周期和区间的行情与交易规则"
        if not complete_pool and missing:
            message += f"。缺失标的：{', '.join(sorted(missing))}"
        raise PortfolioMarketError(message)

    def events(self, entry, settings, *, live=False, after=None):
        symbols = set(settings.symbols)
        start = settings.start.timestamp() if settings.start and not live else -math.inf
        end = settings.end.timestamp() if settings.end and not live else math.inf
        chunks = entry["chunks"]
        first = len(chunks) - 1 if live else 0
        ends = entry.get("chunk_ends")
        if ends and not live:
            from bisect import bisect_left, bisect_right

            first = bisect_left(ends, start)
            if after is not None:
                first = max(first, bisect_right(ends, after))
        for digest in chunks[first:]:
            for event in self.objects.read("private", digest):
                if event["time"] > end:
                    return
                if not start <= event["time"] <= end or after is not None and event["time"] <= after:
                    continue
                yield {"time": event["time"],
                       "bars": {s: bar for s, bar in event["bars"].items() if s in symbols},
                       "suspended": [s for s in event["suspended"] if s in symbols],
                       "eligible": [s for s in event["eligible"] if s in symbols],
                       "daily": {s: bar for s, bar in event.get("daily", {}).items() if s in symbols},
                       "unresolved_actions": [s for s in event.get("unresolved_actions", []) if s in symbols],
                       "corporate_actions": {s: action for s, action in event.get("corporate_actions", {}).items()
                                             if s in symbols}}

    @staticmethod
    def contains_time(entry, timestamp):
        day = datetime.fromtimestamp(timestamp, CHINA).date()
        return (entry["start"] <= timestamp <= entry["end"] and day.isoformat() in entry["sessions"]
                and any(timestamp == close for _, close in session_windows(day, entry["interval"])))

    def latest(self, entry, settings):
        if not self.is_current(entry):
            raise PortfolioMarketError("行情过期或未完整发布，等待下一次更新")
        latest = None
        for event in self.events(entry, settings, live=True):
            latest = event
        if latest is None:
            raise PortfolioMarketError("没有已发布的收盘事件")
        return latest

    @staticmethod
    def is_current(entry):
        now = datetime.now(CHINA)
        if now.date() > date.fromisoformat(entry["calendar_through"]):
            return False
        cutoff = now.timestamp() - FRESH_SECONDS[entry["interval"]]
        for item in reversed(entry["sessions"]):
            day = date.fromisoformat(item)
            if day > now.date():
                continue
            for _, close in reversed(session_windows(day, entry["interval"])):
                if close <= cutoff:
                    return entry["end"] >= close
        return False
