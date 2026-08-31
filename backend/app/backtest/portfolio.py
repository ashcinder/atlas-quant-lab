from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from app.backtest.metrics import calculate_metrics, drawdown_series, safe_float
from app.data.service import DataBundle
from app.models import (
    EquityPoint,
    PortfolioBacktestRequest,
    PortfolioResult,
    StrategyDefinition,
    Trade,
)
from app.strategies import get_strategy
from app.strategies.catalog import default_params


def _portfolio_frame(bundle: DataBundle, interval: str) -> pd.DataFrame:
    """Use a session-date key for daily/weekly bars across provider timezones."""
    frame = bundle.frame.copy()
    if interval not in {"1d", "1wk"}:
        return frame
    # Providers encode a session date as midnight in their local market timezone.
    # After conversion to UTC that same date can appear at 04:00 or at 16:00 on
    # the previous day. Rounding recovers the provider's intended session date.
    frame.index = pd.DatetimeIndex(frame.index).round("D")
    if frame.index.has_duplicates:
        frame = frame.groupby(level=0).last()
    return frame.sort_index()


def _normalized(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(value, 0) for value in values.values())
    if total <= 0:
        return {key: 1 / len(values) for key in values}
    return {key: max(value, 0) / total for key, value in values.items()}


def _constrained_weights(
    values: dict[str, float], cash_buffer: float, max_asset_weight: float
) -> dict[str, float]:
    """Normalize long-only weights, reserve cash, then apply a deterministic cap."""
    normalized = _normalized(values)
    target_total = 1 - cash_buffer
    remaining = target_total
    active = list(normalized)
    result = {symbol: 0.0 for symbol in normalized}
    while active:
        active_total = sum(normalized[symbol] for symbol in active)
        provisional = {
            symbol: remaining * normalized[symbol] / active_total
            if active_total > 0
            else remaining / len(active)
            for symbol in active
        }
        capped = [
            symbol for symbol, value in provisional.items() if value > max_asset_weight
        ]
        if not capped:
            result.update(provisional)
            break
        for symbol in capped:
            result[symbol] = max_asset_weight
            remaining -= max_asset_weight
            active.remove(symbol)
    return result


def _validated_params(
    strategy: StrategyDefinition, supplied: dict[str, object]
) -> dict[str, float | int | str | bool]:
    definitions = {parameter.key: parameter for parameter in strategy.parameters}
    unknown = sorted(set(supplied) - set(definitions))
    if unknown:
        raise ValueError(f"策略包含未知参数: {', '.join(unknown)}")
    validated = default_params(strategy.id)
    for key, raw in supplied.items():
        parameter = definitions[key]
        if parameter.kind == "boolean":
            if not isinstance(raw, bool):
                raise ValueError(f"{parameter.label} 必须为布尔值")
            value: float | int | str | bool = raw
        elif parameter.kind == "select":
            options = {option["value"] for option in parameter.options or []}
            if not isinstance(raw, str) or raw not in options:
                raise ValueError(f"{parameter.label} 不是有效选项")
            value = raw
        else:
            if isinstance(raw, bool):
                raise ValueError(f"{parameter.label} 必须为数字")
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{parameter.label} 必须为数字") from exc
            if not np.isfinite(numeric):
                raise ValueError(f"{parameter.label} 必须为有限数字")
            if parameter.minimum is not None and numeric < parameter.minimum:
                raise ValueError(f"{parameter.label} 不能小于 {parameter.minimum:g}")
            if parameter.maximum is not None and numeric > parameter.maximum:
                raise ValueError(f"{parameter.label} 不能大于 {parameter.maximum:g}")
            if parameter.kind == "integer":
                if not numeric.is_integer():
                    raise ValueError(f"{parameter.label} 必须为整数")
                value = int(numeric)
            else:
                value = numeric
        validated[key] = value
    return validated


