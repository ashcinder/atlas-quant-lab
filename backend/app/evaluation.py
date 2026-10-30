from __future__ import annotations

import math
from typing import Any


EVALUATION_VERSION = "evaluation_v1"
REGIME_NAMES = ("牛市", "熊市", "震荡")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _scale(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    ratio = (value - low) / (high - low)
    return round(max(0.0, min(100.0, ratio * 100)), 1)


def _dimension(
    dimension_id: str,
    score: float | None,
    raw: dict[str, Any],
    period: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": dimension_id,
        "status": "evaluated" if score is not None else "not_evaluable",
        "score": score,
        "raw": raw,
        "reason": reason,
        "period": period,
        "rule_version": EVALUATION_VERSION,
    }


def build_evaluation(
    metrics: dict[str, Any],
    *,
    period: dict[str, Any],
    regime_metrics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the public six-dimension evaluation without imputing missing data."""
    annualized_return = _number(metrics.get("annualized_return"))
    if annualized_return is None:
        annualized_return = _number(metrics.get("cagr"))
    sharpe = _number(metrics.get("sharpe"))
    max_drawdown = _number(metrics.get("max_drawdown"))
    drawdown_magnitude = abs(max_drawdown) if max_drawdown is not None else None

    dimensions = [
        _dimension(
            "return_capacity",
            _scale(annualized_return, -0.2, 0.4),
            {"annualized_return": annualized_return},
            period,
            None if annualized_return is not None else "缺少可核对的年化收益。",
        ),
        _dimension(
            "risk_adjusted_efficiency",
            _scale(sharpe, -1.0, 3.0),
            {"sharpe": sharpe},
            period,
            None if sharpe is not None else "缺少可核对的 Sharpe。",
        ),
        _dimension(
            "risk_control_stability",
            _scale(drawdown_magnitude, 0.5, 0.0),
            {"max_drawdown": max_drawdown},
            period,
            None if max_drawdown is not None else "缺少可核对的最大回撤。",
        ),
    ]

    regime_raw: dict[str, Any] = {}
    excess_returns: list[float] = []
    adaptability_reason: str | None = None
    if regime_metrics is None:
        adaptability_reason = "报告未关联可核对的原始市场阶段数据，不能推算市场适应性。"
    else:
        for name in REGIME_NAMES:
            source = regime_metrics.get(name, {})
            periods = int(source.get("periods", 0) or 0)
            excess = _number(source.get("annualized_excess_return"))
            regime_raw[name] = {
                "periods": periods,
                "strategy_annualized_return": _number(source.get("annualized_return")),
                "benchmark_annualized_return": _number(source.get("benchmark_annualized_return")),
                "annualized_excess_return": excess,
            }
            if periods < 30:
                adaptability_reason = f"{name}只有 {periods} 个有效收益观测，少于 30 个。"
            elif excess is None:
                adaptability_reason = f"{name}缺少可复算的年化超额收益。"
            else:
                excess_returns.append(excess)
        if adaptability_reason is None and len(excess_returns) != len(REGIME_NAMES):
            adaptability_reason = "牛市、熊市、震荡三个阶段的数据不完整。"
    mean_excess = sum(excess_returns) / len(excess_returns) if len(excess_returns) == 3 else None
    if mean_excess is not None:
        regime_raw["equal_weight_mean_excess_return"] = mean_excess
    dimensions.append(
        _dimension(
            "market_adaptability",
            _scale(mean_excess, -0.2, 0.2),
            regime_raw,
            period,
            adaptability_reason,
        )
    )
    dimensions.extend(
        [
            _dimension(
                "backtest_live_consistency",
                None,
                {},
                period,
                "缺少同一策略、同一口径和重叠区间的回测与实盘配对数据。",
            ),
            _dimension(
                "strategy_purity",
                None,
                {},
                period,
                "缺少策略风格声明、基线和可核对的持仓观测数据。",
            ),
        ]
    )
    complete = all(item["status"] == "evaluated" for item in dimensions)
    return {
        "version": EVALUATION_VERSION,
        "dimensions": dimensions,
        "complete": complete,
        "total_score": (
            round(sum(float(item["score"]) for item in dimensions) / len(dimensions), 1)
            if complete
            else None
        ),
    }
