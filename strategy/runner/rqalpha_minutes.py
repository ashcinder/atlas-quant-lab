import csv
import datetime
import gzip
import hashlib
import io
import json
import math
import re
from collections import OrderedDict
from pathlib import Path, PurePosixPath

import numpy as np

SCHEMA = "atlas.rqalpha.minutes/v1"
ENGINE_VERSION = "6.5.0"
MODULE_NAME = "atlas_rqalpha_minutes"
ROOT = Path("/minutes")
INDEX_BYTES = 4 * 1024 * 1024
MONTH_BYTES = 2 * 1024 * 1024
MONTH_ROWS = 8000
HISTORY_ROWS = 100_000
INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
INDUSTRIES = {"semiconductor", "defense", "space", "robotics"}
NO_TRADE = {"confirmed_suspension", "zero_daily_no_trade"}
SYMBOL = re.compile(r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)")
SHA256 = re.compile(r"[a-f0-9]{64}")
MONTH_PATH = re.compile(
    r"bars/((?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ))/([0-9]{4}-[0-9]{2})\.csv\.gz"
)
COLUMNS = ("datetime", "open", "high", "low", "close", "volume", "total_turnover")
BAR_DTYPE = np.dtype(
    [
        (name, "u8" if name == "datetime" else "f8")
        for name in (*COLUMNS, "limit_up", "limit_down")
    ]
)
_ACTIVE = None


class MinuteError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def date(value):
    if not isinstance(value, str):
        raise MinuteError("分钟清单日期无效")
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise MinuteError("分钟清单日期无效") from exc
    if parsed.isoformat() != value:
        raise MinuteError("分钟清单日期必须为 ISO 日期")
    return parsed


def encoded(value):
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, datetime.time())
    return int(value.strftime("%Y%m%d%H%M%S"))


def native_symbol(value):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise MinuteError("分钟股票代码不受支持")
    return value[:-3] + (".XSHG" if value.endswith(".SS") else ".XSHE")


def platform_symbol(value):
    result = value[:-5] + (".SS" if value.endswith(".XSHG") else ".SZ")
    if native_symbol(result) != value:
        raise MinuteError("分钟股票代码不受支持")
    return result


def continuous_codes(day):
    result = []
    for hour, minute in ((9, 30), (13, 0)):
        start = datetime.datetime.combine(day, datetime.time(hour, minute))
        result.extend(
            encoded(start + datetime.timedelta(minutes=i)) for i in range(1, 121)
        )
    return np.asarray(result, dtype="u8")


def _reject_constant(_):
    raise MinuteError("分钟清单包含非有限值")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise MinuteError("分钟清单包含重复字段")
        value[key] = item
    return value


def _dates(values):
    if not isinstance(values, list) or len(values) > 20_000:
        raise MinuteError("分钟交易日列表无效")
    parsed = [date(value) for value in values]
    if parsed != sorted(set(parsed)):
        raise MinuteError("分钟交易日无序或重复")
    return parsed


def validate_membership(records):
    if not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise MinuteError("分钟回测缺少时点行业名单")
    result, seen = [], set()
    for row in records:
        if not isinstance(row, dict):
            raise MinuteError("时点行业名单无效")
        times = tuple(date(row.get(key)) for key in ("as_of", "published", "effective"))
        symbols = row.get("symbols")
        if (
            not isinstance(symbols, list)
            or not 1 <= len(symbols) <= 150
            or any(
                not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol)
                for symbol in symbols
            )
            or len(symbols) != len(set(symbols))
            or times in seen
        ):
            raise MinuteError("时点行业名单日期或股票无效")
        seen.add(times)
        result.append((times, frozenset(native_symbol(symbol) for symbol in symbols)))
    return tuple(sorted(result, key=lambda row: (row[0][2], row[0][1], row[0][0])))


