import ast
import hashlib
import json
import math
import os
import re
from datetime import UTC, date, datetime, time
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from app.compute_objects import canonical_bytes
from app.rqalpha_reports import (
    BENCHMARKS,
    MAX_RECORDS,
    build_report,
    equity_components,
    number,
    text,
)
from app.sandbox import RqalphaSandbox, RunnerFailure, RunnerUnavailable, rqalpha_runner_status

ENGINE_VERSION = "6.5.0"
RULE_VERSION = "rqalpha-a-share/6.5.0"
CHINA = ZoneInfo("Asia/Shanghai")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
DIGEST = re.compile(r"[a-f0-9]{64}")
SYMBOL = re.compile(r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)")


def validate_source(source, package_b64=None):
    if package_b64:
        raise RunnerFailure("RQAlpha 首期仅接受原生 Python 源码，不接受 Atlas 策略包")
    try:
        valid_size = isinstance(source, str) and len(source.encode()) <= 60_000
    except UnicodeError:
        valid_size = False
    if not valid_size or not source.strip():
        raise RunnerFailure("请输入不超过 60,000 UTF-8 字节的 RQAlpha 源码")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise RunnerFailure("RQAlpha 源码语法无效，请检查 Python 代码") from exc
    entries = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not {"init", "handle_bar"} <= entries:
        raise RunnerFailure("RQAlpha 源码需要定义 init(context) 和 handle_bar(context, bar_dict)")
    if any(isinstance(node, ast.Name) and node.id == "__config__"
           and isinstance(node.ctx, ast.Store) for node in ast.walk(tree)):
        raise RunnerFailure("请在平台设置回测参数，不要在源码声明 __config__")


def runner_image():
    return os.environ.get("ATLAS_RQALPHA_RUNNER_IMAGE", "")


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid date")
    return value


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "," in value:
        raise ValueError("Invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid relative path")
    return path


def _dataset():
    location = os.environ.get("ATLAS_RQALPHA_DATASET", "")
    directory = os.environ.get("ATLAS_RQALPHA_BUNDLE_DIR", "")
    if not location or not directory:
        raise RunnerUnavailable("RQAlpha 官方日线快照尚未准备，需配置清单和只读目录")
    try:
        with Path(location).open("rb") as stream:
            body = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(body) > MAX_MANIFEST_BYTES:
            raise ValueError("Oversized dataset manifest")
        value = json.loads(body)
        if (not isinstance(value, dict) or value.get("schema") != "atlas.rqalpha.dataset/v1"
                or value.get("engine_version") != ENGINE_VERSION
                or value.get("usage") != "academic-noncommercial-local-research"):
            raise ValueError("Invalid dataset identity")
        digest = value.get("digest")
        identity = {key: item for key, item in value.items() if key != "digest"}
        if (not isinstance(digest, str) or not DIGEST.fullmatch(digest)
                or hashlib.sha256(canonical_bytes(identity)).hexdigest() != digest):
            raise ValueError("Dataset digest mismatch")
        sessions = value["sessions"]
        if (not isinstance(sessions, list) or not 2 <= len(sessions) <= 20_000
                or [_day(day) for day in sessions] != sorted(set(sessions))):
            raise ValueError("Invalid calendar")
        instruments = value["instruments"]
        if not isinstance(instruments, dict) or not 1 <= len(instruments) <= 30_000:
            raise ValueError("Invalid instrument coverage")
        for symbol, item in instruments.items():
            if not SYMBOL.fullmatch(symbol) or not isinstance(item, dict):
                raise ValueError("Invalid instrument")
            native = symbol[:6] + (".XSHG" if symbol.endswith(".SS") else ".XSHE")
            if item.get("native_symbol") != native or _day(item["start"]) > _day(item["end"]):
                raise ValueError("Invalid instrument range")
        benchmarks = value.get("benchmarks", {})
        if (not isinstance(benchmarks, dict)
                or any(symbol not in BENCHMARKS for symbol in benchmarks)):
            raise ValueError("Invalid benchmark coverage")
        for symbol, item in benchmarks.items():
            if (not isinstance(item, dict) or item.get("native_symbol") != symbol[:6] + ".XSHG"
                    or item.get("name") != BENCHMARKS[symbol]
                    or _day(item["start"]) > _day(item["end"])):
                raise ValueError("Invalid benchmark identity")
            covered = item["sessions"]
            if (not isinstance(covered, list) or not 2 <= len(covered) <= 20_000
                    or [_day(day) for day in covered] != sorted(set(covered))
                    or covered[0] != item["start"] or covered[-1] != item["end"]):
                raise ValueError("Invalid benchmark calendar")
        files = value["files"]
        if not isinstance(files, list) or not 1 <= len(files) <= 10_000:
            raise ValueError("Invalid file manifest")
        root = Path(directory).resolve(strict=True)
        bundle = (root / _relative(value["bundle_root"])).resolve(strict=True)
        if not bundle.is_dir() or not bundle.is_relative_to(root):
            raise ValueError("Invalid bundle root")
        seen = set()
        for row in files:
            relative = _relative(row["path"])
            if relative.as_posix().casefold() in seen:
                raise ValueError("Duplicate file path")
            seen.add(relative.as_posix().casefold())
            file = root / relative
            if (file.is_symlink() or not file.resolve(strict=True).is_relative_to(root)
                    or not file.is_file() or type(row["bytes"]) is not int or row["bytes"] < 0
                    or file.stat().st_size != row["bytes"]
                    or not isinstance(row["sha256"], str) or not DIGEST.fullmatch(row["sha256"])):
                raise ValueError("Invalid bundle file")
        required = {"instruments.pk", "trading_dates.npy", "stocks.h5"}
        if benchmarks:
            required.add("indexes.h5")
        if not required <= {
            (root / row["path"]).relative_to(bundle).as_posix()
            for row in files if (root / row["path"]).is_relative_to(bundle)
        }:
            raise ValueError("Incomplete native bundle")
        actual = set()
        for file in root.rglob("*"):
            if file.is_symlink() or not (file.is_file() or file.is_dir()):
                raise ValueError("Unexpected bundle entry")
            if file.is_file():
                folded = file.relative_to(root).as_posix().casefold()
                if folded in actual:
                    raise ValueError("Case-colliding bundle entry")
                actual.add(folded)
        if actual != seen:
            raise ValueError("Bundle file set differs from manifest")
        return value, root, bundle
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise RunnerUnavailable("RQAlpha 日线快照清单、覆盖或文件完整性检查失败") from exc


