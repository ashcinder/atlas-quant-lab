from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import yfinance as yf

from app.models import Asset


class ProviderError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        raise NotImplementedError


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ProviderError("数据源没有返回行情")
    frame = frame.rename(columns={str(column): str(column).lower() for column in frame.columns})
    required = ["open", "high", "low", "close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ProviderError(f"行情缺少字段: {', '.join(missing)}")
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    frame = frame[["open", "high", "low", "close", "volume"]].copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    return frame.astype(float)


class YahooProvider(MarketDataProvider):
    name = "yahoo"

    INTERVAL_MAP = {"15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d", "1wk": "1wk"}
    DEFAULT_PERIOD = {"15m": "60d", "1h": "2y", "4h": "2y", "1d": "10y", "1wk": "max"}

    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        provider_interval = self.INTERVAL_MAP[interval]
        date_options = (
            {"start": start, "end": end}
            if start is not None or end is not None
            else {"period": self.DEFAULT_PERIOD[interval]}
        )
        try:
            frame = yf.download(
                asset.provider_symbol or asset.symbol,
                **date_options,
                interval=provider_interval,
                auto_adjust=False,
                progress=False,
                group_by="column",
                threads=False,
                timeout=12,
            )
        except Exception as exc:  # provider-specific failures are normalized
            raise ProviderError(f"Yahoo 行情请求失败: {exc}") from exc
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.rename(columns={str(column): str(column).lower() for column in frame.columns})
        if adjustment != "raw" and "adj close" in frame.columns:
            ratio = (frame["adj close"] / frame["close"]).replace([np.inf, -np.inf], np.nan)
            valid_ratio = ratio.dropna()
            if not valid_ratio.empty:
                anchor = valid_ratio.iloc[0] if adjustment == "backward" else valid_ratio.iloc[-1]
                scale = (ratio / anchor).ffill().bfill()
                frame[["open", "high", "low", "close"]] = frame[
                    ["open", "high", "low", "close"]
                ].mul(scale, axis=0)
        frame = _normalize(frame)
        if interval == "4h":
            frame = (
                frame.resample("4h")
                .agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
                )
                .dropna(subset=["open", "high", "low", "close"])
            )
        return frame


def _records_frame(
    records: list[dict] | list[list],
    columns: dict[str, str] | list[str],
    timezone: str,
) -> pd.DataFrame:
    if not records:
        raise ProviderError("数据源没有返回行情")
    frame = pd.DataFrame(records)
    if isinstance(columns, list):
        if frame.shape[1] < len(columns):
            raise ProviderError("行情字段数量不完整")
        frame = frame.iloc[:, : len(columns)]
        frame.columns = columns
    else:
        frame = frame.rename(columns=columns)
    if "date" not in frame.columns:
        raise ProviderError("行情缺少时间字段")
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date"), errors="coerce"))
    valid = ~index.isna()
    frame = frame.loc[valid].copy()
    index = index[valid]
    if index.tz is None:
        index = index.tz_localize(ZoneInfo(timezone), ambiguous="NaT", nonexistent="shift_forward")
    frame.index = index.tz_convert("UTC")
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "volume" in frame.columns:
        frame["volume"] = frame["volume"].fillna(0.0)
    return _normalize(frame)


def _resample_ohlcv(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    return _normalize(
        frame.resample(frequency)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "high", "low", "close"])
    )


def _append_latest_sessions(
    daily: pd.DataFrame, intraday: pd.DataFrame, timezone: str
) -> pd.DataFrame:
    sessions = _resample_ohlcv(intraday.tz_convert(ZoneInfo(timezone)), "1D")
    additions = sessions.loc[sessions.index > daily.index.max()]
    if additions.empty:
        return daily
    return _normalize(pd.concat([daily, additions]).sort_index())


