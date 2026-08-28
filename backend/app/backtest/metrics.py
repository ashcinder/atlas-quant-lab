from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


def periods_per_year(interval: str, asset_class: str) -> float:
    days = 365 if asset_class == "crypto" else 252
    return {
        "15m": days * (96 if asset_class == "crypto" else 26),
        "1h": days * (24 if asset_class == "crypto" else 6.5),
        "4h": days * (6 if asset_class == "crypto" else 1.625),
        "1d": days,
        "1wk": 52,
    }[interval]


def safe_float(value: float | np.floating | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def drawdown_series(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak.replace(0, np.nan) - 1


def max_drawdown_duration(drawdown: pd.Series) -> int:
    longest = current = 0
    for value in drawdown.fillna(0):
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def calculate_metrics(
    equity: pd.Series,
    benchmark: pd.Series,
    trades: list[dict],
    exposure: pd.Series,
    interval: str,
    asset_class: str,
    initial_capital: float,
) -> tuple[dict[str, float | int | None], list[str]]:
    factor = periods_per_year(interval, asset_class)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    benchmark_returns = benchmark.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    drawdown = drawdown_series(equity)
    periods = max(len(returns), 1)
    total_return = equity.iloc[-1] / initial_capital - 1
    years = periods / factor
    cagr = (
        (equity.iloc[-1] / initial_capital) ** (1 / years) - 1
        if years > 0 and equity.iloc[-1] > 0
        else np.nan
    )
    annual_volatility = returns.std(ddof=1) * math.sqrt(factor) if len(returns) > 1 else 0.0
    annual_return = returns.mean() * factor if len(returns) else 0.0
    sharpe = annual_return / annual_volatility if annual_volatility > 0 else np.nan
    downside = (
        returns[returns < 0].std(ddof=1) * math.sqrt(factor) if (returns < 0).sum() > 1 else np.nan
    )
    sortino = annual_return / downside if downside and downside > 0 else np.nan
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 and np.isfinite(cagr) else np.nan
    var_95 = -float(np.percentile(returns, 5)) if len(returns) else np.nan
    tail = returns[returns <= -var_95] if np.isfinite(var_95) else pd.Series(dtype=float)
    cvar_95 = -float(tail.mean()) if len(tail) else np.nan
    aligned = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) > 1:
        active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
        tracking_error = active.std(ddof=1) * math.sqrt(factor)
        information_ratio = (
            active.mean() * factor / tracking_error if tracking_error > 0 else np.nan
        )
        beta = (
            np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1], ddof=1)[0, 1]
            / np.var(aligned.iloc[:, 1], ddof=1)
            if np.var(aligned.iloc[:, 1], ddof=1) > 0
            else np.nan
        )
    else:
        information_ratio = beta = np.nan

    sell_trades = [
        trade
        for trade in trades
        if trade["side"] == "sell" and trade.get("realized_pnl") is not None
    ]
    pnls = [float(trade["realized_pnl"]) for trade in sell_trades]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (np.inf if wins else np.nan)
    fees = sum(float(trade["fee"]) for trade in trades)
    notional = sum(float(trade["notional"]) for trade in trades)
    t_stat, p_value = (
        stats.ttest_1samp(returns, 0, nan_policy="omit") if len(returns) >= 3 else (np.nan, np.nan)
    )

    metrics: dict[str, float | int | None] = {
        "total_return": safe_float(total_return),
        "cagr": safe_float(cagr),
        "benchmark_return": safe_float(benchmark.iloc[-1] / benchmark.iloc[0] - 1),
        "excess_return": safe_float(total_return - (benchmark.iloc[-1] / benchmark.iloc[0] - 1)),
        "annual_volatility": safe_float(annual_volatility),
        "max_drawdown": safe_float(max_drawdown),
        "max_drawdown_duration": max_drawdown_duration(drawdown),
        "var_95": safe_float(var_95),
        "cvar_95": safe_float(cvar_95),
        "sharpe": safe_float(sharpe),
        "sortino": safe_float(sortino),
        "calmar": safe_float(calmar),
        "information_ratio": safe_float(information_ratio),
        "beta": safe_float(beta),
        "trade_count": len(trades),
        "round_trip_count": len(sell_trades),
        "win_rate": safe_float(len(wins) / len(pnls) if pnls else np.nan),
        "profit_factor": safe_float(profit_factor),
        "expectancy": safe_float(np.mean(pnls) if pnls else np.nan),
        "fees_paid": safe_float(fees),
        "cost_drag": safe_float(fees / initial_capital),
        "turnover": safe_float(notional / initial_capital),
        "average_exposure": safe_float(exposure.mean()),
        "return_t_stat": safe_float(t_stat),
        "return_p_value": safe_float(p_value),
    }
    warnings: list[str] = []
    if len(sell_trades) < 30:
        warnings.append(f"完整交易仅 {len(sell_trades)} 笔，少于30笔，统计结论可信度有限。")
    if sharpe is not None and np.isfinite(sharpe) and abs(sharpe) > 3:
        warnings.append("Sharpe绝对值超过3，请重点检查过拟合、未来数据和样本长度。")
    if years < 3:
        warnings.append("回测历史不足3年，可能只覆盖单一市场阶段。")
    if fees > abs(equity.iloc[-1] - initial_capital) and fees > 0:
        warnings.append("交易成本超过策略净盈利绝对值，策略对费用高度敏感。")
    return metrics, warnings


def classify_regimes(close: pd.Series) -> pd.Series:
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    returns = close.pct_change()
    volatility = returns.rolling(20).std()
    average_volatility = volatility.rolling(120, min_periods=40).mean()
    regime = pd.Series("震荡", index=close.index, dtype=object)
    regime.loc[(close > sma50) & (sma50 > sma200) & (volatility <= average_volatility)] = "牛市"
    regime.loc[(close < sma50) & (sma50 < sma200)] = "熊市"
    return regime


def regime_metrics(equity: pd.Series, close: pd.Series) -> dict[str, dict[str, float | int | None]]:
    returns = equity.pct_change()
    regimes = classify_regimes(close)
    output: dict[str, dict[str, float | int | None]] = {}
    for name in ["牛市", "熊市", "震荡"]:
        values = returns[regimes == name].dropna()
        output[name] = {
            "periods": int(len(values)),
            "total_return": safe_float((1 + values).prod() - 1 if len(values) else np.nan),
            "average_return": safe_float(values.mean() if len(values) else np.nan),
            "win_period_rate": safe_float((values > 0).mean() if len(values) else np.nan),
        }
    return output