def _fixed_weights(
    request: PortfolioBacktestRequest,
    bundles: list[DataBundle],
    params: dict[str, float | int | str | bool],
) -> dict[str, float]:
    supplied = {item.symbol: item.weight for item in request.assets if item.weight is not None}
    symbols = [bundle.asset.symbol for bundle in bundles]
    if request.strategy_id == "sixty_forty":
        equity_target = float(params.get("equity_target", 0.6))
        values = _normalized(
            {
                symbol: equity_target
                if i == 0
                else (1 - equity_target) / max(len(symbols) - 1, 1)
                for i, symbol in enumerate(symbols)
            }
        )
        return _constrained_weights(values, request.cash_buffer, request.max_asset_weight)
    if len(supplied) == len(request.assets):
        return _constrained_weights(
            {key: float(value) for key, value in supplied.items()},
            request.cash_buffer,
            request.max_asset_weight,
        )
    if request.strategy_id == "all_weather":
        # Positional defaults follow the conventional stock, long bond,
        # intermediate bond, gold and commodity input order.
        template = [0.30, 0.40, 0.15, 0.075, 0.075]
        if len(symbols) == 5:
            return _constrained_weights(
                dict(zip(symbols, template, strict=True)),
                request.cash_buffer,
                request.max_asset_weight,
            )
    return _constrained_weights(
        {symbol: 1 / len(symbols) for symbol in symbols},
        request.cash_buffer,
        request.max_asset_weight,
    )


def _risk_parity_weights(returns: pd.DataFrame, shrinkage: float = 0.1) -> dict[str, float]:
    clean = returns.dropna()
    n = len(clean.columns)
    if len(clean) < 30:
        return {column: 1 / n for column in clean.columns}
    sample_covariance = clean.cov().values * 252
    diagonal = np.diag(np.diag(sample_covariance))
    covariance = (1 - shrinkage) * sample_covariance + shrinkage * diagonal

    def objective(weights: np.ndarray) -> float:
        variance = float(weights @ covariance @ weights)
        volatility = np.sqrt(max(variance, 1e-16))
        marginal = covariance @ weights / volatility
        contribution = weights * marginal
        target = volatility / n
        return float(np.sum((contribution - target) ** 2))

    result = minimize(
        objective,
        np.repeat(1 / n, n),
        method="SLSQP",
        bounds=[(0.01, 1.0)] * n,
        constraints=[{"type": "eq", "fun": lambda weights: np.sum(weights) - 1}],
    )
    weights = result.x if result.success else np.repeat(1 / n, n)
    return {column: float(value) for column, value in zip(clean.columns, weights, strict=True)}


def _rebalance_mask(index: pd.DatetimeIndex, frequency: str) -> pd.Series:
    code = {"monthly": "M", "quarterly": "Q", "yearly": "Y"}[frequency]
    # PeriodIndex.shift changes the *period values* (Q1 -> Q2); it does not
    # compare adjacent rows.  Keep the labels in a Series so shift is
    # positional and only the first bar of each new period is selected.
    labels = pd.Series(index.tz_localize(None).to_period(code).astype(str), index=index)
    mask = labels.ne(labels.shift(1))
    mask.iloc[0] = True
    return mask


