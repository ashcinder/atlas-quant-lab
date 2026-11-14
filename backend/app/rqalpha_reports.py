import math
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from app.sandbox import RunnerFailure

SCHEMA = "atlas.rqalpha.report/v1"
RAW_SCHEMA = "atlas.rqalpha.raw-report/v1"
MAX_RECORDS = 250_000
BENCHMARKS = {"000300.SS": "沪深300", "000905.SS": "中证500", "000001.SS": "上证指数"}
CHINA = ZoneInfo("Asia/Shanghai")
EQUITY_FIELDS = (
    "frozen_cash",
    "dividend_receivable",
    "cash_liabilities",
    "cash_liabilities_interest",
    "pending_cash_flow",
)


def equity_components(row):
    values = {
        key: number(row.get(key), -1e15 if key == "pending_cash_flow" else -0.02, 1e15)
        for key in EQUITY_FIELDS
    }
    total = (
        row["cash"]
        + row["market_value"]
        + values["frozen_cash"]
        + values["dividend_receivable"]
        + values["pending_cash_flow"]
        - values["cash_liabilities"]
        - values["cash_liabilities_interest"]
    )
    if abs(total - row["equity"]) > 0.02:
        raise RunnerFailure("RQAlpha 原生资金组成与权益不闭合")
    return values


def number(value, minimum=None, maximum=None, *, optional=False):
    if value is None and optional:
        return None
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or minimum is not None
        and value < minimum
        or maximum is not None
        and value > maximum
    ):
        raise RunnerFailure("RQAlpha 报告包含非法数值")
    return value


def text(value, limit=100, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise RunnerFailure("RQAlpha 报告包含非法文本")
    return "".join(char for char in value if char in "\n\t" or ord(char) >= 32)


def validate_logs(rows, *, truncated=False):
    if not isinstance(rows, list) or len(rows) > 2000 or type(truncated) is not bool:
        raise RunnerFailure("RQAlpha 日志超过采集限制")
    result, size = [], 0
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or type(row.get("sequence")) is not int
            or row["sequence"] != index
            or row.get("level") not in {"INFO", "WARN", "DEBUG", "ERROR"}
            or row.get("source") not in {"strategy", "engine", "system"}
        ):
            raise RunnerFailure("RQAlpha 日志记录格式无效")
        message = text(row.get("message"), 4096)
        size += len(message.encode("utf-8"))
        if size > 1024 * 1024:
            raise RunnerFailure("RQAlpha 日志超过采集体积限制")
        stamp = number(row.get("time"), 0, 4_102_444_800, optional=True)
        line = row.get("line")
        if line is not None and (type(line) is not int or not 1 <= line <= 60_000):
            raise RunnerFailure("RQAlpha 策略日志行号无效")
        result.append(
            {
                "sequence": index,
                "time": stamp,
                "level": row["level"],
                "source": row["source"],
                "message": message,
                "line": line,
            }
        )
    return result


def _rows(raw, name):
    rows = raw.get(name)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RunnerFailure("RQAlpha 报告缺少完整的原生明细")
    return rows