def runner_files(manifest, root, bundle):
    return [{**row, "path": (root / row["path"]).relative_to(bundle).as_posix()}
            for row in manifest["files"] if (root / row["path"]).is_relative_to(bundle)]


def runner_status():
    available, reason = rqalpha_runner_status()
    if not available:
        return available, reason
    try:
        _dataset()
    except RunnerUnavailable as exc:
        return False, str(exc)
    return True, None


def benchmark_options():
    dataset, _, _ = _dataset()
    return [{"symbol": symbol, "name": BENCHMARKS[symbol],
             "start": item["start"], "end": item["end"]}
            for symbol, item in dataset.get("benchmarks", {}).items()]


def _close(day):
    return int(datetime.combine(date.fromisoformat(day), time(15), CHINA).timestamp())


def resolve(settings):
    if settings.interval != "1d" or settings.universe:
        raise RunnerFailure("RQAlpha 首期只支持静态股票池日线回测")
    if len(settings.symbols) < 2 or any(not SYMBOL.fullmatch(s) for s in settings.symbols):
        raise RunnerFailure("RQAlpha 首期需要至少两只带 .SS 或 .SZ 后缀的沪深 A 股")
    dataset, _, _ = _dataset()
    try:
        coverage = [dataset["instruments"][symbol] for symbol in settings.symbols]
    except KeyError as exc:
        raise RunnerFailure("所选股票未被当前 RQAlpha 日线快照覆盖") from exc
    lower = max(row["start"] for row in coverage)
    upper = min(row["end"] for row in coverage)
    start = settings.start.astimezone(CHINA).date().isoformat() if settings.start else lower
    end = settings.end.astimezone(CHINA).date().isoformat() if settings.end else upper
    if start < lower or end > upper:
        raise RunnerFailure(f"股票池共同日线覆盖范围为 {lower} 至 {upper}，请调整区间")
    now = int(datetime.now(UTC).timestamp())
    days = [day for day in dataset["sessions"] if start <= day <= end
            and _close(day) <= now
            and (settings.start is None or _close(day) >= settings.start.timestamp())
            and (settings.end is None or _close(day) <= settings.end.timestamp())]
    if len(days) < 2:
        raise RunnerFailure("选择的区间内不足两个已收盘的真实交易日")
    if len(days) * (len(settings.symbols) + 2) + len(days) > MAX_RECORDS:
        raise RunnerFailure("RQAlpha 逐日持仓与账户预计超过 250,000 条，请缩短区间或股票池")
    benchmark = None
    if settings.benchmark:
        benchmark = dataset.get("benchmarks", {}).get(settings.benchmark)
        if benchmark is None:
            raise RunnerFailure("当前冻结快照未核验所选基准，请准备指数覆盖清单；不会自动下载行情")
        previous = [day for day in dataset["sessions"] if day < days[0]]
        if not previous or not set([previous[-1], *days]) <= set(benchmark["sessions"]):
            raise RunnerFailure("基准需要覆盖全部回测日及前一交易日，请调整区间或准备完整冻结数据")
    years = sorted({int(day[:4]) for day in days})
    selected = set(days)
    full_years = [year for year in years
                  if dataset["sessions"][0] < f"{year}-01-01"
                  and dataset["sessions"][-1] > f"{year}-12-31"
                  and {day for day in dataset["sessions"] if day.startswith(str(year))} <= selected]
    return {"digest": dataset["digest"], "rule_version": RULE_VERSION,
            "engine_version": ENGINE_VERSION, "benchmark": settings.benchmark,
            "benchmark_coverage": benchmark, "full_years": full_years,
            "engine_id": "rqalpha", "start": _close(days[0]), "end": _close(days[-1]),
            "count": len(days), "sessions": days, "window": {"start": days[0], "end": days[-1]}}


