import ast
import contextlib
import datetime as dt
import hashlib
import json
import math
import numbers
import os
import re
import sys
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from uuid import UUID

PROTOCOL = "atlas.rqalpha/v1"
ENGINE_VERSION = "6.5.0"
INPUT_BYTES = 128 * 1024
OUTPUT_BYTES = 16 * 1024 * 1024
INSPECTION_BYTES = 4 * 1024 * 1024
MAX_SESSIONS = 20_000
MAX_RECORDS = 250_000
STREAM_BYTES = 64 * 1024 * 1024
REPORT_SCHEMA = "atlas.rqalpha.raw-report/v1"
REPORT_TABLES = ("positions", "accounts", "benchmark")
MONETARY_FIELDS = ("frozen_cash", "dividend_receivable", "cash_liabilities",
                   "cash_liabilities_interest", "pending_cash_flow")
LOG_BYTES = 1024 * 1024
MAX_LOGS = 2000
LOG_CHARS = 4096
BENCHMARKS = {
    "000300.SS": ("000300.XSHG", "沪深300"),
    "000905.SS": ("000905.XSHG", "中证500"),
    "000001.SS": ("000001.XSHG", "上证指数"),
}
SOURCE_BYTES = 60_000
CHINA = dt.timezone(dt.timedelta(hours=8))
BUNDLE = Path("/bundle")
NATIVE_SYMBOL = re.compile(r"(?:6[0-9]{5}\.XSHG|[03][0-9]{5}\.XSHE)")
PLATFORM_SYMBOL = re.compile(r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)")


class WorkerError(ValueError):
    pass


def finite(value):
    if isinstance(value, bool):
        raise WorkerError("结果包含非数值或非有限数值")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise WorkerError("结果包含非数值或非有限数值") from exc
    if not math.isfinite(result):
        raise WorkerError("结果包含非数值或非有限数值")
    return result


def optional_number(value):
    if value is None:
        return None
    try:
        return finite(value)
    except WorkerError:
        return None


def day(value):
    if isinstance(value, (dt.datetime, dt.date)):
        return value.date() if isinstance(value, dt.datetime) else value
    text = value.decode("ascii") if isinstance(value, bytes) else str(value)
    if re.fullmatch(r"[0-9]{8}(?:[0-9]{6})?", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError as exc:
        raise WorkerError("行情或结果日期无效") from exc


def timestamp(value, *, close=False):
    if close:
        parsed = dt.datetime.combine(day(value), dt.time(15), CHINA)
    elif isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise WorkerError("成交或事件时间无效") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA)
    return int(parsed.timestamp())


def native_symbol(symbol):
    if not isinstance(symbol, str) or not PLATFORM_SYMBOL.fullmatch(symbol):
        raise WorkerError("首期仅支持沪深 A 股股票代码")
    return symbol[:-3] + (".XSHG" if symbol.endswith(".SS") else ".XSHE")


def platform_symbol(symbol):
    if not isinstance(symbol, str) or not NATIVE_SYMBOL.fullmatch(symbol):
        raise WorkerError("结果包含不支持的证券代码")
    return symbol[:-5] + (".SS" if symbol.endswith(".XSHG") else ".SZ")


def rejected_symbol(symbol):
    if isinstance(symbol, str) and re.fullmatch(r"[0-9]{6}\.(?:XSHG|XSHE)", symbol):
        return symbol[:-5] + (".SS" if symbol.endswith(".XSHG") else ".SZ")
    return str(symbol)[:80]


def check_source(source):
    if not isinstance(source, str):
        raise WorkerError("请输入 Python 文本源码")
    try:
        size = len(source.encode("utf-8"))
    except UnicodeError as exc:
        raise WorkerError("源码必须为有效 UTF-8 文本") from exc
    if not source.strip() or size > SOURCE_BYTES or "\0" in source:
        raise WorkerError("Python 源码必须为不超过 60,000 字节的非空文本")
    try:
        tree = ast.parse(source, filename="strategy.py")
    except (SyntaxError, ValueError, RecursionError) as exc:
        line = getattr(exc, "lineno", None)
        raise WorkerError(f"Python 语法无效{f'（第 {line} 行）' if line else ''}") from exc
    if any(isinstance(node, ast.Name) and node.id == "__config__"
           and isinstance(node.ctx, (ast.Store, ast.Del)) for node in ast.walk(tree)):
        raise WorkerError("请将 __config__ 配置移至平台回测设置")
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not {"init", "handle_bar"} <= functions:
        raise WorkerError("RQAlpha 策略需要 init(context) 与 handle_bar(context, bar_dict)")
    return compile(tree, "strategy.py", "exec")


