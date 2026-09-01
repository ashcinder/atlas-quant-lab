from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    timestamp: datetime
    equity: float
    cash: float
    positions: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    weights: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    daily_pnl: float = 0.0
    drawdown: float = 0.0


@dataclass(frozen=True, slots=True)
class StrategyContext:
    now: datetime
    bars: Mapping[str, Sequence[Bar]]
    portfolio: PortfolioSnapshot
    parameters: Mapping[str, int | float | bool | str]
    run_id: str
    random_seed: int

    def history(self, symbol: str, count: int) -> Sequence[Bar]:
        """Return bars available at `now`; a runner must never inject future bars."""
        if count <= 0:
            raise ValueError("count must be positive")
        return self.bars.get(symbol, ())[-count:]


@dataclass(frozen=True, slots=True)
class TargetPosition:
    symbol: str
    target_weight: float
    confidence: float
    reason_code: str
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    limit_price: float | None = None
    reason_code: str = "strategy"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_gross_exposure: float
    max_single_position: float
    max_daily_loss: float
    max_drawdown: float
    max_participation_rate: float


@dataclass(frozen=True, slots=True)
class AIRequest:
    request_id: str
    role: str
    timestamp: datetime
    baseline: Mapping[str, Any]
    evidence: Mapping[str, Any]
    allowed_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AIResponse:
    request_id: str
    action: str
    confidence: float
    reason_codes: tuple[str, ...]
    adjustments: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
