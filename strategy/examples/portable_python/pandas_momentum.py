"""Pandas/NumPy indicators with ordinary branching, independent of frameworks."""
import numpy as np
import pandas as pd


def target(context):
    if len(context.close) < 40:
        return 0.0
    prices = pd.Series(context.close[-40:], dtype=float)
    trend = prices.ewm(span=20, adjust=False).mean().iloc[-1]
    volatility = float(np.std(np.diff(np.log(prices.to_numpy()))))
    if prices.iloc[-1] > trend and volatility < 0.04:
        return 0.65
    return 0.0