def run_portfolio_backtest(
    request: PortfolioBacktestRequest, bundles: list[DataBundle]
) -> PortfolioResult:
    strategy = get_strategy(request.strategy_id)
    params = _validated_params(strategy, request.params)
    aligned_frames = {
        bundle.asset.symbol: _portfolio_frame(bundle, request.interval) for bundle in bundles
    }
    close = pd.concat(
        {symbol: frame["close"] for symbol, frame in aligned_frames.items()},
        axis=1,
        join="inner",
    ).dropna()
    open_prices = (
        pd.concat(
            {symbol: frame["open"] for symbol, frame in aligned_frames.items()},
            axis=1,
            join="inner",
        )
        .reindex(close.index)
        .dropna()
    )
    close = close.reindex(open_prices.index)
    if len(close) < 60:
        raise ValueError(
            f"多资产组合对齐后仅有{len(close)}个共同K线周期，至少需要60个；"
            "请改用日线/周线、减少跨市场标的，或选择历史更长的数据源"
        )

    symbols = list(close.columns)
    cash = request.initial_capital
    units = {symbol: 0.0 for symbol in symbols}
    target_weights = _fixed_weights(request, bundles, params)
    trades: list[dict] = []
    equity_values: list[float] = []
    exposure_values: list[float] = []
    weight_history: list[dict] = []
    rebalance_mask = _rebalance_mask(close.index, request.rebalance)

    for i, timestamp in enumerate(close.index):
        open_row = open_prices.loc[timestamp]
        close_row = close.loc[timestamp]
        equity_at_open = cash + sum(units[symbol] * float(open_row[symbol]) for symbol in symbols)

        if i == 0 or bool(rebalance_mask.loc[timestamp]):
            history = close.iloc[:0]
            if request.strategy_id == "risk_parity" and i > 0:
                lookback = int(params.get("lookback", 126))
                shrinkage = float(params.get("covariance_shrinkage", 0.1))
                # Use closes known strictly before this open; this avoids
                # look-ahead while allowing the new weights to execute now.
                history = close.iloc[max(0, i - lookback) : i].pct_change().dropna()
                execution_weights = (
                    _constrained_weights(
                        _risk_parity_weights(history, shrinkage),
                        request.cash_buffer,
                        request.max_asset_weight,
                    )
                    if len(history) >= 30
                    else target_weights
                )
            else:
                execution_weights = target_weights

            if request.volatility_target is not None and i > 0:
                if history.empty:
                    history = close.iloc[max(0, i - 252) : i].pct_change().dropna()
                if len(history) >= 30:
                    covariance = history.cov().values * 252
                    vector = np.array([execution_weights.get(symbol, 0) for symbol in symbols])
                    estimated_volatility = np.sqrt(max(float(vector @ covariance @ vector), 1e-16))
                    volatility_scale = min(1.0, request.volatility_target / estimated_volatility)
                    execution_weights = {
                        symbol: weight * volatility_scale
                        for symbol, weight in execution_weights.items()
                    }

            current_weights = {
                symbol: units[symbol] * float(open_row[symbol]) / equity_at_open
                if equity_at_open > 0
                else 0
                for symbol in symbols
            }
            rebalance_band = float(params.get("rebalance_band", 0))
            if i > 0 and max(
                abs(current_weights.get(symbol, 0) - execution_weights.get(symbol, 0))
                for symbol in symbols
            ) < rebalance_band:
                # Keep the period in the equity path, but generate no orders.
                execution_weights = current_weights

            min_trade_rate = float(params.get("min_trade_rate", 0.001))
            for symbol in symbols:
                desired_value = equity_at_open * execution_weights.get(symbol, 0)
                desired_units = desired_value / float(open_row[symbol])
                delta = desired_units - units[symbol]
                if abs(delta * float(open_row[symbol])) < max(
                    equity_at_open * min_trade_rate, 1
                ):
                    continue
                side = "buy" if delta > 0 else "sell"
                execution_cost_rate = request.slippage_rate + request.spread_rate / 2
                execution_price = float(open_row[symbol]) * (
                    1 + execution_cost_rate if side == "buy" else 1 - execution_cost_rate
                )
                quantity = abs(delta)
                if side == "buy":
                    quantity = min(
                        quantity, cash / (execution_price * (1 + request.commission_rate))
                    )
                else:
                    quantity = min(quantity, units[symbol])
                if quantity <= 0:
                    continue
                notional = quantity * execution_price
                fee = notional * request.commission_rate
                if side == "buy":
                    cash -= notional + fee
                    units[symbol] += quantity
                else:
                    cash += notional - fee
                    units[symbol] -= quantity
                trades.append(
                    {
                        "id": len(trades) + 1,
                        "time": int(pd.Timestamp(timestamp).timestamp()),
                        "side": side,
                        "reason": f"{symbol} 组合再平衡",
                        "price": execution_price,
                        "quantity": quantity,
                        "notional": notional,
                        "fee": fee,
                        "slippage_cost": quantity * abs(execution_price - float(open_row[symbol])),
                        "position_after": units[symbol],
                        "cash_after": cash,
                        "realized_pnl": None,
                    }
                )
            equity_after = cash + sum(units[symbol] * float(open_row[symbol]) for symbol in symbols)
            actual = {
                symbol: units[symbol] * float(open_row[symbol]) / equity_after
                if equity_after > 0
                else 0
                for symbol in symbols
            }
            weight_history.append(
                {"time": int(pd.Timestamp(timestamp).timestamp()), "weights": actual}
            )

        equity = cash + sum(units[symbol] * float(close_row[symbol]) for symbol in symbols)
        invested = equity - cash
        equity_values.append(equity)
        exposure_values.append(invested / equity if equity > 0 else 0)

    equity_series = pd.Series(equity_values, index=close.index)
    exposure_series = pd.Series(exposure_values, index=close.index)
    equal_weight_returns = close.pct_change().mean(axis=1).fillna(0)
    benchmark = request.initial_capital * (1 + equal_weight_returns).cumprod()
    metrics, warnings = calculate_metrics(
        equity_series,
        benchmark,
        trades,
        exposure_series,
        request.interval,
        "equity",
        request.initial_capital,
    )
    returns = close.pct_change().dropna()
    latest_weights = weight_history[-1]["weights"] if weight_history else target_weights
    covariance = returns.cov().values * 252
    vector = np.array([latest_weights.get(symbol, 0) for symbol in symbols])
    portfolio_volatility = np.sqrt(max(float(vector @ covariance @ vector), 1e-16))
    marginal = covariance @ vector / portfolio_volatility
    component = vector * marginal
    risk_contribution = {
        symbol: safe_float(value / component.sum()) or 0.0
        for symbol, value in zip(symbols, component, strict=True)
    }
    if any(bundle.source_note and "历史汇率换算" in bundle.source_note for bundle in bundles):
        warnings.insert(0, f"不同币种行情已按历史汇率统一换算为 {request.base_currency}。")
    if any(bundle.source == "demo" for bundle in bundles):
        warnings.insert(0, "组合中包含演示行情，结果只用于验证产品流程。")
    if request.interval in {"1d", "1wk"}:
        warnings.insert(0, "跨市场日线/周线已按交易日期规范化，并仅保留共同交易日。")
    warnings.insert(0, "组合权重仅在再平衡日生成，并在对应开盘价计入滑点和手续费后成交。")
    if request.cash_buffer > 0:
        warnings.insert(0, f"组合保留 {request.cash_buffer:.1%} 现金缓冲。")
    if request.volatility_target is not None:
        warnings.insert(
            0,
            (
                f"目标年化波动率为 {request.volatility_target:.1%}，"
                "只会降低暴露，不使用杠杆。"
            ),
        )
    drawdown = drawdown_series(equity_series)
    equity_points = [
        EquityPoint(
            time=int(pd.Timestamp(timestamp).timestamp()),
            equity=float(equity_series.loc[timestamp]),
            benchmark=float(benchmark.loc[timestamp]),
            drawdown=float(drawdown.loc[timestamp]),
            exposure=float(exposure_series.loc[timestamp]),
        )
        for timestamp in close.index
    ]
    return PortfolioResult(
        run_id=str(uuid4()),
        created_at=datetime.now(UTC),
        strategy=strategy,
        assets=[bundle.asset for bundle in bundles],
        data_source=", ".join(sorted({bundle.source for bundle in bundles})),
        weights={key: float(value) for key, value in latest_weights.items()},
        weight_history=weight_history,
        equity=equity_points,
        trades=[Trade(**trade) for trade in trades],
        metrics=metrics,
        risk_contribution=risk_contribution,
        correlation={
            row: {column: float(value) for column, value in values.items()}
            for row, values in returns.corr().to_dict(orient="index").items()
        },
        warnings=warnings,
    )