def _adjust_detected_splits(frame: pd.DataFrame) -> pd.DataFrame:
    """Anchor obvious stock splits to current prices when the source only offers raw OHLC."""
    adjusted = frame.copy()
    split_sizes = (2, 3, 4, 5, 7, 8, 10, 20)
    for index in range(1, len(frame)):
        previous_close = float(frame["close"].iloc[index - 1])
        current_open = float(frame["open"].iloc[index])
        if previous_close <= 0 or current_open <= 0:
            continue
        ratio = current_open / previous_close
        matched_ratio: float | None = None
        for size in split_sizes:
            for candidate in (1 / size, float(size)):
                if abs(ratio / candidate - 1) <= 0.08:
                    matched_ratio = candidate
                    break
            if matched_ratio is not None:
                break
        if matched_ratio is None:
            continue
        historical = adjusted.index < frame.index[index]
        adjusted.loc[historical, ["open", "high", "low", "close"]] *= matched_ratio
        adjusted.loc[historical, "volume"] /= matched_ratio
    return adjusted


class SinaProvider(MarketDataProvider):
    """Broad public-market fallback used when Yahoo is blocked or rate-limited."""

    name = "sina"
    US_DAILY_URL = (
        "https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK"
    )
    US_MINUTE_URL = (
        "https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getMinK"
    )
    CN_KLINE_URL = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
    FOREX_DAY_URL = (
        "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_atlas=/"
        "NewForexService.getDayKLine"
    )
    FOREX_MINUTE_URL = (
        "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_atlas=/"
        "NewForexService.getMinKline"
    )
    FUTURES_DAY_URL = (
        "https://stock2.finance.sina.com.cn/futures/api/json.php/"
        "GlobalFuturesService.getGlobalFuturesDailyKLine"
    )
    FUTURES_MINUTE_URL = "https://gu.sina.cn/ft/api/json_v2.php/GlobalService.getMink"
    DEFAULT_LIMIT = {"15m": 1000, "1h": 1000, "4h": 900, "1d": 2600, "1wk": 520}

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=18,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AtlasQuant/1.0",
                "Referer": "https://finance.sina.com.cn/",
            },
        )

    def _get(self, url: str, params: dict[str, str | int]) -> httpx.Response:
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response
        except Exception as exc:
            raise ProviderError(f"新浪行情请求失败: {exc}") from exc

    @staticmethod
    def _us_symbol(asset: Asset) -> str:
        return (asset.provider_symbol or asset.symbol).split(".")[0].upper()

    @staticmethod
    def _cn_symbol(asset: Asset) -> str:
        code = asset.symbol.split(".")[0]
        return f"{'sh' if asset.exchange == 'SSE' else 'sz'}{code}"

    @staticmethod
    def _forex_symbol(asset: Asset) -> str:
        code = (asset.provider_symbol or asset.symbol).upper().replace("=X", "").replace("/", "")
        if len(code) == 3:
            code = f"USD{code}"
        return f"fx_s{code.lower()}"

    @staticmethod
    def _future_symbol(asset: Asset) -> str:
        return (asset.provider_symbol or asset.symbol).upper().replace("=F", "")

    def _fetch_us(self, asset: Asset, interval: str, adjustment: str) -> pd.DataFrame:
        symbol = self._us_symbol(asset)
        if interval in {"1d", "1wk"}:
            payload = self._get(self.US_DAILY_URL, {"symbol": symbol}).json()
            frame = _records_frame(
                payload,
                {"d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
                "America/New_York",
            )
            if adjustment != "raw":
                frame = _adjust_detected_splits(frame)
            try:
                recent = self._get(self.US_MINUTE_URL, {"symbol": symbol, "type": "60"}).json()
                recent_frame = _records_frame(
                    recent,
                    {
                        "d": "date",
                        "o": "open",
                        "h": "high",
                        "l": "low",
                        "c": "close",
                        "v": "volume",
                    },
                    "America/New_York",
                )
                frame = _append_latest_sessions(frame, recent_frame, "America/New_York")
            except (ProviderError, ValueError, TypeError):
                pass
            return _resample_ohlcv(frame, "W-FRI") if interval == "1wk" else frame
        minute_type = "15" if interval == "15m" else "60"
        payload = self._get(self.US_MINUTE_URL, {"symbol": symbol, "type": minute_type}).json()
        frame = _records_frame(
            payload,
            {"d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
            "America/New_York",
        )
        return _resample_ohlcv(frame, "4h") if interval == "4h" else frame

    def _fetch_cn(self, asset: Asset, interval: str) -> pd.DataFrame:
        scale = 15 if interval == "15m" else 60 if interval in {"1h", "4h"} else 240
        payload = self._get(
            self.CN_KLINE_URL,
            {"symbol": self._cn_symbol(asset), "scale": scale, "ma": "no", "datalen": 1000},
        ).json()
        frame = _records_frame(
            payload,
            {
                "day": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
            "Asia/Shanghai",
        )
        if interval == "1wk":
            return _resample_ohlcv(frame, "W-FRI")
        return _resample_ohlcv(frame, "4h") if interval == "4h" else frame

    def _fetch_forex(self, asset: Asset, interval: str) -> pd.DataFrame:
        symbol = self._forex_symbol(asset)
        if interval in {"1d", "1wk"}:
            response = self._get(self.FOREX_DAY_URL, {"symbol": symbol})
            match = re.search(r'\("(.*)"\)', response.text, flags=re.DOTALL)
            if not match:
                raise ProviderError("新浪外汇日线格式无法解析")
            rows = [row.split(",") for row in match.group(1).split("|") if row.strip()]
            frame = _records_frame(
                rows, ["date", "open", "low", "high", "close", "volume"], "Asia/Shanghai"
            )
            try:
                recent_text = self._get(
                    self.FOREX_MINUTE_URL,
                    {"symbol": symbol, "scale": 60, "datalen": 48},
                ).text
                recent_match = re.search(
                    r"=\((\[.*\])\)\s*;?$", recent_text.strip(), flags=re.DOTALL
                )
                if recent_match:
                    import json

                    recent_frame = _records_frame(
                        json.loads(recent_match.group(1)),
                        {
                            "d": "date",
                            "o": "open",
                            "h": "high",
                            "l": "low",
                            "c": "close",
                            "v": "volume",
                        },
                        "Asia/Shanghai",
                    )
                    frame = _append_latest_sessions(frame, recent_frame, "Asia/Shanghai")
            except (ProviderError, ValueError, TypeError):
                pass
            return _resample_ohlcv(frame, "W-FRI") if interval == "1wk" else frame
        payload = self._get(
            self.FOREX_MINUTE_URL,
            {"symbol": symbol, "scale": 15 if interval == "15m" else 60, "datalen": 1023},
        ).text
        match = re.search(r"=\((\[.*\])\)\s*;?$", payload.strip(), flags=re.DOTALL)
        if not match:
            raise ProviderError("新浪外汇分钟线格式无法解析")
        import json

        frame = _records_frame(
            json.loads(match.group(1)),
            {"d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
            "Asia/Shanghai",
        )
        return _resample_ohlcv(frame, "4h") if interval == "4h" else frame

    def _fetch_future(self, asset: Asset, interval: str) -> pd.DataFrame:
        symbol = self._future_symbol(asset)
        if interval in {"1d", "1wk"}:
            payload = self._get(self.FUTURES_DAY_URL, {"symbol": symbol}).json()
            frame = _records_frame(
                payload,
                {
                    "date": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
                "Asia/Shanghai",
            )
            try:
                recent = self._get(self.FUTURES_MINUTE_URL, {"symbol": symbol, "type": 60}).json()
                recent_frame = _records_frame(
                    recent,
                    {
                        "d": "date",
                        "o": "open",
                        "h": "high",
                        "l": "low",
                        "c": "close",
                        "v": "volume",
                    },
                    "Asia/Shanghai",
                )
                frame = _append_latest_sessions(frame, recent_frame, "Asia/Shanghai")
            except (ProviderError, ValueError, TypeError):
                pass
            return _resample_ohlcv(frame, "W-FRI") if interval == "1wk" else frame
        payload = self._get(
            self.FUTURES_MINUTE_URL,
            {"symbol": symbol, "type": 15 if interval == "15m" else 60},
        ).json()
        frame = _records_frame(
            payload,
            {"d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
            "Asia/Shanghai",
        )
        return _resample_ohlcv(frame, "4h") if interval == "4h" else frame

    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        if asset.exchange in {"NASDAQ", "NYSE Arca", "GLOBAL"} and asset.asset_class in {
            "equity",
            "etf",
        }:
            frame = self._fetch_us(asset, interval, adjustment)
        elif asset.exchange in {"SSE", "SZSE"}:
            frame = self._fetch_cn(asset, interval)
        elif asset.asset_class == "forex":
            frame = self._fetch_forex(asset, interval)
        elif asset.asset_class == "commodity":
            frame = self._fetch_future(asset, interval)
        else:
            raise ProviderError(f"新浪行情暂不支持 {asset.symbol}")
        if start is not None:
            frame = frame.loc[frame.index >= pd.Timestamp(start)]
        if end is not None:
            frame = frame.loc[frame.index <= pd.Timestamp(end)]
        if start is None and end is None:
            frame = frame.tail(self.DEFAULT_LIMIT[interval])
        return _normalize(frame)


class TencentProvider(MarketDataProvider):
    """Hong Kong daily history plus recent minute bars."""

    name = "tencent"
    KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
    MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/day/query"
    EASTMONEY_MINUTE_URL = "https://33.push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=18, follow_redirects=True)

    @staticmethod
    def _symbol(asset: Asset) -> str:
        if asset.symbol == "^HSI":
            return "hkHSI"
        return f"hk{asset.symbol.split('.')[0].zfill(5)}"

    @staticmethod
    def _eastmoney_symbol(asset: Asset) -> str:
        if asset.symbol == "^HSI":
            return "100.HSI"
        return f"116.{asset.symbol.split('.')[0].zfill(5)}"

    def _fetch_eastmoney_minutes(
        self, asset: Asset, interval: str, adjustment: str
    ) -> pd.DataFrame:
        try:
            response = self.client.get(
                self.EASTMONEY_MINUTE_URL,
                params={
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "ut": "7eea3edcaed734bea9cbfc24409ed989",
                    "klt": "15" if interval == "15m" else "60",
                    "fqt": "0" if adjustment == "raw" else "1",
                    "secid": self._eastmoney_symbol(asset),
                    "beg": "0",
                    "end": "20500101",
                },
            )
            response.raise_for_status()
            records = (response.json().get("data") or {}).get("klines") or []
        except Exception as exc:
            raise ProviderError(f"东方财富港股分钟行情请求失败: {exc}") from exc
        rows = [str(record).split(",") for record in records]
        frame = _records_frame(
            rows,
            ["date", "open", "close", "high", "low", "volume"],
            "Asia/Hong_Kong",
        )
        return _resample_ohlcv(frame, "4h") if interval == "4h" else frame

    def _fetch_minutes(self, symbol: str, interval: str) -> pd.DataFrame:
        try:
            response = self.client.get(self.MINUTE_URL, params={"code": symbol})
            response.raise_for_status()
            sessions = response.json().get("data", {}).get(symbol, {}).get("data", [])
        except Exception as exc:
            raise ProviderError(f"腾讯港股分钟行情请求失败: {exc}") from exc
        records: list[dict[str, str | float]] = []
        for session in sessions:
            date = str(session.get("date", ""))
            previous_volume = 0.0
            for row in session.get("data", []):
                parts = str(row).split()
                if len(parts) < 3:
                    continue
                cumulative_volume = float(parts[2])
                volume = max(0.0, cumulative_volume - previous_volume)
                previous_volume = cumulative_volume
                records.append(
                    {
                        "date": f"{date} {parts[0]}",
                        "open": parts[1],
                        "high": parts[1],
                        "low": parts[1],
                        "close": parts[1],
                        "volume": volume,
                    }
                )
        frame = _records_frame(
            records,
            {
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
            "Asia/Hong_Kong",
        )
        frequency = {"15m": "15min", "1h": "1h", "4h": "4h"}[interval]
        return _resample_ohlcv(frame, frequency)

    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        if asset.exchange != "HKEX":
            raise ProviderError(f"腾讯港股行情不支持 {asset.symbol}")
        symbol = self._symbol(asset)
        if interval in {"15m", "1h", "4h"}:
            try:
                frame = self._fetch_eastmoney_minutes(asset, interval, adjustment)
            except ProviderError:
                frame = self._fetch_minutes(symbol, interval)
            if start is not None:
                frame = frame.loc[frame.index >= pd.Timestamp(start)]
            if end is not None:
                frame = frame.loc[frame.index <= pd.Timestamp(end)]
            return _normalize(frame)
        try:
            response = self.client.get(self.KLINE_URL, params={"param": f"{symbol},day,,,1000"})
            response.raise_for_status()
            root = response.json().get("data", {}).get(symbol, {})
        except Exception as exc:
            raise ProviderError(f"腾讯港股行情请求失败: {exc}") from exc
        records = root.get("qfqday") or root.get("day") or []
        frame = _records_frame(
            records,
            ["date", "open", "close", "high", "low", "volume"],
            "Asia/Hong_Kong",
        )
        if interval == "1wk":
            frame = _resample_ohlcv(frame, "W-FRI")
        if start is not None:
            frame = frame.loc[frame.index >= pd.Timestamp(start)]
        if end is not None:
            frame = frame.loc[frame.index <= pd.Timestamp(end)]
        return _normalize(frame.tail(2600 if interval == "1d" else 520))


class BinanceProvider(MarketDataProvider):
    name = "binance"
    BASE_URL = "https://api.binance.com/api/v3/klines"
    INTERVAL_MAP = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1wk": "1w"}

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=12, follow_redirects=True)

    @staticmethod
    def _symbol(asset: Asset) -> str:
        symbol = (asset.provider_symbol or asset.symbol).upper().replace("-", "")
        if symbol.endswith("USD") and not symbol.endswith("USDT"):
            symbol = f"{symbol[:-3]}USDT"
        return symbol

    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        start_ms = int(start.timestamp() * 1000) if start else None
        end_ms = int(end.timestamp() * 1000) if end else int(datetime.now(UTC).timestamp() * 1000)
        rows: list[list] = []
        cursor = start_ms
        for _ in range(20):
            params: dict[str, str | int] = {
                "symbol": self._symbol(asset),
                "interval": self.INTERVAL_MAP[interval],
                "limit": 1000,
            }
            if cursor is not None:
                params["startTime"] = cursor
            if end_ms is not None:
                params["endTime"] = end_ms
            try:
                response = self.client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                batch = response.json()
            except Exception as exc:
                raise ProviderError(f"Binance 行情请求失败: {exc}") from exc
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + 1
            if len(batch) < 1000 or (end_ms is not None and next_cursor >= end_ms):
                break
            cursor = next_cursor
        if not rows:
            raise ProviderError("Binance 没有返回行情，请检查交易对")
        frame = pd.DataFrame(
            rows,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_base",
                "taker_quote",
                "ignore",
            ],
        )
        frame.index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        return _normalize(frame[["open", "high", "low", "close", "volume"]])


class DemoProvider(MarketDataProvider):
    """Deterministic, clearly-labelled data for offline use and tests."""

    name = "demo"
    FREQUENCY = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D", "1wk": "7D"}
    DEFAULT_PERIODS = {"15m": 900, "1h": 1000, "4h": 900, "1d": 900, "1wk": 520}

    def fetch_bars(
        self,
        asset: Asset,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        adjustment: str,
    ) -> pd.DataFrame:
        end_ts = pd.Timestamp(end or datetime.now(UTC))
        end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
        floor_frequency = {
            "15m": "15min",
            "1h": "1h",
            "4h": "4h",
            "1d": "1D",
            "1wk": "1D",
        }[interval]
        end_ts = end_ts.floor(floor_frequency)
        periods = self.DEFAULT_PERIODS[interval]
        index = pd.date_range(end=end_ts, periods=periods, freq=self.FREQUENCY[interval], tz="UTC")
        if start:
            start_ts = pd.Timestamp(start)
            start_ts = (
                start_ts.tz_localize("UTC")
                if start_ts.tzinfo is None
                else start_ts.tz_convert("UTC")
            )
            index = index[index >= start_ts]
        seed = int(hashlib.sha256(asset.symbol.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        drift = 0.00035 if asset.asset_class == "crypto" else 0.00018
        volatility = 0.025 if asset.asset_class == "crypto" else 0.012
        log_returns = rng.normal(drift, volatility, len(index))
        cycle = np.sin(np.arange(len(index)) / 42) * volatility * 0.35
        close = 100 * np.exp(np.cumsum(log_returns + cycle))
        open_price = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, volatility / 8, len(index)))
        spread = np.abs(rng.normal(volatility / 2, volatility / 5, len(index)))
        high = np.maximum(open_price, close) * (1 + spread)
        low = np.minimum(open_price, close) * (1 - spread)
        volume = rng.lognormal(mean=13, sigma=0.55, size=len(index))
        return pd.DataFrame(
            {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
            index=index,
        )