def _number(value, *, minimum=None, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or minimum is not None and value < minimum
            or maximum is not None and value > maximum):
        raise RunnerFailure("RQAlpha 返回了非法数值")
    return value


def validate_result(result, settings, market):
    if (not isinstance(result, dict) or result.get("engine_version") != ENGINE_VERSION
            or result.get("matching_type") != "current_bar"):
        raise RunnerFailure("RQAlpha 返回的引擎版本或撮合规则不一致")
    collections = ("equity", "trades", "positions", "rejections", "corporate_actions")
    if any(not isinstance(result.get(key), list) for key in collections):
        raise RunnerFailure("RQAlpha 结果缺少必要记录")
    if sum(len(result[key]) for key in collections) > MAX_RECORDS:
        raise RunnerFailure("RQAlpha 结果记录超过 250,000")
    if any(not isinstance(row, dict) for key in collections for row in result[key]):
        raise RunnerFailure("RQAlpha 结果记录格式不合法")
    equity = []
    source_equity = result["equity"]
    if [row.get("time") for row in source_equity] != [_close(day) for day in market["sessions"]]:
        raise RunnerFailure("RQAlpha 净值未覆盖冻结交易日历")
    peak, drawdown = settings.initial_capital, 0
    for row in source_equity:
        total = _number(row.get("equity"), minimum=0, maximum=1e15)
        cash = _number(row.get("cash"), minimum=-.02, maximum=1e15)
        value = _number(row.get("market_value"), minimum=0, maximum=1e15)
        point = {"time": row["time"], "equity": total, "cash": cash, "market_value": value}
        if "report_data" in result:
            point.update(equity_components({**row, **point}))
        elif abs(cash + value - total) > .02:
            raise RunnerFailure("RQAlpha 现金与市值未闭合到账户权益")
        if "net_value" in row:
            point["net_value"] = number(row["net_value"], 0, 1e12)
        if "daily_pnl" in row:
            point["daily_pnl"] = number(row["daily_pnl"], -1e15, 1e15, optional=True)
        equity.append(point)
        peak = max(peak, total)
        drawdown = max(drawdown, 1 - total / peak)
    lower = int(datetime.combine(
        date.fromisoformat(market["window"]["start"]), time(), CHINA,
    ).timestamp())
    upper = int(datetime.combine(
        date.fromisoformat(market["window"]["end"]), time(23, 59, 59), CHINA,
    ).timestamp())
    trades = []
    for trade in result["trades"]:
        if trade.get("symbol") not in settings.symbols or trade.get("side") not in ("buy", "sell"):
            raise RunnerFailure("RQAlpha 成交含池外标的或非法方向")
        _number(trade.get("time"), minimum=lower, maximum=upper)
        _number(trade.get("quantity"), minimum=1e-12, maximum=1e12)
        _number(trade.get("price"), minimum=1e-12, maximum=1e9)
        fee = _number(trade.get("fee"), minimum=0)
        commission = _number(trade.get("commission"), minimum=0)
        tax = _number(trade.get("tax"), minimum=0)
        if abs(fee - commission - tax) > .01:
            raise RunnerFailure("RQAlpha 成交费用细项不一致")
        normalized = {key: trade[key] for key in
                      ("time", "symbol", "side", "quantity", "price", "fee", "commission", "tax")}
        for field in ("order_id", "exec_id", "name"):
            if field in trade:
                normalized[field] = text(trade[field], optional=field == "name")
        effect = trade.get("position_effect")
        if effect not in (None, "open", "close", "close_today", "close_yesterday"):
            raise RunnerFailure("RQAlpha 成交开平字段无效")
        if "position_effect" in trade:
            normalized["position_effect"] = effect
        trades.append(normalized)
    seen, market_value, dividends = set(), 0, 0
    for position in result["positions"]:
        symbol = position.get("symbol")
        if symbol not in settings.symbols or symbol in seen:
            raise RunnerFailure("RQAlpha 期末持仓含重复或池外标的")
        seen.add(symbol)
        quantity = _number(position.get("quantity"), minimum=0, maximum=1e12)
        if position.get("sellable") is not None:
            _number(position["sellable"], minimum=0, maximum=quantity)
        if position.get("mark_price") is not None:
            _number(position["mark_price"], minimum=0, maximum=1e9)
        market_value += _number(position.get("market_value"), minimum=0)
        if "report_data" in result:
            dividends += number(position.get("dividend_receivable"), 0, 1e15)
    if (abs(market_value - equity[-1]["market_value"]) > .02
            or "report_data" in result
            and abs(dividends - equity[-1]["dividend_receivable"]) > .02):
        raise RunnerFailure("RQAlpha 期末持仓市值或应收分红与账户不一致")
    for row in result["rejections"]:
        if (not isinstance(row.get("symbol"), str) or not 1 <= len(row["symbol"]) <= 80
                or not isinstance(row.get("reason"), str) or len(row["reason"]) > 400):
            raise RunnerFailure("RQAlpha 拒单记录不合法")
        _number(row.get("time"), minimum=lower, maximum=upper)
    for row in result["corporate_actions"]:
        if (row.get("symbol") is not None and row["symbol"] not in settings.symbols
                or not isinstance(row.get("type"), str) or len(row["type"]) > 100
                or not isinstance(row.get("remark"), str) or len(row["remark"]) > 400):
            raise RunnerFailure("RQAlpha 公司行动记录不合法")
        _number(row.get("time"), minimum=lower, maximum=upper)
        for field in ("amount", "quantity"):
            if row.get(field) is not None:
                _number(row[field])
    metrics = result.get("native_metrics", {})
    if not isinstance(metrics, dict) or len(metrics) > 150:
        raise RunnerFailure("RQAlpha 指标结构不合法")
    for key, value in metrics.items():
        if not isinstance(key, str) or len(key) > 100:
            raise RunnerFailure("RQAlpha 指标名称不合法")
        if value is not None:
            _number(value)
    validated = {key: result[key] for key in collections} | {
        "equity": equity, "trades": trades,
        "kind": "multi_python", "engine_id": "rqalpha", "engine_version": ENGINE_VERSION,
        "sdk_version": "atlas.rqalpha/v1", "matching_type": "current_bar", "currency": "CNY",
        "proof_status": "unverified", "interval": "1d", "symbols": settings.symbols,
        "initial_capital": settings.initial_capital, "final_equity": equity[-1]["equity"],
        "total_return": equity[-1]["equity"] / settings.initial_capital - 1,
        "max_drawdown": drawdown, "native_metrics": metrics,
        "cost_model": {"stock_min_commission": 5, "pit_tax": True,
                       "commission_rate": settings.commission_rate,
                       "slippage_rate": settings.slippage_rate},
    }
    if "report_data" in result:
        validated.update(build_report(validated, settings, market, result["report_data"]))
        validated["total_return"] = metrics.get("total_returns")
        if validated["total_return"] is None:
            validated["total_return"] = equity[-1]["net_value"] - 1
        interval = validated["report"]["drawdown"]
        validated["max_drawdown"] = metrics.get("max_drawdown")
        if validated["max_drawdown"] is None:
            validated["max_drawdown"] = interval["value"] if interval else 0
    return validated


