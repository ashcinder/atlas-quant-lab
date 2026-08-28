from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pandas as pd

from app.backtest.metrics import calculate_metrics, drawdown_series, regime_metrics
from app.data.service import DataBundle
from app.indicators import calculate_indicators, serialize_indicators
from app.models import (
    BacktestRequest,
    BacktestResult,
    Bar,
    EquityPoint,
    StrategyDefinition,
    Trade,
)
from app.strategies import generate_target_exposure, get_strategy
from app.strategies.custom import generate_custom_target


def serialize_bars(frame: pd.DataFrame) -> list[Bar]:
    return [
        Bar(
            time=int(pd.Timestamp(index).timestamp()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for index, row in frame.iterrows()
    ]


def run_backtest(
    request: BacktestRequest, bundle: DataBundle, *, include_details: bool = True
) -> BacktestResult:
    frame = bundle.frame.copy()
    if len(frame) < 40:
        raise ValueError("至少需要40根K线才能回测")
    if request.custom_strategy is not None:
        strategy = StrategyDefinition(
            id=request.custom_strategy.id,
            name=request.custom_strategy.name,
            category="自定义",
            description=request.custom_strategy.description,
            suitable_for="由用户定义的条件组合",
            risk_level="高",
            parameters=[],
        )
    else:
        strategy = get_strategy(request.strategy_id)
    if strategy.mode != "single":
        raise ValueError("组合策略请使用组合回测接口")
    if request.custom_strategy is not None:
        target, reasons = generate_custom_target(
            frame, request.custom_strategy, request.max_position
        )
    else:
        target, reasons = generate_target_exposure(
            frame, request.strategy_id, request.params, request.max_position
        )
    indicators = calculate_indicators(frame) if include_details else None

    cash = request.initial_capital
    quantity = 0.0
    average_cost = 0.0
    trades: list[dict] = []
    equity_values: list[float] = []
    exposure_values: list[float] = []
    pending_target = 0.0
    pending_reason = "初始状态"
    last_signal_target = 0.0
    active_execution_target = 0.0
    rebalance_in_progress = False

    first_close = float(frame["close"].iloc[0])
    benchmark_units = request.initial_capital / first_close

    for i, (timestamp, bar) in enumerate(frame.iterrows()):
        open_price = float(bar.open)
        mark_price = float(bar.close)
        pre_trade_equity = cash + quantity * open_price

        if i > 0:
            if not np.isclose(pending_target, last_signal_target, atol=1e-9):
                last_signal_target = pending_target
                active_execution_target = pending_target
                rebalance_in_progress = True
            current_fraction = (
                quantity * open_price / pre_trade_equity if pre_trade_equity > 0 else 0.0
            )
            desired_value = active_execution_target * pre_trade_equity
            desired_quantity = desired_value / open_price if open_price > 0 else quantity

            # Stops are close-confirmed and therefore also execute at the next open.
            if quantity > 0 and average_cost > 0:
                previous_close = float(frame["close"].iloc[i - 1])
                if request.stop_loss and previous_close <= average_cost * (1 - request.stop_loss):
                    active_execution_target = 0.0
                    rebalance_in_progress = True
                    desired_quantity = 0.0
                    pending_reason = "收盘确认止损"
                elif request.take_profit and previous_close >= average_cost * (
                    1 + request.take_profit
                ):
                    active_execution_target = 0.0
                    rebalance_in_progress = True
                    desired_quantity = 0.0
                    pending_reason = "收盘确认止盈"

            delta = desired_quantity - quantity
            min_change = max(pre_trade_equity * 0.001, 1.0)
            if (
                rebalance_in_progress
                and abs(delta * open_price) >= min_change
                and abs(current_fraction - active_execution_target) >= 0.001
            ):
                side = "buy" if delta > 0 else "sell"
                half_spread = request.spread_rate / 2
                price_impact = request.slippage_rate + half_spread
                execution_price = open_price * (
                    1 + price_impact if side == "buy" else 1 - price_impact
                )
                max_notional = np.inf
                if float(bar.volume) > 0:
                    max_notional = float(bar.volume) * open_price * request.max_participation_rate
                trade_quantity = min(abs(delta), max_notional / execution_price)
                if side == "buy":
                    affordable = cash / (execution_price * (1 + request.commission_rate))
                    trade_quantity = min(trade_quantity, affordable)
                notional = trade_quantity * execution_price
                fee = notional * request.commission_rate
                slippage_cost = trade_quantity * abs(execution_price - open_price)
                realized_pnl = None
                if trade_quantity > 0:
                    if side == "buy":
                        old_cost = average_cost * quantity
                        cash -= notional + fee
                        quantity += trade_quantity
                        average_cost = (
                            (old_cost + notional + fee) / quantity if quantity > 0 else 0.0
                        )
                    else:
                        trade_quantity = min(trade_quantity, quantity)
                        notional = trade_quantity * execution_price
                        fee = notional * request.commission_rate
                        cash += notional - fee
                        realized_pnl = (execution_price - average_cost) * trade_quantity - fee
                        quantity -= trade_quantity
                        if quantity <= 1e-12:
                            quantity = 0.0
                            average_cost = 0.0
                    trades.append(
                        {
                            "id": len(trades) + 1,
                            "time": int(pd.Timestamp(timestamp).timestamp()),
                            "side": side,
                            "reason": pending_reason,
                            "price": execution_price,
                            "quantity": trade_quantity,
                            "notional": notional,
                            "fee": fee,
                            "slippage_cost": slippage_cost,
                            "position_after": quantity,
                            "cash_after": cash,
                            "realized_pnl": realized_pnl,
                        }
                    )
            post_trade_equity = cash + quantity * open_price
            post_trade_fraction = (
                quantity * open_price / post_trade_equity if post_trade_equity > 0 else 0.0
            )
            remaining_notional = abs(
                active_execution_target * post_trade_equity - quantity * open_price
            )
            if abs(
                post_trade_fraction - active_execution_target
            ) < 0.002 or remaining_notional < max(post_trade_equity * 0.001, 1.0):
                rebalance_in_progress = False

        equity = cash + quantity * mark_price
        equity_values.append(equity)
        exposure_values.append(quantity * mark_price / equity if equity > 0 else 0.0)
        pending_target = float(target.iloc[i])
        pending_reason = str(reasons.iloc[i])

    equity_series = pd.Series(equity_values, index=frame.index, dtype=float)
    exposure_series = pd.Series(exposure_values, index=frame.index, dtype=float)
    benchmark_series = frame["close"] * benchmark_units
    drawdown = drawdown_series(equity_series)
    metrics, warnings = calculate_metrics(
        equity_series,
        benchmark_series,
        trades,
        exposure_series,
        request.interval,
        bundle.asset.asset_class,
        request.initial_capital,
    )
    warnings.insert(0, "所有策略信号均在当前K线收盘后生成，并在下一根K线开盘执行。")
    if request.strategy_id in {"arithmetic_grid", "geometric_grid"}:
        warnings.append("网格使用收盘确认和保守成交顺序；单根K线内的真实价格路径无法由OHLC确定。")
    if bundle.source == "demo":
        warnings.insert(0, "当前使用明确标记的演示数据，结果不能用于真实投资判断。")

    equity_points = [
        EquityPoint(
            time=int(pd.Timestamp(timestamp).timestamp()),
            equity=float(equity_series.loc[timestamp]),
            benchmark=float(benchmark_series.loc[timestamp]),
            drawdown=float(drawdown.loc[timestamp])
            if np.isfinite(drawdown.loc[timestamp])
            else 0.0,
            exposure=float(exposure_series.loc[timestamp]),
        )
        for timestamp in frame.index
    ]
    return BacktestResult(
        run_id=str(uuid4()),
        created_at=datetime.now(UTC),
        asset=bundle.asset,
        interval=request.interval,
        strategy=strategy,
        data_source=bundle.source,
        source_note=bundle.source_note,
        bars=serialize_bars(frame) if include_details else [],
        indicators=serialize_indicators(indicators) if indicators is not None else {},
        trades=[Trade(**trade) for trade in trades],
        equity=equity_points if include_details else [],
        metrics=metrics,
        regime_metrics=regime_metrics(equity_series, frame["close"]),
        warnings=warnings,
    )