def parse_request(raw):
    if not isinstance(raw, bytes) or len(raw) > INPUT_BYTES:
        raise WorkerError("执行请求超过 128 KiB")
    try:
        request = json.loads(raw, parse_constant=lambda value: _invalid_constant(value))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WorkerError("执行请求不是有效 JSON") from exc
    if not isinstance(request, dict) or request.get("protocol") != PROTOCOL:
        raise WorkerError("执行协议不匹配")
    identifier = request.get("request_id")
    try:
        if not isinstance(identifier, str) or len(identifier) not in (32, 36):
            raise ValueError
        UUID(identifier)
    except ValueError as exc:
        raise WorkerError("执行请求标识无效") from exc
    if request.get("op") not in ("inspect", "run"):
        raise WorkerError("执行操作不受支持")
    if ("stream" in request and type(request["stream"]) is not bool
            or request.get("op") == "inspect" and request.get("stream") is True):
        raise WorkerError("执行流式设置无效")
    return request


def _invalid_constant(_):
    raise ValueError("Non-finite JSON constant")


def encoded_response(value, limit=OUTPUT_BYTES):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise WorkerError("结果无法表示为有效 JSON") from exc
    if len(encoded) + 1 > limit:
        raise WorkerError("结果超过输出体积限制，请缩短回测区间")
    return encoded + b"\n"


