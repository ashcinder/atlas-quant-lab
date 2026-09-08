from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .types import PortfolioSnapshot, RiskLimits, TargetPosition


@dataclass(frozen=True, slots=True)
class HardRiskResult:
    accepted: tuple[TargetPosition, ...]
    rejected_reasons: tuple[str, ...]
    trading_halted: bool


def apply_hard_limits(
    targets: Sequence[TargetPosition], portfolio: PortfolioSnapshot, limits: RiskLimits
) -> HardRiskResult:
    """Pure final gate. AI output is treated exactly like any other untrusted proposal."""
    if portfolio.daily_pnl <= -limits.max_daily_loss * portfolio.equity:
        return HardRiskResult((), ("MAX_DAILY_LOSS",), True)
    if portfolio.drawdown <= -limits.max_drawdown:
        return HardRiskResult((), ("MAX_DRAWDOWN",), True)

    accepted: list[TargetPosition] = []
    reasons: list[str] = []
    for target in targets:
        bounded = max(-limits.max_single_position, min(limits.max_single_position, target.target_weight))
        if bounded != target.target_weight:
            reasons.append(f"CLAMP_SINGLE_POSITION:{target.symbol}")
        accepted.append(
            TargetPosition(target.symbol, bounded, target.confidence, target.reason_code, target.metadata)
        )
    gross = sum(abs(target.target_weight) for target in accepted)
    if gross > limits.max_gross_exposure and gross > 0:
        scale = limits.max_gross_exposure / gross
        accepted = [
            TargetPosition(item.symbol, item.target_weight * scale, item.confidence, item.reason_code, item.metadata)
            for item in accepted
        ]
        reasons.append("SCALE_GROSS_EXPOSURE")
    return HardRiskResult(tuple(accepted), tuple(reasons), False)
