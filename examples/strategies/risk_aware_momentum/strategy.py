from __future__ import annotations

from math import sqrt

from atlas_strategy_sdk import BaseStrategy, StrategyContext, TargetPosition


class RiskAwareMomentum(BaseStrategy):
    def generate_targets(self, context: StrategyContext) -> list[TargetPosition]:
        lookback = int(context.parameters["lookback"])
        vol_window = int(context.parameters["volatility_window"])
        target_vol = float(context.parameters["target_volatility"])
        maximum = float(context.parameters["maximum_weight"])
        targets: list[TargetPosition] = []
        for symbol in sorted(context.bars):
            bars = context.history(symbol, max(lookback + 1, vol_window + 1))
            if len(bars) < max(lookback + 1, vol_window + 1):
                continue
            momentum = bars[-1].close / bars[-lookback - 1].close - 1
            returns = [bars[index].close / bars[index - 1].close - 1 for index in range(len(bars) - vol_window, len(bars))]
            mean = sum(returns) / len(returns)
            variance = sum((value - mean) ** 2 for value in returns) / max(1, len(returns) - 1)
            annualized_vol = sqrt(variance) * sqrt(252)
            raw_weight = 0.0 if momentum <= 0 or annualized_vol <= 0 else target_vol / annualized_vol
            targets.append(TargetPosition(symbol, min(maximum, raw_weight), min(1.0, abs(momentum) * 5), "POSITIVE_MOMENTUM" if momentum > 0 else "NO_MOMENTUM"))
        total = sum(target.target_weight for target in targets)
        if total > 1:
            targets = [TargetPosition(item.symbol, item.target_weight / total, item.confidence, item.reason_code) for item in targets]
        return targets
