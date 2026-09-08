from datetime import UTC, datetime

from atlas_strategy_sdk import PortfolioSnapshot, RiskLimits, TargetPosition, apply_hard_limits


LIMITS = RiskLimits(0.9, 0.25, 0.03, 0.15, 0.01)


def snapshot(**updates):
    values = {"timestamp": datetime.now(UTC), "equity": 100_000, "cash": 100_000}
    values.update(updates)
    return PortfolioSnapshot(**values)


def test_hard_limits_clamp_single_and_gross_exposure():
    targets = [TargetPosition(symbol, 0.4, 0.8, "TEST") for symbol in ("A", "B", "C", "D")]
    result = apply_hard_limits(targets, snapshot(), LIMITS)
    assert result.trading_halted is False
    assert sum(item.target_weight for item in result.accepted) == 0.9
    assert all(item.target_weight <= LIMITS.max_single_position for item in result.accepted)
    assert "SCALE_GROSS_EXPOSURE" in result.rejected_reasons


def test_hard_limits_fail_closed_on_loss_or_drawdown():
    target = [TargetPosition("BTC-USD", 0.1, 0.8, "TEST")]
    daily = apply_hard_limits(target, snapshot(daily_pnl=-3_001), LIMITS)
    drawdown = apply_hard_limits(target, snapshot(drawdown=-0.151), LIMITS)
    assert daily.trading_halted and daily.rejected_reasons == ("MAX_DAILY_LOSS",)
    assert drawdown.trading_halted and drawdown.rejected_reasons == ("MAX_DRAWDOWN",)
