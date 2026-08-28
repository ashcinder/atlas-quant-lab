import numpy as np
import pandas as pd

from app.indicators import ema, rsi
from app.strategies.catalog import default_params


def _merge_params(strategy_id: str, params: dict) -> dict:
    merged = default_params(strategy_id)
    merged.update(params)
    return merged


def _hold_state(entries: pd.Series, exits: pd.Series) -> pd.Series:
    state = pd.Series(np.nan, index=entries.index, dtype=float)
    state.loc[entries.fillna(False)] = 1.0
    state.loc[exits.fillna(False)] = 0.0
    return state.ffill().fillna(0.0)


def _confirmed(mask: pd.Series, bars: int) -> pd.Series:
    bars = max(1, int(bars))
    if bars == 1:
        return mask.fillna(False)
    return mask.fillna(False).rolling(bars, min_periods=bars).sum().eq(bars)


def generate_target_exposure(
    frame: pd.DataFrame, strategy_id: str, params: dict, max_position: float
) -> tuple[pd.Series, pd.Series]:
    """Return target exposure and a human-readable reason for each bar.

    Values are calculated from information available at the current close. The
    execution engine applies changes at the next bar open.
    """
    p = _merge_params(strategy_id, params)
    close = frame["close"]
    target = pd.Series(0.0, index=frame.index)
    reason = pd.Series("等待信号", index=frame.index, dtype=object)

    if strategy_id in {"sma_cross", "ema_cross"}:
        fast, slow = int(p["fast"]), int(p["slow"])
        if fast >= slow:
            raise ValueError("快速周期必须小于慢速周期")
        fast_line = close.rolling(fast).mean() if strategy_id == "sma_cross" else ema(close, fast)
        slow_line = close.rolling(slow).mean() if strategy_id == "sma_cross" else ema(close, slow)
        long_condition = fast_line > slow_line * (1 + float(p["min_gap"]))
        trend_filter = int(p["trend_filter"])
        if trend_filter > 0:
            long_condition &= close > close.rolling(trend_filter).mean()
        long_condition = _confirmed(long_condition, int(p["confirm_bars"]))
        target = long_condition.astype(float) * max_position
        reason.loc[target > 0] = "快速均线位于慢速均线上方"
        reason.loc[target == 0] = "均线差距、确认期或趋势过滤未满足"
    elif strategy_id == "macd":
        fast_line = ema(close, int(p["fast"]))
        slow_line = ema(close, int(p["slow"]))
        macd_line = fast_line - slow_line
        signal = ema(macd_line, int(p["signal"]))
        long_condition = macd_line > signal
        if bool(p["zero_line_filter"]):
            long_condition &= macd_line > 0
        long_condition = _confirmed(long_condition, int(p["confirm_bars"]))
        target = long_condition.astype(float) * max_position
        reason.loc[target > 0] = "MACD上穿并保持在信号线上方"
        reason.loc[target == 0] = "MACD未确认多头"
    elif strategy_id == "rsi_reversal":
        oscillator = rsi(close, int(p["period"]))
        entries = _confirmed(oscillator < float(p["entry"]), int(p["entry_confirm"]))
        exits = _confirmed(oscillator > float(p["exit"]), int(p["exit_confirm"]))
        target = _hold_state(entries, exits) * max_position
        reason.loc[oscillator < float(p["entry"])] = "RSI进入超卖区"
        reason.loc[oscillator > float(p["exit"])] = "RSI恢复至退出阈值"
    elif strategy_id == "bollinger":
        period = int(p["period"])
        middle = close.rolling(period).mean()
        std = close.rolling(period).std()
        lower = middle - float(p["std_dev"]) * std
        upper = middle + float(p["std_dev"]) * std
        bandwidth = (upper - lower) / middle.replace(0, np.nan)
        entries = (close < lower) & (bandwidth >= float(p["min_bandwidth"]))
        exit_line = lower + (middle - lower) * float(p["exit_ratio"])
        exits = close >= exit_line
        target = _hold_state(entries, exits) * max_position
        reason.loc[entries] = "价格跌破下轨且带宽满足过滤"
        reason.loc[exits] = "价格恢复至设定退出位置"
    elif strategy_id == "breakout":
        entry_high = frame["high"].rolling(int(p["entry_lookback"])).max().shift(1)
        exit_low = frame["low"].rolling(int(p["exit_lookback"])).min().shift(1)
        entries = _confirmed(
            close > entry_high * (1 + float(p["breakout_buffer"])), int(p["confirm_bars"])
        )
        target = _hold_state(entries, close < exit_low) * max_position
        reason.loc[entries] = "收盘确认突破缓冲后的通道高点"
        reason.loc[close < exit_low] = "收盘跌破退出通道"
    elif strategy_id == "momentum":
        momentum = close.pct_change(int(p["lookback"])).rolling(int(p["smoothing"])).mean()
        target = (
            _hold_state(momentum > float(p["threshold"]), momentum < float(p["exit_threshold"]))
            * max_position
        )
        reason.loc[target > 0] = "阶段动量超过阈值"
        reason.loc[target == 0] = "阶段动量不足"
    elif strategy_id in {"dca", "dip_dca"}:
        every = int(p["every_bars"])
        increment = float(p["amount_pct"])
        start_delay = int(p.get("start_delay", 0))
        max_contributions = int(p.get("max_contributions", 0))
        contributions = 0
        running = 0.0
        drawdown_lookback = int(p.get("drawdown_lookback", max(20, every)))
        rolling_peak = close.rolling(drawdown_lookback, min_periods=1).max()
        drawdown = close / rolling_peak - 1
        for i, index in enumerate(frame.index):
            due = i >= start_delay and (i - start_delay) % every == 0
            within_limit = max_contributions == 0 or contributions < max_contributions
            if due and within_limit:
                add = increment
                if strategy_id == "dip_dca" and drawdown.loc[index] <= -float(p["dip_threshold"]):
                    add *= float(p["dip_multiplier"])
                    reason.loc[index] = "阶段回撤触发加倍定投"
                else:
                    reason.loc[index] = "定期投入"
                running = min(max_position, running + add)
                contributions += 1
            target.loc[index] = running
    elif strategy_id in {"arithmetic_grid", "geometric_grid"}:
        lower, upper = float(p["lower"]), float(p["upper"])
        levels = int(p["levels"])
        if lower <= 0 or upper <= lower:
            raise ValueError("网格上限必须大于下限，且下限必须为正")
        if strategy_id == "geometric_grid":
            raw = (np.log(upper) - np.log(close.clip(lower=lower, upper=upper))) / (
                np.log(upper) - np.log(lower)
            )
        else:
            raw = (upper - close.clip(lower=lower, upper=upper)) / (upper - lower)
        stepped = np.ceil(raw * levels) / levels
        base_position = float(p["base_position"])
        target = (base_position + (1 - base_position) * stepped.clip(0, 1)) * max_position
        reason.loc[target.diff().fillna(0) > 0] = "价格下穿网格，增加仓位"
        reason.loc[target.diff().fillna(0) < 0] = "价格上穿网格，减少仓位"
    elif strategy_id in {"martingale", "anti_martingale"}:
        base = float(p["base_position"])
        multiplier = float(p["multiplier"])
        if strategy_id == "martingale":
            oscillator = rsi(close, int(p["rsi_period"]))
            drawdown = close / close.rolling(20, min_periods=1).max() - 1
            levels = (-drawdown / float(p["drawdown_step"])).clip(0, 4).fillna(0).astype(int)
            target = pd.Series(
                np.where(oscillator < 55, base * multiplier**levels, 0), index=frame.index
            )
            reason.loc[target > 0] = "回撤层级提高马丁目标仓位"
            reason.loc[target == 0] = "RSI退出马丁持仓"
        else:
            momentum = close.pct_change(int(p["lookback"]))
            levels = (
                (momentum.clip(lower=0) / float(p["level_step"]))
                .clip(0, int(p["max_levels"]))
                .fillna(0)
                .astype(int)
            )
            target = pd.Series(
                np.where(momentum > 0, base * multiplier**levels, 0), index=frame.index
            )
            reason.loc[target > 0] = "盈利趋势提高反马丁目标仓位"
            reason.loc[target == 0] = "动量转弱，降低仓位"
        target = target.clip(0, max_position)
    else:
        raise ValueError(f"策略 {strategy_id} 不支持单标的回测")

    return target.fillna(0).clip(0, max_position), reason