class EligibilityValidator:
    def __init__(self, environment, membership, phase, algo_types=()):
        self.env, self.membership, self.phase, self.algo_types = (
            environment,
            membership,
            phase,
            algo_types,
        )

    def validate_submission(self, order, account=None):
        if getattr(self.phase(), "name", None) == "OPEN_AUCTION":
            return "冻结分钟源没有可核验的集合竞价数据，竞价下单不可用"
        if self.algo_types and isinstance(
            getattr(order, "style", None), self.algo_types
        ):
            return "冻结分钟源不支持算法订单"
        if order.side.name != "BUY":
            return None
        day = self.env.trading_dt.date()
        eligible = [
            row
            for row in self.membership
            if row[0][0] <= day and row[0][1] < day and row[0][2] <= day
        ]
        if not eligible or order.order_book_id not in eligible[-1][1]:
            return "证券不在当前已公开生效的行业名单中，不可新增买入"
        return None

    def validate_cancellation(self, order, account=None):
        return None


class MinuteStore:
    def __init__(self, digest, daily_digest, settings, window, root=ROOT):
        self.root = Path(root)
        self.cache = OrderedDict()
        self.interval = settings.get("interval")
        if self.interval not in INTERVALS or settings.get("industry") not in INDUSTRIES:
            raise MinuteError("分钟回测仅支持四行业及 1/5/15/30/60 分钟")
        if (
            not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
            or not isinstance(daily_digest, str)
            or not SHA256.fullmatch(daily_digest)
        ):
            raise MinuteError("分钟或配套日线冻结摘要缺失")
        path = self.root / "index.json"
        if (
            self.root.is_symlink()
            or not self.root.is_dir()
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > INDEX_BYTES
        ):
            raise MinuteError("分钟清单缺失或超过 4 MiB")
        try:
            with path.open("rb") as stream:
                raw = stream.read(INDEX_BYTES + 1)
            if len(raw) > INDEX_BYTES:
                raise MinuteError("分钟清单超过 4 MiB")
            index = json.loads(
                raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object
            )
            if not isinstance(index, dict):
                raise MinuteError("分钟清单不是对象")
            content = {key: value for key, value in index.items() if key != "digest"}
            if (
                index.get("digest") != digest
                or hashlib.sha256(canonical(content)).hexdigest() != digest
            ):
                raise MinuteError("分钟清单摘要与冻结请求不符")
        except (UnicodeError, json.JSONDecodeError, RecursionError, OSError) as exc:
            raise MinuteError("分钟清单无法读取") from exc
        source = index.get("source")
        expected_source = {
            "repo_id": "neigezhu/china-a-share-1min-ohlcv",
            "revision": "ba589a11534825044fe5a6b84838f50ba8d8d188",
            "timezone": "Asia/Singapore",
            "price_adjustment": "none",
            "volume_unit": "shares",
            "turnover_unit": "CNY",
            "last_complete_day": "2026-08-06",
            "license_declared": "apache-2.0",
        }
        if (
            index.get("schema") != SCHEMA
            or index.get("adapter_version") != SCHEMA
            or index.get("engine_version") != ENGINE_VERSION
            or index.get("usage") != "academic-noncommercial-local-research"
            or index.get("daily_digest") != daily_digest
            or not isinstance(index.get("membership_sha256"), str)
            or not SHA256.fullmatch(index["membership_sha256"])
            or index.get("bar_convention") != "end-label-session-local/v1"
            or index.get("extra_session_policy")
            != "retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders"
            or not isinstance(source, dict)
            or any(source.get(key) != value for key, value in expected_source.items())
        ):
            raise MinuteError("分钟数据版本、来源、配套日线或时间口径不符")
        self.index, self.digest = index, digest
        self.start, self.end = date(window.get("start")), date(window.get("end"))
        lower, upper = date(index.get("start")), date(index.get("end"))
        self.sessions = _dates(index.get("sessions"))
        if (
            not self.sessions
            or self.sessions[0] != lower
            or self.sessions[-1] != upper
            or lower > self.start
            or self.start >= self.end
            or self.end > upper
            or upper > date(source["last_complete_day"])
        ):
            raise MinuteError("分钟请求超出实际完整覆盖区间")
        self.request_sessions = tuple(
            day for day in self.sessions if self.start <= day <= self.end
        )
        if (
            len(self.request_sessions) < 2
            or self.request_sessions[0] != self.start
            or self.request_sessions[-1] != self.end
        ):
            raise MinuteError("分钟回测起止必须是至少两个已冻结交易日")
        instruments, files = index.get("instruments"), index.get("files")
        symbols = settings.get("symbols")
        if (
            not isinstance(instruments, dict)
            or not isinstance(files, list)
            or not 1 <= len(files) <= 10_000
            or not isinstance(symbols, list)
            or not 1 <= len(symbols) <= 150
            or any(
                not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol)
                for symbol in symbols
            )
            or len(set(symbols)) != len(symbols)
        ):
            raise MinuteError("分钟证券或文件清单无效")
        self.symbols, self.instruments, self.files = frozenset(symbols), {}, {}
        total = 0
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise MinuteError("分钟分块文件无效")
            match = MONTH_PATH.fullmatch(row["path"])
            relative = PurePosixPath(row["path"])
            if (
                match is None
                or relative.is_absolute()
                or ".." in relative.parts
                or match[1] != row.get("symbol")
                or match[2] != row.get("month")
                or row["path"].casefold() in self.files
                or type(row.get("bytes")) is not int
                or not 0 < row["bytes"] <= MONTH_BYTES
                or type(row.get("rows")) is not int
                or not 0 < row["rows"] <= MONTH_ROWS
                or not isinstance(row.get("sha256"), str)
                or not SHA256.fullmatch(row["sha256"])
            ):
                raise MinuteError("分钟分块路径、大小、行数或摘要无效")
            date(row["month"] + "-01")
            self.files[row["path"].casefold()] = row
            total += row["bytes"]
        if total > 4 * 1024**3:
            raise MinuteError("分钟数据超过隔离预算")
        actual = set()
        for entry in self.root.rglob("*"):
            if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
                raise MinuteError("分钟目录包含链接或特殊文件")
            if entry.is_file():
                name = entry.relative_to(self.root).as_posix().casefold()
                if name in actual:
                    raise MinuteError("分钟目录包含大小写冲突")
                actual.add(name)
        if actual != {"index.json", *self.files}:
            raise MinuteError("分钟目录文件集合与冻结清单不符")
        for symbol in sorted(self.symbols):
            info = instruments.get(symbol)
            if not isinstance(info, dict) or info.get("native_symbol") != native_symbol(
                symbol
            ):
                raise MinuteError("所选证券缺少分钟冻结信息")
            complete = _dates(info.get("complete_sessions"))
            no_trade, gaps, months = (
                info.get("no_trade_sessions"),
                info.get("gaps"),
                info.get("months"),
            )
            if (
                not isinstance(no_trade, dict)
                or not isinstance(gaps, dict)
                or not isinstance(months, dict)
                or any(
                    classification not in NO_TRADE
                    for classification in no_trade.values()
                )
            ):
                raise MinuteError("分钟停牌、缺口或月份索引无效")
            no_trade_days, gap_days = (
                {date(day) for day in no_trade},
                {date(day) for day in gaps},
            )
            if (
                set(complete) & (no_trade_days | gap_days)
                or no_trade_days & gap_days
                or not (set(complete) | no_trade_days | gap_days) <= set(self.sessions)
                or not complete
                or date(info.get("start")) != complete[0]
                or date(info.get("end")) != complete[-1]
                or not set(self.request_sessions) <= set(complete) | no_trade_days
            ):
                raise MinuteError("所选股票在请求区间存在未核验的分钟缺口")
            for month, relative in months.items():
                if (
                    not isinstance(month, str)
                    or not isinstance(relative, str)
                    or relative != f"bars/{symbol}/{month}.csv.gz"
                    or relative.casefold() not in self.files
                ):
                    raise MinuteError("分钟月份索引与文件清单不符")
                self._verified_bytes(self.files[relative.casefold()])
            if any(day.strftime("%Y-%m") not in months for day in complete):
                raise MinuteError("完整交易日没有对应分钟分块")
            selected_files = {
                row["month"] for row in self.files.values() if row["symbol"] == symbol
            }
            if selected_files != set(months):
                raise MinuteError("所选证券分块未被完整索引")
            self.instruments[symbol] = {**info, "complete": frozenset(complete)}

    def _verified_bytes(self, row):
        path = self.root / row["path"]
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(self.root.resolve())
            or path.stat().st_size != row["bytes"]
        ):
            raise MinuteError("分钟分块大小与冻结清单不符")
        with path.open("rb") as stream:
            raw = stream.read(MONTH_BYTES + 1)
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise MinuteError("分钟分块摘要与冻结清单不符")
        return raw

    def month(self, symbol, month):
        key = symbol, month
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        info = self.instruments.get(symbol)
        if info is None:
            raise MinuteError("证券不在本次冻结分钟池中")
        relative = info["months"].get(month)
        if relative is None:
            return {"raw": np.empty(0, dtype=BAR_DTYPE), "bars": {}}
        spec = self.files[relative.casefold()]
        try:
            with gzip.GzipFile(
                fileobj=io.BytesIO(self._verified_bytes(spec))
            ) as stream:
                raw = stream.read(MONTH_BYTES + 1)
            if len(raw) > MONTH_BYTES:
                raise MinuteError("分钟分块解压超过 2 MiB")
            reader = csv.reader(
                io.StringIO(raw.decode("utf-8"), newline=""), strict=True
            )
            if tuple(next(reader, ())) != COLUMNS:
                raise MinuteError("分钟分块字段无效")
            rows = []
            previous = 0
            for row in reader:
                if (
                    len(rows) >= MONTH_ROWS
                    or len(row) != len(COLUMNS)
                    or any(len(value) > 64 for value in row)
                ):
                    raise MinuteError("分钟分块行数或字段超过限制")
                if not re.fullmatch(r"[0-9]{14}", row[0]):
                    raise MinuteError("分钟时间标签无效")
                moment = datetime.datetime.strptime(row[0], "%Y%m%d%H%M%S").replace(
                    tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
                )
                code = int(row[0])
                if (
                    moment.strftime("%Y-%m") != month
                    or code <= previous
                    or moment.second
                    or not (
                        datetime.time(9, 30) <= moment.time() <= datetime.time(11, 30)
                        or datetime.time(13) <= moment.time() <= datetime.time(15)
                    )
                ):
                    raise MinuteError("分钟时间标签重复、无序或超出交易时段")
                values = tuple(float(value) for value in row[1:])
                opening, high, low, close, volume, turnover = values
                if (
                    any(not math.isfinite(value) for value in values)
                    or min(opening, high, low, close) <= 0
                    or high < max(opening, close, low)
                    or low > min(opening, close, high)
                    or volume < 0
                    or not volume.is_integer()
                    or volume > 2**53
                    or turnover < 0
                    or turnover > 1e16
                ):
                    raise MinuteError("分钟价量无效")
                rows.append((code, *values, np.nan, np.nan))
                previous = code
            if len(rows) != spec["rows"]:
                raise MinuteError("分钟分块实际行数与冻结清单不符")
            bars = np.asarray(rows, dtype=BAR_DTYPE)
            for day in info["no_trade_sessions"]:
                if day[:7] != month:
                    continue
                code = int(day.replace("-", ""))
                if np.any(bars["volume"][bars["datetime"] // 1_000_000 == code] > 0):
                    raise MinuteError("确认无交易日的分钟分块含有成交量")
            times = bars["datetime"] % 1_000_000
            continuous = bars[(times != 93000) & (times != 130000)]
            for day in sorted(info["complete"]):
                if day.strftime("%Y-%m") != month:
                    continue
                expected = continuous_codes(day)
                day_rows = continuous[
                    (continuous["datetime"] // 1_000_000) == int(day.strftime("%Y%m%d"))
                ]
                if not np.array_equal(day_rows["datetime"], expected):
                    raise MinuteError("完整交易日缺少真实连续 240 根分钟线")
            valid_days = np.asarray(
                [int(day.strftime("%Y%m%d")) for day in info["complete"]], dtype="u8"
            )
            continuous = continuous[
                np.isin(continuous["datetime"] // 1_000_000, valid_days)
            ]
        except (
            OSError,
            EOFError,
            UnicodeError,
            csv.Error,
            ValueError,
            OverflowError,
        ) as exc:
            if isinstance(exc, MinuteError):
                raise
            raise MinuteError("分钟分块不是有效的冻结 CSV gzip") from exc
        item = {"raw": bars, "bars": {1: continuous}}
        self.cache[key] = item
        if len(self.cache) > 64:
            self.cache.popitem(last=False)
        return item

    def bars(self, symbol, month, interval=1):
        item = self.month(symbol, month)
        if interval not in INTERVALS.values():
            raise MinuteError("分钟聚合周期不受支持")
        if interval not in item["bars"]:
            one = item["bars"].get(1, np.empty(0, dtype=BAR_DTYPE))
            groups = one.reshape((-1, interval))
            result = np.empty(len(groups), dtype=BAR_DTYPE)
            result["datetime"] = groups["datetime"][:, -1]
            result["open"], result["close"] = (
                groups["open"][:, 0],
                groups["close"][:, -1],
            )
            result["high"], result["low"] = (
                groups["high"].max(axis=1),
                groups["low"].min(axis=1),
            )
            for field in ("volume", "total_turnover"):
                result[field] = groups[field].sum(axis=1)
            result["limit_up"], result["limit_down"] = np.nan, np.nan
            item["bars"][interval] = result
        return item["bars"].get(interval, np.empty(0, dtype=BAR_DTYPE))

    def get_bar(self, symbol, moment, interval=1):
        if moment.date() not in self.instruments[symbol]["complete"]:
            return None
        bars = self.bars(symbol, moment.strftime("%Y-%m"), interval)
        code = encoded(moment)
        position = bars["datetime"].searchsorted(code)
        return (
            bars[position]
            if position < len(bars) and bars["datetime"][position] == code
            else None
        )

    def visible(self, symbol, moment):
        if moment.date() not in self.instruments[symbol]["complete"]:
            return np.empty(0, dtype=BAR_DTYPE)
        bars = self.month(symbol, moment.strftime("%Y-%m"))["raw"]
        left = bars["datetime"].searchsorted(encoded(moment.date()), side="left")
        right = bars["datetime"].searchsorted(encoded(moment), side="right")
        return bars[left:right]

    def history(self, symbol, moment, count, interval=1):
        if type(count) is not int or not 1 <= count <= HISTORY_ROWS:
            raise MinuteError("分钟历史查询须为 1–100000 根")
        values, remaining = [], count
        for month in sorted(self.instruments[symbol]["months"], reverse=True):
            if month > moment.strftime("%Y-%m"):
                continue
            bars = self.bars(symbol, month, interval)
            end = bars["datetime"].searchsorted(encoded(moment), side="right")
            part = bars[max(0, end - remaining) : end]
            if len(part):
                values.append(part)
                remaining -= len(part)
            if not remaining:
                break
        result = (
            np.concatenate(values[::-1]) if values else np.empty(0, dtype=BAR_DTYPE)
        )
        first_day = int(result["datetime"][0]) // 1_000_000 if len(result) else None
        query_day = int(moment.strftime("%Y%m%d"))
        if any(
            int(day.replace("-", "")) <= query_day
            and (remaining or first_day <= int(day.replace("-", "")))
            for day in self.instruments[symbol]["gaps"]
        ):
            raise MinuteError("分钟历史查询跨越已知数据缺口，不可跳过缺口拼接历史")
        return result


def cumulative(rows, *, dtype=BAR_DTYPE, daily=False, limits=(np.nan, np.nan)):
    if not len(rows):
        return None
    result = np.zeros(1, dtype=dtype)
    for field in result.dtype.names:
        if result.dtype[field].kind == "f":
            result[field] = np.nan
    for field in ("open", "high", "low", "close", "volume", "total_turnover"):
        if field not in result.dtype.names:
            continue
        result[field] = (
            rows[field][0]
            if field == "open"
            else rows[field][-1]
            if field == "close"
            else rows[field].max()
            if field == "high"
            else rows[field].min()
            if field == "low"
            else rows[field].sum()
        )
    result["datetime"] = (
        rows["datetime"][-1] // 1_000_000 * 1_000_000 if daily else rows["datetime"][-1]
    )
    for field, value in zip(("limit_up", "limit_down"), limits, strict=True):
        if field in result.dtype.names:
            result[field] = value
    return result[0]


def configure(store, membership):
    global _ACTIVE
    _ACTIVE = store, validate_membership(membership)
    return {"enabled": True, "priority": 1000, "lib": MODULE_NAME}


def activate(environment):
    if (
        _ACTIVE is None
        or getattr(environment.data_source, "store", None) is not _ACTIVE[0]
    ):
        raise MinuteError("可信分钟扩展未正确安装")
    store = _ACTIVE[0]
    actual = tuple(day.date() for day in environment.config.base.trading_calendar)
    if (
        environment.config.base.start_date != store.start
        or environment.config.base.end_date != store.end
        or actual != store.request_sessions
    ):
        raise MinuteError("原生引擎不得静默缩短冻结分钟区间")
    environment.data_source.enforce_visibility = True


def load_mod():
    from rqalpha.const import EXECUTION_PHASE, INSTRUMENT_TYPE
    from rqalpha.core.events import EVENT, Event
    from rqalpha.core.execution_context import ExecutionContext
    from rqalpha.data.bar_dict_price_board import BarDictPriceBoard
    from rqalpha.data.base_data_source import BaseDataSource
    from rqalpha.data.base_data_source.adjust import adjust_bars
    from rqalpha.interface import AbstractEventSource, AbstractMod
    from rqalpha.mod.rqalpha_mod_sys_simulation.matcher import DefaultBarMatcher
    from rqalpha.model.bar import BarMap
    from rqalpha.model.order import ALGO_ORDER_STYLES
    from rqalpha.model.tick import TickObject

    if _ACTIVE is None:
        raise MinuteError("分钟冻结上下文缺失")
    store, membership = _ACTIVE

    class Source(BaseDataSource):
        def __init__(self, environment):
            self.env, self.store, self.enforce_visibility = environment, store, False
            self.limit_cache = OrderedDict()
            super().__init__(environment.config.base)

        def _clock(self):
            return self.env.calendar_dt

        def _limits(self, instrument, day):
            key = instrument.order_book_id, day
            if key in self.limit_cache:
                self.limit_cache.move_to_end(key)
                return self.limit_cache[key]
            bar = super().get_bar(instrument, day, "1d")
            if bar is None:
                raise MinuteError("分钟数据缺少同日原生规则日线")
            result = tuple(
                float(bar[field]) if field in bar.dtype.names else np.nan
                for field in ("limit_up", "limit_down")
            )
            self.limit_cache[key] = result
            if len(self.limit_cache) > 4096:
                self.limit_cache.popitem(last=False)
            return result

        def _partial(self, instrument):
            symbol = platform_symbol(instrument.order_book_id)
            if symbol not in store.instruments:
                return None
            meta = super().get_bar(instrument, self._clock().date(), "1d")
            if meta is None:
                raise MinuteError("分钟数据缺少同日原生规则日线")
            return cumulative(
                store.visible(symbol, self._clock()),
                dtype=meta.dtype,
                daily=True,
                limits=self._limits(instrument, self._clock().date()),
            )

        def get_bar(self, instrument, dt, frequency):
            moment = dt
            if frequency == "1d":
                day = moment.date() if isinstance(moment, datetime.datetime) else moment
                if not self.enforce_visibility or day < self._clock().date():
                    return super().get_bar(instrument, moment, frequency)
                return (
                    self._partial(instrument) if day == self._clock().date() else None
                )
            if frequency not in INTERVALS:
                raise MinuteError("冻结分钟源不支持此行情周期")
            symbol = platform_symbol(instrument.order_book_id)
            if symbol not in store.instruments:
                raise MinuteError("证券不在本次冻结分钟池中")
            moment = min(moment, self._clock())
            row = store.get_bar(symbol, moment, INTERVALS[frequency])
            if row is None:
                return None
            result = row.copy()
            result["limit_up"], result["limit_down"] = self._limits(
                instrument, moment.date()
            )
            return result

        def history_bars(
            self,
            instrument,
            bar_count,
            frequency,
            fields,
            dt,
            skip_suspended=True,
            include_now=False,
            adjust_type="pre",
            adjust_orig=None,
        ):
            moment = dt
            if adjust_type not in {"pre", "post", "none"}:
                raise MinuteError("历史复权口径无效")
            if frequency in {"1d", "1w"}:
                now = self._clock()
                query_day = (
                    moment.date() if isinstance(moment, datetime.datetime) else moment
                )
                if (
                    not self.enforce_visibility
                    or query_day < now.date()
                    or frequency == "1w"
                    and not include_now
                ):
                    moment = (
                        min(
                            moment,
                            now
                            if isinstance(moment, datetime.datetime)
                            else now.date(),
                        )
                        if self.enforce_visibility
                        else moment
                    )
                    return super().history_bars(
                        instrument,
                        bar_count,
                        frequency,
                        fields,
                        moment,
                        skip_suspended,
                        include_now,
                        adjust_type,
                        adjust_orig,
                    )
                previous = self.env.data_proxy.get_previous_trading_date(now.date())
                count = (
                    None
                    if frequency == "1w" or bar_count is None
                    else max(0, bar_count - 1)
                )
                bars = super().history_bars(
                    instrument,
                    count,
                    "1d",
                    None,
                    previous,
                    skip_suspended,
                    False,
                    "none",
                    adjust_orig,
                )
                partial = self._partial(instrument)
                if partial is not None and (
                    not skip_suspended or partial["volume"] > 0
                ):
                    bars = np.concatenate(
                        (bars, np.asarray([partial], dtype=bars.dtype))
                    )
                elif frequency == "1d":
                    bars = super().history_bars(
                        instrument,
                        bar_count,
                        "1d",
                        None,
                        previous,
                        skip_suspended,
                        False,
                        "none",
                        adjust_orig,
                    )
                if adjust_type != "none":
                    bars = adjust_bars(
                        bars,
                        self.get_ex_cum_factor(instrument),
                        fields,
                        adjust_type,
                        adjust_orig or now,
                    )
                if frequency == "1w":
                    chosen = list(bars.dtype.names) if fields is None else fields
                    bars = self.resample_week_bars(bars, bar_count, chosen)
            else:
                if frequency not in INTERVALS:
                    raise MinuteError("冻结分钟源不支持此历史周期")
                symbol = platform_symbol(instrument.order_book_id)
                if symbol not in store.instruments:
                    raise MinuteError("证券不在本次冻结分钟池中")
                bars = store.history(
                    symbol, min(moment, self._clock()), bar_count, INTERVALS[frequency]
                ).copy()
                for code in np.unique(bars["datetime"] // 1_000_000):
                    code = int(code)
                    day = datetime.date(code // 10_000, code // 100 % 100, code % 100)
                    mask = bars["datetime"] // 1_000_000 == code
                    bars["limit_up"][mask], bars["limit_down"][mask] = self._limits(
                        instrument, day
                    )
                if adjust_type != "none":
                    bars = adjust_bars(
                        bars,
                        self.get_ex_cum_factor(instrument),
                        fields,
                        adjust_type,
                        adjust_orig or self._clock(),
                    )
            if not self._are_fields_valid(fields, bars.dtype.names):
                raise MinuteError("分钟历史字段不受支持")
            return bars if fields is None else bars[fields]

        def current_snapshot(self, instrument, frequency, moment):
            symbol = platform_symbol(instrument.order_book_id)
            if symbol not in store.instruments:
                raise MinuteError("证券不在本次冻结分钟池中")
            moment = min(moment, self._clock())
            row = cumulative(
                store.visible(symbol, moment),
                limits=self._limits(instrument, moment.date()),
            )
            if row is None:
                raise MinuteError("当前时点没有已完成的真实分钟记录")
            value = {field: row[field] for field in row.dtype.names}
            value["last"] = value.pop("close")
            value["prev_close"] = self.env.data_proxy.get_prev_close(
                instrument.order_book_id, moment
            )
            return TickObject(instrument, value)

        def available_data_range(self, frequency):
            return (
                (store.start, store.end)
                if frequency == "1m"
                else super().available_data_range(frequency)
            )

        def get_trading_minutes_for(self, instrument, trading_dt):
            symbol = platform_symbol(instrument.order_book_id)
            day = (
                trading_dt.date()
                if isinstance(trading_dt, datetime.datetime)
                else trading_dt
            )
            return (
                continuous_codes(day)
                if day in store.instruments[symbol]["complete"]
                else np.empty(0, dtype="u8")
            )

        def get_open_auction_bar(self, instrument, moment):
            raise MinuteError("冻结分钟源没有可核验的集合竞价数据")

        def get_open_auction_volume(self, instrument, moment):
            raise MinuteError("冻结分钟源没有可核验的集合竞价成交量")

        def get_algo_bar(self, *args, **kwargs):
            raise MinuteError("冻结分钟源不支持算法订单")

    class Events(AbstractEventSource):
        def events(self, start_date, end_date, frequency):
            if (start_date, end_date, frequency) != (store.start, store.end, "1m"):
                raise MinuteError("原生分钟事件区间与冻结请求不符")
            period = INTERVALS[store.interval]
            for day in store.request_sessions:
                for event_type, time in (
                    (EVENT.BEFORE_TRADING, datetime.time(8, 30)),
                    (EVENT.OPEN_AUCTION, datetime.time(9, 28)),
                ):
                    moment = datetime.datetime.combine(day, time)
                    yield Event(event_type, calendar_dt=moment, trading_dt=moment)
                for hour, minute in ((9, 30), (13, 0)):
                    opening = datetime.datetime.combine(
                        day, datetime.time(hour, minute)
                    )
                    for offset in range(period, 121, period):
                        moment = opening + datetime.timedelta(minutes=offset)
                        yield Event(EVENT.BAR, calendar_dt=moment, trading_dt=moment)
                moment = datetime.datetime.combine(day, datetime.time(15, 30))
                yield Event(EVENT.AFTER_TRADING, calendar_dt=moment, trading_dt=moment)

    class PriceBoard(BarDictPriceBoard):
        def _get_bar(self, symbol):
            if ExecutionContext.phase() == EXECUTION_PHASE.OPEN_AUCTION:
                raise MinuteError("冻结分钟源没有可核验的集合竞价报价")
            return self._env.data_proxy.get_bar(
                symbol, self._env.calendar_dt, store.interval
            )

    class Matcher(DefaultBarMatcher):
        def _current_bar_close_decider(self, symbol, side):
            return self._env.data_proxy.get_bar(
                symbol, self._env.calendar_dt, store.interval
            ).close

        def _get_bar_volume(self, order, open_auction=False):
            if open_auction or isinstance(order.style, ALGO_ORDER_STYLES):
                raise MinuteError("冻结分钟源不支持集合竞价或算法订单")
            return self._env.data_proxy.get_bar(
                order.order_book_id, self._env.calendar_dt, store.interval
            ).volume

    class Mod(AbstractMod):
        def start_up(self, env, mod_config):
            env.set_data_source(Source(env))
            env.set_event_source(Events())
            env.set_price_board(PriceBoard())
            simulation = env.config.mod.sys_simulation
            env.broker.register_matcher(INSTRUMENT_TYPE.CS, Matcher(env, simulation))
            env.add_frontend_validator(
                EligibilityValidator(
                    env, membership, ExecutionContext.phase, ALGO_ORDER_STYLES
                )
            )
            self.bars = None

            def replace_bars(event):
                if self.bars is None:
                    self.bars = BarMap(env.data_proxy, store.interval)
                self.bars.update_dt(event.calendar_dt)
                event.bar_dict = self.bars

            env.event_bus.prepend_listener(EVENT.BAR, replace_bars)

        def tear_down(self, code, exception=None):
            return None

    return Mod()