def validate_raw(raw, result, settings, market):
    if not isinstance(raw, dict) or raw.get("schema_version") != RAW_SCHEMA:
        raise RunnerFailure("RQAlpha 报告结构版本不一致")
    positions, accounts = _rows(raw, "positions"), _rows(raw, "accounts")
    benchmark, logs = _rows(raw, "benchmark"), _rows(raw, "logs")
    base = sum(
        len(result[key])
        for key in ("equity", "trades", "positions", "rejections", "corporate_actions")
    )
    if base + len(positions) + len(accounts) + len(benchmark) > MAX_RECORDS:
        raise RunnerFailure("RQAlpha 报告超过 250,000 条经济记录限制")
    points = {point["time"]: point for point in result["equity"]}
    stamps = list(points)
    totals, receivables = defaultdict(float), defaultdict(float)
    seen, normalized_positions = set(), []
    previous = -1
    for row in positions:
        stamp, symbol = row.get("time"), row.get("symbol")
        if (
            type(stamp) is not int
            or stamp not in points
            or symbol not in settings.symbols
            or (stamp, symbol) in seen
            or stamp < previous
            or row.get("direction") not in (None, "long")
        ):
            raise RunnerFailure("RQAlpha 逐日持仓日期、标的或方向无效")
        previous = stamp
        seen.add((stamp, symbol))
        quantity = number(row.get("quantity"), 0, 1e12)
        price = number(row.get("last_price"), 0, 1e9)
        value = number(row.get("market_value"), 0, 1e15)
        dividend = number(row.get("dividend_receivable"), 0, 1e15)
        if quantity == 0 and dividend == 0:
            raise RunnerFailure("RQAlpha 空持仓没有应收权益")
        if abs(quantity * price - value) > max(0.02, quantity * 0.00005 + 0.00005):
            raise RunnerFailure("RQAlpha 持仓估值不闭合")
        totals[stamp] += value
        receivables[stamp] += dividend
        normalized_positions.append(
            {
                "time": stamp,
                "symbol": symbol,
                "name": text(row.get("name"), optional=True),
                "direction": row.get("direction"),
                "quantity": quantity,
                "last_price": price,
                "avg_price": number(row.get("avg_price"), 0, 1e9, optional=True),
                "market_value": value,
                "dividend_receivable": dividend,
                "pnl": number(row.get("pnl"), -1e15, 1e15, optional=True),
                "fee": number(row.get("fee"), 0, 1e15, optional=True),
                "sellable": number(row.get("sellable"), 0, quantity, optional=True),
            }
        )
    if any(abs(totals[stamp] - points[stamp]["market_value"]) > 0.02 for stamp in stamps):
        raise RunnerFailure("RQAlpha 每日持仓市值与账户不一致")
    normalized_accounts = []
    if [row.get("time") for row in accounts] != stamps:
        raise RunnerFailure("RQAlpha 账户明细未覆盖完整交易日历")
    for row in accounts:
        if row.get("account_type") != "stock" or row.get("margin") is not None:
            raise RunnerFailure("RQAlpha 首版报告只支持股票账户")
        stamp = row["time"]
        cash = number(row.get("cash"), -0.02, 1e15)
        equity = number(row.get("equity"), 0, 1e15)
        value = number(row.get("market_value"), 0, 1e15)
        point = points[stamp]
        components = equity_components(row)
        if (
            any(
                abs(actual - point[key]) > 0.02
                for actual, key in ((cash, "cash"), (value, "market_value"), (equity, "equity"))
            )
            or any(abs(components[key] - point[key]) > 0.02 for key in EQUITY_FIELDS)
            or abs(receivables[stamp] - components["dividend_receivable"]) > 0.02
        ):
            raise RunnerFailure("RQAlpha 账户明细与原生权益不一致")
        normalized_accounts.append(
            {
                **components,
                "time": stamp,
                "account_type": "stock",
                "cash": cash,
                "equity": equity,
                "market_value": value,
                "margin": None,
                "fee": number(row.get("fee"), 0, 1e15),
                "daily_pnl": number(row.get("daily_pnl"), -1e15, 1e15, optional=True),
            }
        )
    if settings.benchmark:
        if [row.get("time") for row in benchmark] != stamps:
            raise RunnerFailure("RQAlpha 基准未覆盖完整交易日历")
    elif benchmark:
        raise RunnerFailure("未配置基准却返回基准数据")
    normalized_benchmark = [
        {"time": row["time"], "net_value": number(row.get("net_value"), 1e-12, 1e12)}
        for row in benchmark
    ]
    normalized_logs = validate_logs(logs, truncated=raw.get("logs_truncated"))
    return {
        "positions": normalized_positions,
        "accounts": normalized_accounts,
        "benchmark": normalized_benchmark,
        "logs": normalized_logs,
        "logs_truncated": raw["logs_truncated"],
        "risk_free_rate": number(raw.get("risk_free_rate"), -1, 10, optional=True),
    }


def _date(stamp):
    return datetime.fromtimestamp(stamp, CHINA).date()


