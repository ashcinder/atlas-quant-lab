from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from .types import StrategyContext, TargetPosition


class BaseStrategy(ABC):
    """Deterministic strategy contract; network, filesystem and clock access are runner-owned."""

    def initialize(self, parameters: Mapping[str, int | float | bool | str]) -> None:
        """Validate immutable parameters before the first market event."""

    @abstractmethod
    def generate_targets(self, context: StrategyContext) -> Sequence[TargetPosition]:
        """Return desired positions. Orders are created only after AI and hard-risk stages."""
        raise NotImplementedError

    def on_fill(self, _fill: Mapping[str, object]) -> None:
        """Optional deterministic fill callback."""