def sanitize_log(message):
    text = str(message)[:LOG_CHARS]
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?<![\w:/])/(?:[^\s\"'<>:;,()\[\]]+/?)+", "[路径已隐藏]", text)
    text = re.sub(r"[A-Za-z]:[\\/][^\s\"'<>]+", "[路径已隐藏]", text)
    return "".join(char for char in text if char in "\n\t" or ord(char) >= 32
                   ).encode("utf-8", "replace").decode()[:LOG_CHARS]


class ReportCapture:
    def __init__(self, emit=None):
        self.logs, self.bytes, self.truncated = [], 0, False
        self.emit, self.clock = emit, lambda: None

    def append(self, message, *, level="INFO", source="strategy", line=None):
        if len(self.logs) >= MAX_LOGS or self.bytes >= LOG_BYTES:
            self.truncated = True
            return
        original = str(message)
        text = sanitize_log(original)
        if len(original) > LOG_CHARS:
            self.truncated = True
        try:
            now = self.clock()
            when = timestamp(now) if now is not None else None
        except (AttributeError, TypeError, ValueError):
            when = None
        row = {"sequence": len(self.logs), "time": when, "level": level,
               "source": source, "message": text}
        if type(line) is int and 0 < line <= SOURCE_BYTES:
            row["line"] = line
        size = len(encoded_response(row))
        if self.bytes + size > LOG_BYTES:
            self.truncated = True
            return
        self.logs.append(row)
        self.bytes += size
        if self.emit is not None:
            self.emit(row)

    def user_print(self, *args, sep=" ", end="\n", file=None, flush=False):
        if not isinstance(sep, str) or not isinstance(end, str):
            raise TypeError("sep and end must be strings")
        if len(self.logs) >= MAX_LOGS or self.bytes >= LOG_BYTES:
            self.truncated = True
            return
        pieces, remaining = [], LOG_CHARS + 1
        for index, arg in enumerate(args):
            if index:
                pieces.append(sep[:remaining])
                remaining -= min(len(sep), remaining)
            if remaining <= 0:
                self.truncated = True
                break
            text = str(arg)
            pieces.append(text[:remaining])
            remaining -= min(len(text), remaining)
            if remaining <= 0:
                self.truncated = True
                break
        pieces.append(end[:remaining])
        self.append("".join(pieces))

    def exception(self, exc):
        trace, line = exc.__traceback__, None
        while trace is not None:
            if trace.tb_frame.f_code.co_filename == "strategy.py":
                line = trace.tb_lineno
            trace = trace.tb_next
        if line is None:
            return
        self.append(f"{type(exc).__name__}: {exc}", level="ERROR", line=line)

    def handler(self):
        import logbook

        capture = self

        class SafeHandler(logbook.Handler):
            def emit(self, record):
                if record.channel not in ("user_log", "user_system_log"):
                    return
                level = {"WARNING": "WARN", "CRITICAL": "ERROR"}.get(
                    record.level_name, record.level_name,
                )
                if level in ("INFO", "WARN", "DEBUG", "ERROR"):
                    original = getattr(record, "msg", None)
                    if (record.channel == "user_system_log"
                            and hasattr(original, "exc_val")):
                        error = getattr(original, "exc_val", None)
                        if isinstance(error, BaseException):
                            capture.exception(error)
                        return
                    message = record.message
                    if record.channel == "user_system_log" and (
                        "Traceback (" in message or "\n  File " in message
                    ):
                        message = "策略执行异常，内部堆栈已隐藏"
                    capture.append(message, level=level,
                                   source="strategy" if record.channel == "user_log" else "engine")

        return SafeHandler(level=logbook.DEBUG, bubble=False)


class StreamWriter:
    def __init__(self, output, identifier):
        self.output, self.identifier, self.bytes = output, identifier, 0
        self.counts = {table: 0 for table in (*REPORT_TABLES, "logs")}

    def write(self, payload, *, final=False):
        encoded = encoded_response({"protocol": PROTOCOL, "request_id": self.identifier, **payload})
        if self.bytes + len(encoded) > STREAM_BYTES - (0 if final else 8192):
            raise WorkerError("结果超过 64 MiB 通道限制，请缩短回测区间")
        self.output.write(encoded)
        self.output.flush()
        self.bytes += len(encoded)

    def log(self, row):
        self.write({"event": "log", "row": row})
        self.counts["logs"] += 1

    def result(self, result):
        report = result["report_data"]
        for table in REPORT_TABLES:
            rows = report[table]
            for offset in range(0, len(rows), 1000):
                batch = rows[offset:offset + 1000]
                self.write({"event": "rows", "table": table, "offset": offset, "rows": batch})
                self.counts[table] += len(batch)
        metadata = {key: value for key, value in report.items()
                    if key not in (*REPORT_TABLES, "logs")}
        metadata["counts"] = dict(self.counts)
        self.write({"ok": True, "result": {**result, "report_data": metadata}}, final=True)


def verify_bundle(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 10_000:
        raise WorkerError("冻结数据文件清单缺失")
    expected, total = set(), 0
    for row in files:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise WorkerError("冻结数据文件清单无效")
        relative = PurePosixPath(row["path"])
        if (not relative.parts or relative.is_absolute() or ".." in relative.parts
                or "\\" in row["path"] or ":" in row["path"]
                or relative.as_posix().casefold() in expected
                or type(row.get("bytes")) is not int or not 0 <= row["bytes"] <= 4 * 1024**3
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
            raise WorkerError("冻结数据路径、大小或摘要无效")
        expected.add(relative.as_posix().casefold())
        total += row["bytes"]
        if total > 8 * 1024**3:
            raise WorkerError("冻结数据超过大小限制")
        path = BUNDLE.joinpath(*relative.parts)
        if (path.is_symlink() or not path.resolve().is_relative_to(BUNDLE.resolve())
                or not path.is_file() or path.stat().st_size != row["bytes"]):
            raise WorkerError("隔离容器内数据文件与冻结清单不符")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != row["sha256"]:
            raise WorkerError("隔离容器内数据文件摘要不符")
    actual = set()
    for path in BUNDLE.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise WorkerError("隔离数据目录含链接或特殊文件")
        if path.is_file():
            folded = path.relative_to(BUNDLE).as_posix().casefold()
            if folded in actual:
                raise WorkerError("隔离数据目录含大小写冲突文件")
            actual.add(folded)
    if actual != expected:
        raise WorkerError("隔离数据目录与冻结文件集合不一致")


def inspect_bundle():
    import h5py
    import hdf5plugin  # noqa: F401
    import numpy as np

    sessions = [day(value).isoformat() for value in np.load(
        BUNDLE / "trading_dates.npy", allow_pickle=False,
    )]
    if not sessions or len(sessions) > MAX_SESSIONS or sessions != sorted(set(sessions)):
        raise WorkerError("原生交易日历缺失、无序或超出限制")
    instruments = {}
    with h5py.File(BUNDLE / "stocks.h5", "r") as store:
        for key in sorted(store.keys()):
            if not NATIVE_SYMBOL.fullmatch(key):
                continue
            dataset = store[key]
            if not isinstance(dataset, h5py.Dataset) or not len(dataset):
                continue
            if not dataset.dtype.names or "datetime" not in dataset.dtype.names:
                raise WorkerError("原生日线数据格式不受支持")
            start = day(dataset[0]["datetime"]).isoformat()
            end = day(dataset[-1]["datetime"]).isoformat()
            if start > end:
                raise WorkerError("原生证券覆盖日期无效")
            instruments[platform_symbol(key)] = {"native_symbol": key, "start": start, "end": end}
    if not instruments:
        raise WorkerError("数据包没有可用的沪深 A 股日线")
    benchmarks = {}
    with h5py.File(BUNDLE / "indexes.h5", "r") as store:
        for symbol, (native, name) in BENCHMARKS.items():
            if native not in store:
                continue
            dataset = store[native]
            if not isinstance(dataset, h5py.Dataset) or not len(dataset):
                continue
            if (not dataset.dtype.names or not {"datetime", "close"} <= set(dataset.dtype.names)
                    or len(dataset) > MAX_SESSIONS):
                raise WorkerError("原生基准日线格式无效或超出日期限制")
            valid = [day(date).isoformat() for date, close in
                     zip(dataset["datetime"], dataset["close"], strict=True)
                     if optional_number(close) is not None and float(close) > 0]
            if not valid:
                continue
            if valid != sorted(set(valid)):
                raise WorkerError("原生基准交易日无序或重复")
            benchmarks[symbol] = {"native_symbol": native, "name": name,
                                  "start": valid[0], "end": valid[-1], "sessions": valid}
    result = {"sessions": sessions, "instruments": instruments, "benchmarks": benchmarks,
              "engine_version": ENGINE_VERSION}
    encoded_response(result, INSPECTION_BYTES)
    return result


def run_config(settings, window):
    if not isinstance(settings, dict) or not isinstance(window, dict):
        raise WorkerError("回测设置缺失")
    symbols = settings.get("symbols")
    if (not isinstance(symbols, list) or not 2 <= len(symbols) <= 150
            or len(set(symbols)) != len(symbols)):
        raise WorkerError("请配置 2–150 只不重复的沪深 A 股")
    for symbol in symbols:
        native_symbol(symbol)
    if settings.get("interval") != "1d" or settings.get("universe") is not None:
        raise WorkerError("首期 RQAlpha 仅支持静态股票池日线回测")
    initial = finite(settings.get("initial_capital"))
    commission = finite(settings.get("commission_rate"))
    slippage = finite(settings.get("slippage_rate"))
    position = finite(settings.get("max_position"))
    participation = finite(settings.get("max_participation_rate"))
    if not (0 < initial <= 1e12 and 0 <= commission <= .1 and 0 <= slippage <= .1
            and 0 < position <= 1 and 0 < participation <= 1):
        raise WorkerError("资金、费用、仓位或参与率超出允许范围")
    start, end = day(window.get("start")), day(window.get("end"))
    if start >= end:
        raise WorkerError("回测需要至少两个交易日")
    benchmark = settings.get("benchmark")
    if benchmark is not None and (not isinstance(benchmark, str) or benchmark not in BENCHMARKS):
        raise WorkerError("仅支持已冻结的沪深300、中证500或上证指数基准")
    return {
        "base": {"start_date": start.isoformat(), "end_date": end.isoformat(),
                 "frequency": "1d", "run_type": "b", "accounts": {"stock": initial},
                 "data_bundle_path": str(BUNDLE), "persist": False, "auto_update_bundle": False,
                 "rqdatac_uri": "disabled", "capital_gain_tax_rate": 0},
        "extra": {"log_level": "debug"},
        "mod": {
            "sys_progress": {"enabled": False},
            "sys_simulation": {"enabled": True, "signal": False, "matching_type": "current_bar",
                               "price_limit": True, "volume_limit": True,
                               "volume_percent": participation,
                               "slippage_model": "PriceRatioSlippage", "slippage": slippage},
            "sys_transaction_cost": {"enabled": True,
                                     "stock_commission_multiplier": commission / .0008,
                                     "stock_min_commission": 5, "pit_tax": True},
            "sys_analyser": {"enabled": True, "record": True, "plot": False, "output_file": None,
                             "report_save_path": None, "plot_save_file": None,
                             "benchmark": BENCHMARKS[benchmark][0] if benchmark else None},
        },
    }


class PoolRiskValidator:
    def __init__(self, environment, symbols, maximum):
        self.env, self.symbols, self.maximum = environment, set(symbols), maximum

    def validate_submission(self, order, account=None):
        symbol = order.order_book_id
        if symbol not in self.symbols:
            return "证券不在本次股票池中"
        if order.side.name != "BUY":
            return None
        try:
            equity = finite(self.env.portfolio.total_value)
            price = finite(self.env.get_last_price(symbol))
            held = sum(finite(position.quantity) * price
                       for position in self.env.portfolio.get_positions()
                       if position.order_book_id == symbol and position.direction.name == "LONG")
            pending = sum(finite(item.unfilled_quantity) * finite(item.frozen_price)
                          for item in self.env.get_open_orders(symbol)
                          if item.side.name == "BUY" and item.order_id != order.order_id)
            incoming = finite(order.unfilled_quantity) * finite(order.frozen_price)
            if equity <= 0 or price <= 0 or incoming < 0:
                return "无法取得有效的订单估值"
            if held + pending + incoming > equity * self.maximum + 1e-6:
                return "预计单股仓位超过本次回测上限"
        except WorkerError:
            return "无法取得有效的订单估值"
        return None

    def validate_cancellation(self, order, account=None):
        return None


def _append_record(records, record):
    if len(records) >= MAX_RECORDS:
        raise WorkerError("交易或事件记录过多，请缩短回测区间")
    records.append(record)


def _parameters(request, settings):
    values = request.get("parameters", settings.get("parameters", {}))
    if not isinstance(values, dict) or len(values) > 80:
        raise WorkerError("策略参数必须为不超过 80 项的 JSON 对象")
    for key, value in values.items():
        if (not isinstance(key, str) or len(key) > 100
                or not isinstance(value, (str, int, float, bool))
                or isinstance(value, str) and len(value) > 2000):
            raise WorkerError("策略参数只支持字符串、数值和布尔值")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            finite(value)
    return dict(values)


def _native_name(value):
    return value.name if hasattr(value, "name") else str(value)


def _optional_name(value):
    return value[:100] if isinstance(value, str) and value else None


def _matching_values(captured, *, quantity=None, equity=None, market_value=None, cash=None):
    if not captured:
        return False
    for key, value, tolerance in (("quantity", quantity, 1e-8),
                                  ("equity", equity, .02),
                                  ("market_value", market_value, .02), ("cash", cash, .02)):
        observed = optional_number(captured.get(key))
        if value is not None and (observed is None or abs(observed - value) > tolerance):
            return False
    return True


def convert_result(native, initial, sellable, rejections, *, snapshots=None,
                   daily_snapshots=None, sellable_snapshots=None, capture=None,
                   risk_free_rate=None, trading_days=None):
    snapshots, daily_snapshots = snapshots or {}, daily_snapshots or {}
    sellable_snapshots = sellable_snapshots or {}
    capture = capture or ReportCapture()
    portfolio = native["portfolio"]
    if portfolio.empty:
        raise WorkerError("原生引擎没有生成净值记录")
    total = sum(len(native.get(key, ())) for key in
                ("portfolio", "trades", "stock_positions", "stock_account",
                 "benchmark_portfolio", "portfolio_event")) + len(rejections)
    if total > MAX_RECORDS:
        raise WorkerError("回测记录过多，请缩短区间")
    equity = []
    for index, row in portfolio.iterrows():
        value, market_value = finite(row["total_value"]), finite(row["market_value"])
        cash = finite(row["cash"])
        captured = daily_snapshots.get(day(index).isoformat(), {}).get("portfolio")
        matches = _matching_values(captured, equity=value, market_value=market_value, cash=cash)
        equity.append({"time": timestamp(index, close=True), "equity": value,
                       "cash": cash, "market_value": market_value,
                       "net_value": finite(row["unit_net_value"]), "units": finite(row["units"]),
                       "static_unit_net_value": finite(row["static_unit_net_value"]),
                       "daily_pnl": optional_number(captured.get("daily_pnl")) if matches else None,
                       **{field: optional_number(captured.get(field)) if matches else None
                          for field in MONETARY_FIELDS}})
    trades = []
    for _, row in native["trades"].iterrows():
        side = _native_name(row["side"]).lower()
        effect = _native_name(row["position_effect"]).lower()
        if side not in ("buy", "sell") or effect not in (
            "open", "close", "close_today", "exercise", "match", "split", "unsplit",
        ):
            raise WorkerError("原生引擎返回了不支持的交易方向或开平类型")
        trades.append({"time": timestamp(row["datetime"]),
                       "symbol": platform_symbol(row["order_book_id"]), "side": side,
                       "name": _optional_name(row["symbol"]), "position_effect": effect,
                       "quantity": finite(row["last_quantity"]), "price": finite(row["last_price"]),
                       "fee": finite(row["transaction_cost"]),
                       "commission": finite(row["commission"]),
                       "tax": finite(row["tax"]), "order_id": str(row["order_id"]),
                       "exec_id": str(row["exec_id"])})
    positions, history, actions = [], [], []
    final_day = day(portfolio.index[-1]).isoformat()
    for index, row in native["stock_positions"].iterrows():
        current_day = day(index).isoformat()
        symbol, quantity = row["order_book_id"], finite(row["quantity"])
        value, price = finite(row["market_value"]), finite(row["last_price"])
        captured = snapshots.get((current_day, symbol))
        matches = _matching_values(captured, quantity=quantity, market_value=value)
        receivable = optional_number(captured.get("dividend_receivable")) if matches else None
        available = sellable_snapshots.get((current_day, symbol))
        if available is None and current_day == final_day:
            available = sellable.get(symbol)
        available = (optional_number(available.get("sellable"))
                     if available and available.get("day") == current_day
                     and _matching_values(available, quantity=quantity, market_value=value) else None)
        history.append({"time": timestamp(index, close=True), "symbol": platform_symbol(symbol),
                        "name": _optional_name(row["symbol"]), "last_price": price,
                        "direction": "long", "quantity": quantity,
                        "avg_price": optional_number(row["avg_price"]), "market_value": value,
                        "pnl": optional_number(captured.get("pnl")) if matches else None,
                        "fee": optional_number(captured.get("fee")) if matches else None,
                        "dividend_receivable": receivable, "sellable": available})
        if (current_day != final_day or quantity <= 0
                and (receivable is None or receivable <= 0)):
            continue
        positions.append({"symbol": platform_symbol(symbol), "quantity": quantity,
                          "sellable": available, "mark_price": price, "market_value": value,
                          "dividend_receivable": receivable})
    accounts = []
    for index, row in native["stock_account"].iterrows():
        value, market_value = finite(row["total_value"]), finite(row["market_value"])
        cash = finite(row["cash"])
        captured = daily_snapshots.get(day(index).isoformat(), {}).get("stock")
        matches = _matching_values(captured, equity=value, market_value=market_value, cash=cash)
        accounts.append({"time": timestamp(index, close=True), "account_type": "stock",
                         "cash": cash, "equity": value,
                         "market_value": market_value, "margin": None,
                         "fee": finite(row["transaction_cost"]),
                         "daily_pnl": optional_number(captured.get("daily_pnl")) if matches else None,
                         **{field: optional_number(captured.get(field)) if matches else None
                            for field in MONETARY_FIELDS}})
    benchmark = []
    native_benchmark = native.get("benchmark_portfolio")
    if native_benchmark is not None:
        benchmark = [{"time": timestamp(index, close=True),
                      "net_value": finite(row["unit_net_value"])}
                     for index, row in native_benchmark.iterrows()]
    events = native.get("portfolio_event")
    if events is not None:
        for index, row in events.iterrows():
            symbol = row.get("order_book_id")
            symbol = platform_symbol(symbol) if isinstance(symbol, str) else None
            _append_record(actions, {
                "time": timestamp(row.get("datetime", index)), "symbol": symbol,
                "type": _native_name(row["event_category"])[:100],
                "amount": optional_number(row.get("delta_amount")),
                "quantity": optional_number(row.get("delta_quantity")),
                "remark": str(row.get("remark", ""))[:400],
            })
    if sum(map(len, (equity, trades, positions, actions, rejections,
                     history, accounts, benchmark))) > MAX_RECORDS:
        raise WorkerError("回测记录过多，请缩短区间")
    peak, drawdown = initial, 0.0
    for point in equity:
        peak = max(peak, point["equity"])
        if peak > 0:
            drawdown = max(drawdown, 1 - point["equity"] / peak)
    metrics = {str(key): optional_number(value) for key, value in native["summary"].items()
               if value is None
               or isinstance(value, numbers.Number) and not isinstance(value, bool)}
    report = {"schema_version": REPORT_SCHEMA, "positions": history, "accounts": accounts,
              "benchmark": benchmark, "logs": capture.logs, "logs_truncated": capture.truncated,
              "risk_free_rate": risk_free_rate, "trading_days_a_year": trading_days,
              "risk_free_rate_status": "native" if risk_free_rate is not None else "unavailable",
              "position_snapshot_time": "post_settlement_before_account_reset",
              "account_snapshot_time": "post_settlement_before_account_reset",
              "sellable_snapshot_time": "after_trading_before_settlement",
              "pnl_semantics": "unrealized_position_pnl", "fee_semantics": "daily_transaction_cost"}
    report["counts"] = {table: len(report[table]) for table in (*REPORT_TABLES, "logs")}
    return {"equity": equity, "trades": trades, "positions": positions, "rejections": rejections,
            "corporate_actions": actions, "initial_capital": initial,
            "final_equity": equity[-1]["equity"],
            "total_return": equity[-1]["equity"] / initial - 1, "max_drawdown": drawdown,
            "native_metrics": metrics, "matching_type": "current_bar",
            "engine_version": ENGINE_VERSION, "report_data": report}


def run_backtest(request):
    compiled = check_source(request.get("source"))
    settings = request.get("settings")
    config = run_config(settings, request.get("window"))
    parameters = _parameters(request, settings)
    symbols = [native_symbol(symbol) for symbol in settings["symbols"]]
    from rqalpha import run_func
    from rqalpha.core.events import EVENT
    from rqalpha.environment import Environment
    from rqalpha.main import create_base_scope, get_strategy_apis

    capture = request.get("_report_capture") or ReportCapture()
    callbacks, rejections, sellable, snapshots, daily = {}, [], {}, {}, {}
    available = {}
    rates = {"risk_free_rate": None, "trading_days": None}

    def clock():
        try:
            return Environment.get_instance().calendar_dt
        except (AttributeError, RuntimeError):
            return None

    capture.clock = clock

    def invoke(callback, *args):
        if callback is None:
            return
        try:
            return callback(*args)
        except BaseException as exc:
            capture.exception(exc)
            raise

    def creation_rejected(event):
        env = Environment.get_instance()
        _append_record(rejections, {"time": timestamp(env.calendar_dt),
                                    "symbol": rejected_symbol(event.order_book_id),
                                    "reason": sanitize_log(event.reason)[:400]})

    def unsolicited_update(event):
        order = event.order
        if order.status.name not in ("REJECTED", "CANCELLED"):
            return
        env = Environment.get_instance()
        _append_record(rejections, {"time": timestamp(env.calendar_dt),
                                    "symbol": rejected_symbol(order.order_book_id),
                                    "reason": sanitize_log(order.message or order.status.name)[:400]})

    def collect_settlement(_):
        env = Environment.get_instance()
        current_day = env.calendar_dt.date().isoformat()
        portfolio = env.portfolio
        accounts = list(portfolio.accounts.items())
        if len(accounts) != 1 or _native_name(accounts[0][0]).upper() != "STOCK":
            raise WorkerError("首期 RQAlpha 报告仅支持单个股票账户")
        account = accounts[0][1]
        positions = list(account.get_positions())
        components = {
            "frozen_cash": finite(account.frozen_cash),
            "dividend_receivable": sum(finite(getattr(position, "dividend_receivable", 0))
                                       for position in positions),
            "cash_liabilities": finite(account.cash_liabilities),
            "cash_liabilities_interest": finite(account.cash_liabilities_interest),
            "pending_cash_flow": sum(finite(amount)
                                     for _, amount in account._pending_deposit_withdraw),
        }
        daily[current_day] = {
            "portfolio": {"equity": finite(portfolio.total_value),
                          "cash": finite(portfolio.cash),
                          "market_value": finite(portfolio.market_value),
                          "daily_pnl": finite(portfolio.daily_pnl), **components},
            "stock": {"equity": finite(account.total_value), "cash": finite(account.cash),
                      "market_value": finite(account.market_value),
                      "daily_pnl": finite(account.daily_pnl), **components},
        }
        for position in positions:
            symbol = position.order_book_id
            if len(snapshots) >= MAX_RECORDS:
                raise WorkerError("逐日持仓记录过多，请缩短区间")
            snapshots[(current_day, symbol)] = {
                "quantity": finite(position.quantity),
                "market_value": finite(position.market_value),
                "pnl": optional_number(position.pnl),
                "fee": optional_number(position.transaction_cost),
                "dividend_receivable": finite(getattr(position, "dividend_receivable", 0)),
            }

    def initialize(context):
        env = Environment.get_instance()
        env.add_frontend_validator(PoolRiskValidator(env, symbols, settings["max_position"]))
        env.event_bus.add_listener(EVENT.ORDER_CREATION_REJECT, creation_rejected)
        env.event_bus.add_listener(EVENT.ORDER_UNSOLICITED_UPDATE, unsolicited_update)
        env.event_bus.prepend_listener(EVENT.POST_SETTLEMENT, collect_settlement)
        try:
            rates["risk_free_rate"] = optional_number(env.data_proxy.get_risk_free_rate(
                env.config.base.start_date, env.config.base.end_date,
            ))
            rates["trading_days"] = optional_number(env.trading_days_a_year)
        except (AttributeError, RuntimeError, ValueError, TypeError, KeyError, OSError):
            rates["risk_free_rate"] = None
        scope = create_base_scope()
        scope.update(get_strategy_apis())
        scope["g"], scope["print"] = env.global_vars, capture.user_print
        context.parameters, context.symbols = parameters, tuple(symbols)
        invoke(exec, compiled, scope)
        for name in ("init", "handle_bar", "before_trading", "after_trading", "open_auction"):
            callback = scope.get(name)
            if callback is not None and not callable(callback):
                raise WorkerError("策略约定入口必须是函数")
            callbacks[name] = callback
        if callbacks["init"] is None or callbacks["handle_bar"] is None:
            raise WorkerError("策略约定入口缺失")
        invoke(callbacks["init"], context)

    def handle_bar(context, bars):
        invoke(callbacks["handle_bar"], context, bars)

    def before_trading(context):
        invoke(callbacks["before_trading"], context)

    def after_trading(context):
        invoke(callbacks["after_trading"], context)
        current_day = context.now.date().isoformat()
        for position in context.portfolio.get_positions():
            symbol = position.order_book_id
            if position.quantity > 0:
                quantity = finite(position.quantity)
                captured = {"day": current_day, "quantity": quantity,
                            "sellable": optional_number(position.closable),
                            "market_value": finite(position.market_value)}
                if len(available) >= MAX_RECORDS:
                    raise WorkerError("逐日可卖持仓记录过多，请缩短区间")
                available[(current_day, symbol)] = captured
                sellable[symbol] = captured

    def open_auction(context, bars):
        invoke(callbacks["open_auction"], context, bars)

    with capture.handler().applicationbound():
        native = run_func(config=config, init=initialize, handle_bar=handle_bar,
                          before_trading=before_trading, after_trading=after_trading,
                          open_auction=open_auction)["sys_analyser"]
    return convert_result(native, config["base"]["accounts"]["stock"], sellable, rejections,
                          snapshots=snapshots, daily_snapshots=daily, sellable_snapshots=available,
                          capture=capture, **rates)


def dispatch(request):
    if version("rqalpha") != ENGINE_VERSION:
        raise WorkerError("隔离引擎版本与固定版本不符")
    verify_bundle(request.get("bundle_files"))
    return inspect_bundle() if request["op"] == "inspect" else run_backtest(request)


def serve(input_stream, output_stream):
    identifier, writer = None, None
    capture = ReportCapture()
    try:
        request = parse_request(input_stream.readline(INPUT_BYTES + 1))
        identifier = request["request_id"]
        if request.get("stream") is True:
            writer = StreamWriter(output_stream, identifier)
            capture.emit = writer.log
        request["_report_capture"] = capture
        with contextlib.redirect_stdout(sys.stderr):
            result = dispatch(request)
        if writer is not None:
            writer.result(result)
            return
        response = {"protocol": PROTOCOL, "request_id": identifier, "ok": True, "result": result}
        encoded = encoded_response(response)
    except BaseException as exc:  # noqa: BLE001 - isolate user SystemExit and KeyboardInterrupt.
        message = (sanitize_log(exc) if isinstance(exc, WorkerError)
                   else "RQAlpha 执行未完成，请检查策略和数据")
        error = {"message": message[:400]}
        cause = exc.__cause__
        if (isinstance(cause, SyntaxError) and cause.filename == "strategy.py"
                and type(cause.lineno) is int):
            capture.append(message, level="ERROR", source="strategy", line=cause.lineno)
        lines = [row["line"] for row in capture.logs if row.get("line") is not None]
        if lines:
            error["line"] = lines[-1]
        report = {"schema_version": REPORT_SCHEMA, "logs_truncated": capture.truncated,
                  "counts": dict(writer.counts) if writer else {"logs": len(capture.logs)}}
        if writer is None:
            report["logs"] = capture.logs
        failure = {"ok": False, "error": error, "report_data": report}
        if writer is not None:
            writer.write(failure, final=True)
            return
        encoded = encoded_response({"protocol": PROTOCOL, "request_id": identifier, **failure})
    output_stream.write(encoded)
    output_stream.flush()


def main():
    os.chdir("/tmp")
    serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