def period_returns(series, period, *, benchmark=False):
    final, prior = {}, 1.0
    for point in series:
        day = _date(point["time"])
        key = (
            day.year
            if period == "year"
            else (day.year, (day.month - 1) // 3 if period == "quarter" else day.month)
        )
        value = 1 + point["benchmark_return"] if benchmark else point["net_value"]
        final[key] = value
    returns = {}
    for key, value in final.items():
        returns[key] = value / prior - 1 if prior > 0 else None
        prior = value
    return returns


def _annual(series, market):
    strategy = period_returns(series, "year")
    benchmark = (
        period_returns(series, "year", benchmark=True)
        if series[0]["benchmark_return"] is not None
        else {}
    )
    days = defaultdict(list)
    for point in series:
        days[_date(point["time"]).year].append(point["time"])
    rows = []
    for year, stamps in days.items():
        partial = year not in market.get("full_years", [])
        rows.append(
            {
                "year": year,
                "start": stamps[0],
                "end": stamps[-1],
                "partial": partial,
                "strategy": strategy[year],
                "benchmark": benchmark.get(year),
            }
        )
    return rows


def _drawdown(series):
    peak, peak_time, maximum, interval = 1.0, series[0]["time"], 0.0, None
    for point in series:
        value = point["net_value"]
        if value >= peak:
            peak, peak_time = value, point["time"]
        depth = 1 - value / peak if peak > 0 else 0
        if depth > maximum:
            maximum = depth
            interval = {"start": peak_time, "end": point["time"], "value": depth}
    return interval


def _metrics(result, series, has_benchmark):
    native = result["native_metrics"]
    definitions = [
        ("total_returns", "回测收益", "percent", "原生单位净值减1，剔除申赎份额变化。", False),
        (
            "annualized_returns",
            "回测年化收益",
            "percent",
            "原生交易日年化，252个交易日为一年。",
            False,
        ),
        (
            "benchmark_total_returns",
            "基准收益",
            "percent",
            "冻结指数以前一交易日收盘为基期的累计收益。",
            True,
        ),
        (
            "benchmark_annualized_returns",
            "基准年化收益",
            "percent",
            "原生基准收益按252个交易日年化。",
            True,
        ),
        ("unit_net_value", "累计净值", "number", "原生份额单位净值，初始为1。", False),
        (
            "excess_max_drawdown",
            "超额收益最大回撤率",
            "percent",
            "策略净值/基准净值之比相对其历史峰值的最大跌幅，不是收益差曲线的回撤。",
            True,
        ),
    ]
    risks = [
        ("alpha", "阿尔法", "number", "原生CAPM年化阿尔法，使用冻结收益率曲线的无风险利率。", True),
        ("beta", "贝塔", "number", "策略与基准日收益协方差除以基准方差。", True),
        ("sharpe", "夏普率", "number", "原生日频超额无风险收益与波动率之比，按252日年化。", False),
        ("sortino", "索提诺比率", "number", "原生按无风险利率和下行风险计算的年化比率。", False),
        (
            "information_ratio",
            "信息比率",
            "number",
            "原生策略与基准日收益差的年化收益风险比。",
            True,
        ),
        ("volatility", "年化波动率", "percent", "原生日收益样本标准差乘以252的平方根。", False),
        (
            "max_drawdown",
            "最大回撤",
            "percent",
            "原生单位净值相对历史峰值的最大跌幅，包括初始净值1。",
            False,
        ),
        (
            "tracking_error",
            "年化跟踪误差",
            "percent",
            "原生策略与基准日收益差的样本标准差按252日年化。",
            True,
        ),
        (
            "downside_risk",
            "年化下行波动率",
            "percent",
            "原生相对无风险收益的下行偏差按252日年化。",
            False,
        ),
    ]
    daily = []
    previous = 1.0
    for point in series:
        daily.append(point["net_value"] / previous - 1 if previous > 0 else None)
        previous = point["net_value"]
    finite_daily = [value for value in daily if value is not None]
    flat = len(set(finite_daily)) <= 1
    rows = []

    def add(key, label, form, definition, needs_benchmark, risk=False):
        value = native.get(key)
        reason = None
        if needs_benchmark and not has_benchmark:
            value, reason = None, "未配置可核验的基准指数"
        elif risk and key != "max_drawdown" and len(series) < 2:
            value, reason = None, "不足两个交易日"
        elif flat and key == "sharpe":
            value, reason = None, "收益波动为零，比率不可计算"
        elif key == "sortino" and native.get("downside_risk") == 0:
            value, reason = None, "下行风险为零，比率不可计算"
        elif value is None:
            reason = "原生引擎未产出有限值，可能因样本或分母不足"
        rows.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "format": form,
                "precision": 3 if form == "percent" else 4,
                "definition": definition,
                "source": f"RQAlpha 6.5.0 summary.{key}",
                "reason": reason,
            }
        )

    for item in definitions:
        add(*item)
    for period, label in (("year", "年胜率"), ("quarter", "季度胜率"), ("month", "月胜率")):
        values = list(period_returns(series, period).values())
        value = (
            sum(item > 0 for item in values) / len(values)
            if values and None not in values
            else None
        )
        rows.append(
            {
                "key": f"{period}_win_rate",
                "label": label,
                "value": value,
                "format": "percent",
                "precision": 2,
                "definition": (
                    "平台口径：自然期间单位净值复利收益大于0的期间占比，"
                    "含实际覆盖的首尾部分期间；不是交易胜率或超额胜率。"
                ),
                "source": "平台从原生单位净值按自然期间派生",
                "reason": None if value is not None else "期间期初净值非正",
            }
        )
    add(
        "win_rate",
        "日胜率",
        "percent",
        "原生正收益交易日占比；零收益日也计入分母，不是跑赢基准日占比。",
        False,
    )
    for item in risks:
        add(*item, risk=True)
    return rows


