from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators import ema, rsi
from app.models import CustomStrategySpec, IndicatorSpec, RuleNode


def validate_rule_complexity(node: RuleNode, depth: int = 1) -> int:
    if depth > 5:
        raise ValueError("自定义策略条件最多嵌套5层")
    if node.kind == "condition":
        return 1
    count = 1 + sum(validate_rule_complexity(child, depth + 1) for child in node.children)
    if count > 50:
        raise ValueError("自定义策略最多包含50个条件节点")
    return count


def _series(frame: pd.DataFrame, spec: IndicatorSpec) -> pd.Series:
    close = frame["close"]
    period = int(spec.period or 14)
    if spec.field in {"open", "high", "low", "close", "volume"}:
        return frame[spec.field].astype(float)
    if spec.field == "sma":
        return close.rolling(period, min_periods=period).mean()
    if spec.field == "ema":
        return ema(close, period)
    if spec.field == "rsi":
        return rsi(close, period)
    if spec.field in {"macd", "macd_signal"}:
        macd_line = ema(close, 12) - ema(close, 26)
        return macd_line if spec.field == "macd" else ema(macd_line, 9)
    if spec.field in {"boll_upper", "boll_lower"}:
        middle = close.rolling(period, min_periods=period).mean()
        width = close.rolling(period, min_periods=period).std() * 2
        return middle + width if spec.field == "boll_upper" else middle - width
    if spec.field == "roc":
        return close.pct_change(period)
    raise ValueError(f"不支持的指标: {spec.field}")


def _evaluate_condition(frame: pd.DataFrame, node: RuleNode) -> pd.Series:
    if node.left is None or node.operator is None:
        raise ValueError("自定义比较条件不完整")
    left = _series(frame, node.left)
    right: pd.Series
    if node.right_indicator is not None:
        right = _series(frame, node.right_indicator)
    else:
        right = pd.Series(float(node.right_value), index=frame.index, dtype=float)
    operator = node.operator
    if operator == "gt":
        output = left > right
    elif operator == "gte":
        output = left >= right
    elif operator == "lt":
        output = left < right
    elif operator == "lte":
        output = left <= right
    elif operator == "crosses_above":
        output = (left > right) & (left.shift(1) <= right.shift(1))
    else:
        output = (left < right) & (left.shift(1) >= right.shift(1))
    return output.fillna(False)


def evaluate_rule(frame: pd.DataFrame, node: RuleNode) -> pd.Series:
    if node.kind == "condition":
        return _evaluate_condition(frame, node)
    values = [evaluate_rule(frame, child) for child in node.children]
    if not values:
        return pd.Series(False, index=frame.index)
    matrix = pd.concat(values, axis=1)
    return matrix.all(axis=1) if node.combinator == "all" else matrix.any(axis=1)


def generate_custom_target(
    frame: pd.DataFrame, spec: CustomStrategySpec, max_position: float
) -> tuple[pd.Series, pd.Series]:
    validate_rule_complexity(spec.entry)
    validate_rule_complexity(spec.exit)
    entries = evaluate_rule(frame, spec.entry)
    exits = evaluate_rule(frame, spec.exit)
    state = pd.Series(np.nan, index=frame.index, dtype=float)
    state.loc[entries] = min(spec.target_position, max_position)
    state.loc[exits] = 0.0
    target = state.ffill().fillna(0.0)
    reason = pd.Series("等待自定义信号", index=frame.index, dtype=object)
    reason.loc[entries] = f"{spec.name}：入场条件成立"
    reason.loc[exits] = f"{spec.name}：退出条件成立"
    return target.clip(0, max_position), reason
