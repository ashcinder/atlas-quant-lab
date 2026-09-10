from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from time import monotonic

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
from app.strategies.schedule import contribution_schedule
from app.strategies.catalog import validate_params


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
    request: BacktestRequest, bundle: DataBundle, *, include_details: bool = True, supplied_ai_guard=None
) -> BacktestResult:
    pipeline = request.execution_pipeline
    ai_stages = []
    ai_guard = supplied_ai_guard
    ai_reviews = 0
    ai_started = monotonic()
    if pipeline:
        request = request.model_copy(update={
            "max_position": min(request.max_position, pipeline.max_position),
            "commission_rate": pipeline.commission_rate,
            "slippage_rate": pipeline.slippage_rate,
            "max_participation_rate": pipeline.max_participation_rate,
        })
        ai_stages = [stage for stage in pipeline.ai_stages if stage.enabled]
        if len({stage.stage for stage in ai_stages}) != len(ai_stages):
            raise ValueError("AI 阶段不能重复")
        if ai_stages and ai_guard is None:
            from app.ai_runtime import LocalAIGuard
            from app.sandbox import RunnerUnavailable
            try:
                ai_guard = LocalAIGuard()
            except RunnerUnavailable as exc:
                raise ValueError(f"AI 流程未就绪：{exc}") from exc
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
    scheduled_dca = request.strategy_id == "scheduled_dca" and request.custom_strategy is None
    schedule_params = validate_params(request.strategy_id, request.params) if scheduled_dca else {}
    if scheduled_dca:
        due_dates = contribution_schedule(frame.index, int(schedule_params["every"]), str(schedule_params["unit"]), int(schedule_params["start_delay"]))
        target = pd.Series(0.0, index=frame.index)
        reasons = pd.Series("固定金额定投", index=frame.index)
    elif request.custom_strategy is not None:
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
            if scheduled_dca:
                rebalance_in_progress = due_dates[i - 1]
                impact = 1 + request.slippage_rate + request.spread_rate / 2
                budget = min(float(schedule_params["amount"]), max(0, cash))
                allowed = max(0, request.max_position * pre_trade_equity - quantity * open_price)
                addition = min(budget / (open_price * impact * (1 + request.commission_rate)), allowed / (open_price * impact)) if rebalance_in_progress else 0
                desired_quantity = quantity + addition
                active_execution_target = desired_quantity * open_price / pre_trade_equity if pre_trade_equity > 0 else 0
                pending_reason = "固定金额定投（下一根开盘）"

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
            if ai_guard and rebalance_in_progress and abs(delta * open_price) >= (0.01 if scheduled_dca else max(pre_trade_equity * 0.001, 1.0)):
                # Review only already-closed bars. AI scales the proposed order,
                # never rewrites accounting or bypasses a mandatory stop exit.
                forced_exit = pending_reason in {"收盘确认止损", "收盘确认止盈"} or (
                    delta < 0 and current_fraction > request.max_position
                )
                scale = 1.0
                for stage in ai_stages:
                    if forced_exit or (stage.stage in {"entry", "buy_size"} and delta <= 0) or (stage.stage == "sell_size" and delta >= 0):
                        continue
                    ai_reviews += 1
                    if monotonic() - ai_started > 75:
                        raise ValueError("AI 审核超过本次回测时间预算；请缩短回测范围或减少启用阶段")
                    if ai_reviews > 200:
                        raise ValueError("本次 AI 回测超过 200 次审核；请缩短时间范围或减少 AI 阶段")
                    reviewed, receipt = ai_guard.review({
                        "stage": stage.stage, "side": "buy" if delta > 0 else "sell",
                        "closed_bars": frame.iloc[max(0, i - 20):i].reset_index().astype(str).to_dict("records"),
                        "signal": pending_reason,
                    }, scale, stage.authority, instructions=stage.instructions, timeout_ms=stage.timeout_ms)
                    if receipt["status"] != "inference_completed":
                        raise ValueError(f"AI 阶段 {stage.stage} 调用失败，本次回测中止，请检查模型配置与连接")
                    if stage.authority == "reduce_only":
                        reviewed = max(reviewed, scale * (1 - stage.max_reduction))
                    scale = min(scale, max(0.0, reviewed))
                delta *= scale
            min_change = 0.01 if scheduled_dca else max(pre_trade_equity * 0.001, 1.0)
            if (
                rebalance_in_progress
                and abs(delta * open_price) >= min_change
                and (scheduled_dca or abs(current_fraction - active_execution_target) >= 0.001)
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
    if scheduled_dca:
        warnings.append("固定金额定投使用初始可用资金，金额包含手续费；资金不足、仓位上限或流动性限制可能导致部分成交或跳过。日历时间按数据 UTC 时间计算，非交易时段顺延；K线粒度过粗时合并错过的计划，不补做多笔成交。不模拟外部自动入金。")
    if request.strategy_id in {"dca", "dip_dca"} and request.custom_strategy is None:
        warnings.append("此定投模型分期提高目标仓位，只使用初始资金，不模拟外部持续入金。达到仓位上限或投入次数限制后将停止增加目标仓位；没有新买点不代表策略停止运行。")
    if pipeline:
        warnings.append(f"已应用策略流程：仓位上限 {pipeline.max_position:.0%}、手续费、滑点及成交参与率；AI 审核 {ai_reviews} 次。")
    if ai_reviews:
        warnings.append("AI 为当前配置模型对历史数据的审核，不是历史时点模型重放；本报告不包含 AI 的 ZKP 或 TEE 证明。")
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
        valuation_currency=bundle.asset.currency,
        source_note=bundle.source_note,
        bars=serialize_bars(frame) if include_details else [],
        indicators=serialize_indicators(indicators) if indicators is not None else {},
        trades=[Trade(**trade) for trade in trades],
        equity=equity_points if include_details else [],
        metrics=metrics,
        regime_metrics=regime_metrics(equity_series, frame["close"]),
        warnings=warnings,
    )