def execute(source, settings, market, *, cancelled=None):
    validate_source(source)
    dataset, root, bundle = _dataset()
    if market["digest"] != dataset["digest"]:
        raise RunnerFailure("RQAlpha 日线快照已变更，请重新检查并创建回测")
    for row in dataset["files"]:
        digest = hashlib.sha256()
        try:
            with (root / row["path"]).open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    if cancelled and cancelled():
                        raise RunnerFailure("RQAlpha 执行已取消")
                    digest.update(chunk)
        except OSError as exc:
            raise RunnerFailure("RQAlpha 冻结数据文件无法读取") from exc
        if digest.hexdigest() != row["sha256"]:
            raise RunnerFailure("RQAlpha 冻结数据文件摘要不符")
    runner = RqalphaSandbox(bundle, cancelled=cancelled)
    try:
        with runner:
            result = runner.run({"op": "run", "source": source,
                                 "bundle_files": runner_files(dataset, root, bundle),
                                 "settings": settings.model_dump(mode="json"),
                                 "parameters": settings.parameters, "window": market["window"]})
        return validate_result(result, settings, market)
    except (RunnerFailure, RunnerUnavailable) as exc:
        if not hasattr(exc, "report_logs"):
            exc.report_logs = getattr(runner, "report_logs", [])
            exc.logs_truncated = getattr(runner, "logs_truncated", False)
        raise