def build_report(result, settings, market, raw):
    rows = validate_raw(raw, result, settings, market)
    benchmark = {row["time"]: row["net_value"] for row in rows["benchmark"]}
    account = {row["time"]: row for row in rows["accounts"]}
    trades_by_day = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
    fees_by_day = defaultdict(float)
    for trade in result["trades"]:
        day = _date(trade["time"])
        trades_by_day[day][trade["side"]] += trade["quantity"] * trade["price"]
        fees_by_day[day] += trade["fee"]
    for row in rows["accounts"]:
        if abs(fees_by_day[_date(row["time"])] - row["fee"]) > 0.02:
            raise RunnerFailure("RQAlpha 每日账户费用与成交费用不一致")
    series = []
    for point in result["equity"]:
        nav = number(point.get("net_value"), 0, 1e12)
        day, stamp = _date(point["time"]), point["time"]
        daily_pnl = number(point.get("daily_pnl"), -1e15, 1e15, optional=True)
        if daily_pnl is None:
            daily_pnl = account[stamp]["daily_pnl"]
        if daily_pnl is None:
            raise RunnerFailure("RQAlpha 未记录完整每日盈亏")
        if (
            account[stamp]["daily_pnl"] is not None
            and abs(daily_pnl - account[stamp]["daily_pnl"]) > 0.02
        ):
            raise RunnerFailure("RQAlpha 每日盈亏与股票账户不一致")
        series.append(
            {
                "time": stamp,
                "equity": point["equity"],
                "net_value": nav,
                "strategy_return": nav - 1,
                "benchmark_return": benchmark[stamp] - 1 if benchmark else None,
                "excess_return": nav - benchmark[stamp] if benchmark else None,
                "daily_pnl": daily_pnl,
                "buy_amount": trades_by_day[day]["buy"],
                "sell_amount": trades_by_day[day]["sell"],
            }
        )
    expected_metrics = {
        "unit_net_value": series[-1]["net_value"],
        "total_returns": series[-1]["strategy_return"],
    }
    if benchmark:
        expected_metrics["benchmark_total_returns"] = series[-1]["benchmark_return"]
    for key, expected in expected_metrics.items():
        actual = result["native_metrics"].get(key)
        if actual is not None:
            observed = (
                round(actual + 1, 6) - 1
                if key == "total_returns"
                else (round(actual, 6) if key == "unit_net_value" else actual)
            )
            if not math.isclose(observed, expected, rel_tol=1e-10, abs_tol=1e-10):
                raise RunnerFailure("RQAlpha 原生汇总与净值序列不一致")
    report_rows = {
        "trades": result["trades"],
        "positions": rows["positions"],
        "accounts": rows["accounts"],
        "logs": rows["logs"],
    }
    report = {
        "schema_version": SCHEMA,
        "benchmark": {"symbol": settings.benchmark, "name": BENCHMARKS[settings.benchmark]}
        if settings.benchmark
        else None,
        "conventions": {
            "timezone": "Asia/Shanghai",
            "trading_days_per_year": 252,
            "risk_free_rate": rows["risk_free_rate"],
            "risk_free_source": "RQAlpha 冻结 yield_curve 按回测起止期限取值；null表示未记录",
            "period_win_rate": "正收益期间占比，含首尾部分期间；非超额胜率",
            "excess_curve": "算术收益差：策略单位净值减基准单位净值",
            "excess_drawdown": "几何超额：策略单位净值/基准单位净值之比的最大回撤",
            "pnl": "原生每日盈亏；持仓pnl为当前持仓浮盈亏，非累计已实现盈亏",
            "position_snapshot": (
                "持仓估值/浮盈亏/费用/应收分红与账户每日盈亏在结算后、账户重置前原生采集；"
                "可卖量为结算前after_trading后快照，数量不匹配则未记录"
            ),
            "equity_closure": (
                "可用现金+冻结资金+市值+应收分红+待到账申赎-现金负债-负债利息=总权益；"
                "各项原生采集，不用残差填平"
            ),
            "native_precision": (
                "原生分析器日单位净值保留6位小数；图表/年度据此派生，"
                "原生指标保留原始精度；证券估值价4位小数，闭合按字段精度核对"
            ),
            "security_names": "冻结原生数据包证券名称，不承诺历史时点名称",
            "stock_margin": "股票账户不适用保证金，不表示支持期货或融资融券",
        },
        "metrics": _metrics(result, series, bool(benchmark)),
        "series": series,
        "annual_returns": _annual(series, market),
        "drawdown": _drawdown(series),
        "tables": {
            name: {"count": len(values), "recorded": True} for name, values in report_rows.items()
        },
        "logs_truncated": rows["logs_truncated"],
        "performance": {"enabled": False},
    }
    return {"report": report, "report_rows": report_rows}
