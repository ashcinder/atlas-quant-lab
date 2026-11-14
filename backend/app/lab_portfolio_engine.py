"""Deterministic A-share portfolio simulation. User Python supplies proposals only."""

from collections import deque
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from zoneinfo import ZoneInfo

from app.execution import parameter_values
from app.sandbox import PORTFOLIO_PROTOCOL, PortfolioSandbox, RunnerFailure, portfolio_runner_status

__all__ = ["PortfolioEngine", "PortfolioSandbox", "portfolio_runner_status", "run_portfolio_backtest"]
from app.strategy_studio import inspect_strategy_package

SHANGHAI = ZoneInfo("Asia/Shanghai")
MICROS = 1_000_000
HISTORY_BARS = 128
MAX_EVENTS = 20_000
MAX_RECORDS = 50_000
ENGINE_VERSION = "a-share-portfolio/v1"


def _decimal(value):
    return Decimal(str(value))


def _number(value, label, minimum=0, maximum=1_000_000_000):
    if type(value) not in (int, float, Decimal) or (type(value) is not int and not isfinite(value)) or not minimum <= value <= maximum:
        raise RunnerFailure(f"{label} 无效")
    return _decimal(value)


def _integer(value, label, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise RunnerFailure(f"{label} 必须为有效整数")
    return value


def _micros(value):
    return int((_decimal(value) * MICROS).to_integral_value(rounding=ROUND_HALF_UP))


def _rounded(value):
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _session(timestamp):
    return datetime.fromtimestamp(timestamp, SHANGHAI)


def _symbol_list(value, allowed, label):
    if not isinstance(value, (list, tuple)) or any(type(symbol) is not str or symbol not in allowed for symbol in value):
        raise RunnerFailure(f"{label}包含无效标的")
    if len(set(value)) != len(value):
        raise RunnerFailure(f"{label}存在重复标的")
    return set(value)


def _ohlcv(symbol, row):
    bar = {key: float(_number(row.get(key), f"{symbol} {key}", 0.000001)) for key in ("open", "high", "low", "close")}
    if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
        raise RunnerFailure(f"{symbol} OHLC 价格关系无效")
    bar["volume"] = float(_number(row.get("volume"), f"{symbol} 成交量", maximum=10**12))
    return bar


def _daily(symbol, row):
    if not isinstance(row, dict):
        raise RunnerFailure(f"{symbol} 日线无效")
    daily = _ohlcv(symbol, row)
    for key in ("reference", "limit_up", "limit_down", "adjustment_ratio"):
        if key in row:
            daily[key] = None if row[key] is None else float(_number(row[key], f"{symbol} 日线 {key}", 0.000001))
    if "amount" in row:
        daily["amount"] = float(_number(row["amount"], f"{symbol} 日成交额", maximum=10**12))
    return daily


def _bar(symbol, row, timestamp, open_default):
    if not isinstance(row, dict):
        raise RunnerFailure(f"{symbol} 缺少完整行情")
    bar = _ohlcv(symbol, row)
    bar["lot_size"] = _integer(row.get("lot_size"), f"{symbol} 买入起始手数", 1, 100_000)
    bar["lot_step"] = _integer(row.get("lot_step", bar["lot_size"]), f"{symbol} 买入递增股数", 1, 100_000)
    upper, lower = row.get("limit_up"), row.get("limit_down")
    if "limit_up" not in row or "limit_down" not in row or (upper is None) != (lower is None):
        raise RunnerFailure(f"{symbol} 缺少经确认的涨跌停规则")
    if upper is not None:
        upper = float(_number(upper, f"{symbol} 涨停价", 0.000001))
        lower = float(_number(lower, f"{symbol} 跌停价", 0.000001))
        if not lower < upper or bar["low"] < lower or bar["high"] > upper:
            raise RunnerFailure(f"{symbol} 行情与涨跌停规则不一致")
    open_time = _integer(row.get("open_time", open_default), f"{symbol} 开盘时间", 1, timestamp - 1)
    if _session(open_time).date() != _session(timestamp).date():
        raise RunnerFailure(f"{symbol} 开盘和收盘不在同一交易日")
    bar.update(time=timestamp, open_time=open_time, limit_up=upper, limit_down=lower)
    for key in ("reference", "research_close"):
        if row.get(key) is not None:
            bar[key] = float(_number(row[key], f"{symbol} {key}", 0.000001))
    bar["split_ratio"] = float(_number(row.get("split_ratio", 1), f"{symbol} 送转比例", 0.000001, 100))
    bar["cash_dividend"] = float(_number(row.get("cash_dividend", 0), f"{symbol} 每股分红"))
    if row.get("sell_tax_rate") is not None:
        bar["sell_tax_rate"] = float(_number(row["sell_tax_rate"], f"{symbol} 卖出税率", maximum=0.1))
    if row.get("daily") is not None:
        if _session(timestamp).time() != time(15):
            raise RunnerFailure(f"{symbol} 仅可在当日收盘时提供已收盘日线")
        bar["daily"] = _daily(symbol, row["daily"])
    if type(row.get("touch_evidence", False)) is not bool:
        raise RunnerFailure(f"{symbol} 触板标记无效")
    bar["touch_evidence"] = row.get("touch_evidence", False)
    return bar


def _proposals(response, eligible, positions, max_position):
    if not isinstance(response, dict) or ("targets" in response) == ("orders" in response):
        raise RunnerFailure("策略必须返回目标仓位或订单意图其中一种")
    targets = "targets" in response
    mode = "targets" if targets else "orders"
    rows = response[mode]
    if not isinstance(rows, list) or len(rows) > 300:
        raise RunnerFailure("策略返回了无效意图或超过 300 条")
    seen = set()
    total = Decimal(0)
    proposals = []
    for index, row in enumerate(rows):
        symbol = row.get("symbol") if isinstance(row, dict) else None
        if type(symbol) is not str or (symbol not in eligible and symbol not in positions):
            raise RunnerFailure(f"第 {index + 1} 条意图引用股票池外标的")
        reason = row.get("reason_code", "strategy")
        if type(reason) is not str or not 1 <= len(reason) <= 80 or any(not c.isprintable() for c in reason):
            raise RunnerFailure(f"第 {index + 1} 条意图原因无效")
        allowed_fields = {"symbol", "reason_code", "target_weight"} if targets else {"symbol", "reason_code", "side", "quantity"}
        if row.keys() - allowed_fields:
            raise RunnerFailure(f"第 {index + 1} 条意图包含未支持字段")
        proposal = {"index": index, "symbol": symbol, "reason_code": reason}
        if targets:
            weight = _number(row.get("target_weight"), f"{symbol} 目标仓位", maximum=max_position)
            if symbol in seen or (symbol not in eligible and weight):
                raise RunnerFailure(f"{symbol} 重复声明目标仓位或对池外持仓增加仓位")
            seen.add(symbol)
            total += weight
            proposal["target_weight"] = float(weight)
        else:
            side = row.get("side")
            if side not in ("buy", "sell") or (side == "buy" and symbol not in eligible):
                raise RunnerFailure(f"{symbol} 买卖方向无效或试图买入池外标的")
            quantity = _number(row.get("quantity"), f"{symbol} 委托股数", 1, 10**9)
            if quantity != int(quantity):
                raise RunnerFailure(f"{symbol} 委托必须为整数股")
            proposal.update(side=side, quantity=int(quantity))
        proposals.append(proposal)
    if total > Decimal("1.0000000001"):
        raise RunnerFailure("目标仓位合计超过 100%")
    return proposals


def _lot_quantity(quantity, minimum, increment):
    return minimum + (quantity - minimum) // increment * increment if quantity >= minimum else 0


class PortfolioEngine:
    """One cash account. Persist snapshots only after successful complete events."""

    def __init__(self, settings, state=None):
        self.symbols = tuple(settings["symbols"])
        if not 2 <= len(self.symbols) <= 150 or len(set(self.symbols)) != len(self.symbols):
            raise RunnerFailure("股票池需要 2–150 个不同标的")
        self.universe = frozenset(self.symbols)
        self.initial = _micros(_number(settings["initial_capital"], "初始资金", 0, 10**12))
        if self.initial <= 0:
            raise RunnerFailure("初始资金小于账户精度")
        self.commission = _number(settings.get("commission_rate", 0.001), "手续费", maximum=0.1)
        self.slippage = _number(settings.get("slippage_rate", 0.0005), "滑点", maximum=0.1)
        self.sell_tax = _number(settings.get("sell_tax_rate", 0.0005), "卖出税率", maximum=0.1)
        self.max_position = _number(settings.get("max_position", 0.95), "单股仓位", 0, 1)
        self.participation = _number(settings.get("max_participation_rate", 0.01), "成交参与率", 0, 1)
        if not self.max_position or not self.participation:
            raise RunnerFailure("单股仓位与成交参与率必须大于零")
        self.interval = settings.get("interval", "1d")
        if self.interval not in ("1d", "15m"):
            raise RunnerFailure("A 股多标的支持日线和 15 分钟")
        self.run_id = settings.get("run_id", "portfolio")
        state = state or {}
        self.time = state.get("time", 0)
        self.cash = state.get("cash", self.initial)
        self.peak = state.get("peak", self.initial)
        self.holdings = {symbol: tuple(row) for symbol, row in state.get("holdings", {}).items()}
        self.basis = dict(state.get("basis", {}))
        self.pending = list(state.get("pending", []))
        self.marks = dict(state.get("marks", {}))
        self._history = {symbol: deque(rows, maxlen=HISTORY_BARS) for symbol, rows in state.get("history", {}).items()}
        self.strategy_state = state.get("strategy_state")

    def snapshot(self):
        return {
            "time": self.time, "cash": self.cash, "peak": self.peak,
            "holdings": {symbol: list(row) for symbol, row in self.holdings.items()},
            "pending": list(self.pending), "marks": dict(self.marks), "basis": dict(self.basis),
            "history": self.history(), "strategy_state": self.strategy_state,
        }

    def history(self):
        return {symbol: list(rows) for symbol, rows in self._history.items()}

    def step(self, event, strategy_callback, *, allow_fills=True):
        if strategy_callback is None and allow_fills:
            raise RunnerFailure("仅禁止撮合的观察事件可以不执行策略")
        timestamp = _integer(event.get("time"), "行情事件时间", self.time + 1, 4_102_444_799)
        session = _session(timestamp)
        day = session.date().isoformat()
        new_day = not self.time or _session(self.time).date() != session.date()
        ranked_symbols = event.get("eligible", self.symbols)
        eligible = _symbol_list(ranked_symbols, self.universe, "可买股票池")
        suspended = _symbol_list(event.get("suspended", []), self.universe, "明确停牌列表")
        raw = event.get("bars")
        if not isinstance(raw, dict) or raw.keys() - self.universe or raw.keys() & suspended:
            raise RunnerFailure("行情事件包含池外标的或停牌标的同时有成交行情")
        pending = self.pending if allow_fills else []
        missing = (eligible | self.holdings.keys() | {item["symbol"] for item in pending}) - raw.keys() - suspended
        if missing:
            raise RunnerFailure(f"行情事件缺少标的且无停牌依据: {', '.join(sorted(missing))}")
        default_open = int(session.replace(hour=9, minute=30, second=0, microsecond=0).timestamp()) if self.interval == "1d" else timestamp - 900
        bars = {symbol: _bar(symbol, row, timestamp, default_open) for symbol, row in sorted(raw.items())}
        if allow_fills and any(bar["open_time"] < self.time for bar in bars.values()):
            raise RunnerFailure("本期行情开盘早于前一根收盘，无法按因果顺序撮合")
        if len({bar["open_time"] for bar in bars.values()}) > 1:
            raise RunnerFailure("同一事件的标的开盘时点不一致")
        daily_raw = event.get("daily", {})
        if not isinstance(daily_raw, dict) or daily_raw.keys() - self.universe or (daily_raw and session.time() != time(15)):
            raise RunnerFailure("日线补充行情只能在交易日收盘时提供")
        daily = {symbol: _daily(symbol, row) for symbol, row in sorted(daily_raw.items())}

        holdings = {symbol: (sum(row), 0) if new_day else row for symbol, row in self.holdings.items()}
        unresolved = _symbol_list(event.get("unresolved_actions", []), self.universe, "未核实的公司行动")
        affected = unresolved & holdings.keys()
        if affected:
            raise RunnerFailure(f"持仓缺少已核实的公司行动结算条款: {', '.join(sorted(affected))}")
        if unresolved & {order["symbol"] for order in pending}:
            raise RunnerFailure("待成交标的缺少已核实的公司行动结算条款")
        basis = dict(self.basis)
        cash, marks, actions = self._corporate_actions(bars, holdings, self.cash, new_day, event.get("corporate_actions", {}))
        open_prices = {**marks, **{symbol: _micros(bar["open"]) for symbol, bar in bars.items()}}
        cash, fills, rejections = self._match(pending, eligible, bars, open_prices, holdings, basis, cash)
        marks.update({symbol: _micros(bar["close"]) for symbol, bar in bars.items()})
        equity = cash + sum(sum(row) * marks[symbol] for symbol, row in holdings.items())
        if equity <= 0:
            raise RunnerFailure("账户权益不足以继续模拟")
        peak = max(self.peak, equity)
        weights = {symbol: sum(row) * marks[symbol] / equity for symbol, row in holdings.items()}
        payload = {
            "kind": "portfolio_step", "run_id": self.run_id, "time": timestamp, "session_date": day,
            "bars": bars, "symbols": list(ranked_symbols), "suspended": sorted(suspended),
            "daily": daily,
            "cash": cash / MICROS, "equity": equity / MICROS, "drawdown": equity / peak - 1,
            "positions": {symbol: sum(row) for symbol, row in holdings.items()}, "weights": weights,
            "sellable": {symbol: row[0] for symbol, row in holdings.items()}, "fills": fills,
        }
        response = strategy_callback(payload) if strategy_callback is not None else None
        proposals = _proposals(response, eligible, holdings, self.max_position) if strategy_callback is not None else []
        self.time, self.cash, self.peak = timestamp, cash, peak
        self.holdings, self.marks, self.basis = holdings, marks, basis
        self.pending = proposals
        if response is not None:
            self.strategy_state = response.get("checkpoint")
        for symbol, bar in bars.items():
            self._history.setdefault(symbol, deque(maxlen=HISTORY_BARS)).append(bar)
        return {
            "time": timestamp, "equity": equity / MICROS, "cash": cash / MICROS,
            "drawdown": equity / peak - 1, "trades": fills, "rejections": rejections,
            "corporate_actions": actions, "pending_count": len(proposals),
            "positions": [
                {"symbol": symbol, "quantity": sum(row), "sellable": row[0], "weight": weights[symbol],
                 "mark_price": marks[symbol] / MICROS, "market_value": sum(row) * marks[symbol] / MICROS,
                 "average_cost": basis[symbol] / (sum(row) * MICROS) if symbol in basis else None,
                 "unrealized_pnl": (sum(row) * marks[symbol] - basis[symbol]) / MICROS if symbol in basis else None}
                for symbol, row in sorted(holdings.items())
            ],
        }

    def _corporate_actions(self, bars, holdings, cash, new_day, supplied):
        if not isinstance(supplied, dict) or supplied.keys() - self.universe:
            raise RunnerFailure("公司行动引用无效标的")
        marks = dict(self.marks)
        actions = []
        entries = {symbol: (bar["split_ratio"], bar["cash_dividend"]) for symbol, bar in bars.items()}
        for symbol, action in supplied.items():
            if not isinstance(action, dict):
                raise RunnerFailure(f"{symbol} 公司行动无效")
            if entries.get(symbol, (1, 0)) != (1, 0):
                raise RunnerFailure(f"{symbol} 公司行动重复")
            entries[symbol] = (
                _number(action.get("split_ratio", 1), f"{symbol} 送转比例", 0.000001, 100),
                _number(action.get("cash_dividend", 0), f"{symbol} 每股分红"),
            )
        for symbol, (ratio, dividend) in sorted(entries.items()):
            if ratio == 1 and dividend == 0:
                continue
            if not new_day:
                raise RunnerFailure(f"{symbol} 公司行动必须在交易日第一根行情前应用")
            if symbol not in holdings:
                continue
            quantity = sum(holdings[symbol])
            adjusted = _decimal(ratio) * quantity
            if adjusted != int(adjusted):
                raise RunnerFailure(f"{symbol} 公司行动产生零碎股，缺少零碎股结算数据")
            dividend_cash = _micros(_decimal(dividend) * quantity)
            cash += dividend_cash
            holdings[symbol] = (int(adjusted), 0)
            if symbol in marks:
                marks[symbol] = _rounded((Decimal(marks[symbol]) - _micros(dividend)) / _decimal(ratio))
                if marks[symbol] <= 0:
                    raise RunnerFailure(f"{symbol} 除权参考价无效")
            actions.append({"symbol": symbol, "shares_before": quantity, "shares_after": int(adjusted), "cash_dividend": dividend_cash / MICROS})
        return cash, marks, actions

    def _match(self, pending, eligible, bars, prices, holdings, basis, cash):
        fills, rejections = [], []
        equity_open = cash + sum(sum(row) * prices[symbol] for symbol, row in holdings.items())
        wanted = []
        for proposal in pending:
            symbol = proposal["symbol"]
            if "target_weight" not in proposal:
                wanted.append(proposal)
                continue
            mark = prices.get(symbol)
            held = sum(holdings.get(symbol, (0, 0)))
            if not mark:
                rejections.append(self._rejection(proposal, None, 0, "缺少可交易开盘价"))
                continue
            target = int(_decimal(proposal["target_weight"]) * equity_open / mark)
            delta = target - held
            if delta:
                wanted.append({**proposal, "side": "buy" if delta > 0 else "sell", "quantity": abs(delta)})
        # Stable within each direction, with sale proceeds available for simultaneous buys.
        wanted.sort(key=lambda order: order["side"] == "buy")
        available_volume = {}
        for order in wanted:
            symbol, side, requested = order["symbol"], order["side"], order["quantity"]
            bar = bars.get(symbol)
            buying = side == "buy"
            if not bar or (buying and symbol not in eligible):
                rejections.append(self._rejection(order, bar, 0, "停牌或移出股票池"))
                continue
            if not bar["volume"]:
                rejections.append(self._rejection(order, bar, 0, "当根行情无成交"))
                continue
            raw_open = prices[symbol]
            limit = bar["limit_up"] if buying else bar["limit_down"]
            price_limit = _micros(limit) if limit is not None else None
            if price_limit is not None and ((buying and raw_open >= price_limit) or (not buying and raw_open <= price_limit)):
                rejections.append(self._rejection(order, bar, 0, "开盘触及涨跌停"))
                continue
            price = _rounded(Decimal(raw_open) * (1 + self.slippage if buying else 1 - self.slippage))
            if price_limit is not None:
                price = min(price_limit, price) if buying else max(price_limit, price)
            tax_rate = Decimal(0) if buying else _decimal(bar.get("sell_tax_rate", self.sell_tax))
            if symbol not in available_volume:
                history = self._history.get(symbol)
                past_volume = history[-1]["volume"] if history and history[-1]["time"] == self.time else 0
                available_volume[symbol] = int(_decimal(past_volume) * self.participation)
            volume = available_volume[symbol]
            quantity = min(requested, volume)
            reason = "成交参与率限制" if quantity < requested else "委托数量不足一手"
            settled, today = holdings.get(symbol, (0, 0))
            if buying:
                unit_cost = Decimal(price) * (1 + self.commission)
                equity_open = cash + sum(sum(row) * prices[held] for held, row in holdings.items())
                risk_budget = self.max_position * equity_open - (settled + today) * raw_open
                risk_unit = Decimal(raw_open) + self.max_position * (unit_cost - raw_open)
                risk_quantity = max(0, int(risk_budget / risk_unit))
                affordable = int(cash / unit_cost)
                if min(risk_quantity, affordable) < quantity:
                    reason = "单股仓位上限" if risk_quantity < affordable else "可用现金不足"
                quantity = _lot_quantity(min(quantity, affordable, risk_quantity), bar["lot_size"], bar["lot_step"])
            else:
                if settled < quantity:
                    reason = "T+1 或持仓可卖数量不足"
                quantity = min(quantity, settled)
                if quantity != settled:
                    quantity = _lot_quantity(quantity, bar["lot_size"], bar["lot_step"])
            if quantity:
                notional = quantity * price
                commission = _rounded(Decimal(notional) * self.commission)
                tax = _rounded(Decimal(notional) * tax_rate)
                fee = commission + tax
                realized_pnl = None
                if buying:
                    cash -= notional + fee
                    holdings[symbol] = (settled, today + quantity)
                    if settled + today == 0 or symbol in basis:
                        basis[symbol] = basis.get(symbol, 0) + notional + fee
                else:
                    cash += notional - fee
                    if symbol in basis:
                        released_basis = _rounded(Decimal(basis[symbol]) * quantity / (settled + today))
                        basis[symbol] -= released_basis
                        realized_pnl = (notional - fee - released_basis) / MICROS
                    if settled + today == quantity:
                        holdings.pop(symbol, None)
                        basis.pop(symbol, None)
                    else:
                        holdings[symbol] = (settled - quantity, today)
                available_volume[symbol] -= quantity
                fills.append({
                    "id": f"{self.time}:{order['index']}", "time": bar["open_time"], "decision_time": self.time,
                    "symbol": symbol, "side": side, "quantity": quantity, "price": price / MICROS,
                    "raw_open": raw_open / MICROS, "fee": fee / MICROS, "commission": commission / MICROS,
                    "tax": tax / MICROS, "slippage": quantity * abs(price - raw_open) / MICROS,
                    "cash_after": cash / MICROS, "reason_code": order["reason_code"], "realized_pnl": realized_pnl,
                })
            if quantity < requested:
                rejections.append(self._rejection(order, bar, quantity, reason))
        return cash, fills, rejections

    def _rejection(self, order, bar, filled, reason):
        return {
            "id": f"{self.time}:{order['index']}", "decision_time": self.time,
            "time": bar["open_time"] if bar else None, "symbol": order["symbol"], "side": order.get("side"),
            "requested": order.get("quantity"), "filled": filled, "reason": reason,
        }


def run_portfolio_backtest(
    archive, events, settings, parameters=None, *, cancelled=None, progress=None, sandbox_factory=PortfolioSandbox,
):
    inspection = inspect_strategy_package(archive)
    if settings.get("interval", "1d") not in inspection.manifest.intervals:
        raise RunnerFailure("策略包未声明所选 K 线周期")
    values = parameter_values(inspection.manifest, parameters or {})
    engine = PortfolioEngine(settings)
    trades, equity, rejections, actions = [], [], [], []
    count = len(events) if hasattr(events, "__len__") else None
    if count is not None and not 2 <= count <= MAX_EVENTS:
        raise RunnerFailure("回测需要 2–20,000 个行情事件")
    with sandbox_factory(archive, values, save_state=False, cancelled=cancelled) as sandbox:
        for index, event in enumerate(events):
            if cancelled is not None and cancelled():
                raise RunnerFailure("回测已取消")
            if index >= MAX_EVENTS:
                raise RunnerFailure("回测超过 20,000 个行情事件")
            point = engine.step(event, sandbox.exchange)
            trades.extend(point["trades"])
            rejections.extend(point["rejections"])
            actions.extend({**action, "time": point["time"]} for action in point["corporate_actions"])
            if len(trades) + len(rejections) + len(actions) > MAX_RECORDS:
                raise RunnerFailure("回测交易及拒绝记录过多，请缩短区间")
            equity.append({key: point[key] for key in ("time", "equity", "cash", "drawdown")})
            if progress is not None and index % 32 == 0:
                progress(index + 1, count)
        if len(equity) < 2:
            raise RunnerFailure("回测至少需要两个行情事件")
        if progress is not None:
            progress(len(equity), count)
        image = getattr(sandbox, "image", None)
    initial = engine.initial / MICROS
    final_equity = equity[-1]["equity"]
    return {
        "kind": "multi_python", "engine_version": ENGINE_VERSION, "sdk_version": PORTFOLIO_PROTOCOL,
        "runner_image": image, "source_sha256": inspection.content_hash, "currency": "CNY",
        "proof_status": "unverified", "interval": engine.interval, "symbols": list(engine.symbols),
        "initial_capital": initial, "final_equity": final_equity, "total_return": final_equity / initial - 1,
        "max_drawdown": -min(row["drawdown"] for row in equity),
        "equity": equity, "trades": trades, "rejections": rejections,
        "corporate_actions": actions, "positions": point["positions"],
    }
