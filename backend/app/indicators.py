import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def calculate_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    close = frame["close"]
    result["sma20"] = close.rolling(20).mean()
    result["sma50"] = close.rolling(50).mean()
    result["ema12"] = ema(close, 12)
    result["ema26"] = ema(close, 26)
    result["macd"] = result["ema12"] - result["ema26"]
    result["macd_signal"] = ema(result["macd"], 9)
    result["macd_hist"] = result["macd"] - result["macd_signal"]
    result["rsi14"] = rsi(close, 14)
    middle = close.rolling(20).mean()
    std = close.rolling(20).std()
    result["boll_mid"] = middle
    result["boll_upper"] = middle + 2 * std
    result["boll_lower"] = middle - 2 * std
    result["atr14"] = atr(frame, 14)
    low_n = frame["low"].rolling(9).min()
    high_n = frame["high"].rolling(9).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    result["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    result["kdj_d"] = result["kdj_k"].ewm(alpha=1 / 3, adjust=False).mean()
    result["kdj_j"] = 3 * result["kdj_k"] - 2 * result["kdj_d"]
    return result


def serialize_indicators(
    indicators: pd.DataFrame,
) -> dict[str, list[dict[str, float | int | None]]]:
    payload: dict[str, list[dict[str, float | int | None]]] = {}
    for column in indicators.columns:
        points = []
        for timestamp, value in indicators[column].items():
            points.append(
                {
                    "time": int(pd.Timestamp(timestamp).timestamp()),
                    "value": None if pd.isna(value) else float(value),
                }
            )
        payload[column] = points
    return payload
