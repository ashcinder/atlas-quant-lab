from datetime import UTC, datetime
from threading import BoundedSemaphore

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.data.providers import BinanceProvider, NoMarketData, ProviderError
from app.data.service import MarketDataService
from app.models import MarketDataResponse


class RecordingProvider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls = []

    def fetch_bars(self, asset, interval, start, end, adjustment):
        self.calls.append((asset, interval, start, end, adjustment))
        return self.frame


class ErrorProvider:
    def __init__(self, error: ProviderError):
        self.error = error
        self.calls = 0

    def fetch_bars(self, *_args):
        self.calls += 1
        raise self.error


class EmptyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return []


class EmptyClient:
    def get(self, *_args, **_kwargs):
        return EmptyResponse()


def frame(periods: int) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=periods, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000.0,
        },
        index=index,
    )


@pytest.fixture
def history_client(tmp_path, monkeypatch):
    service = MarketDataService(tmp_path / "cache")
    provider = RecordingProvider(frame(1))
    service.providers["binance"] = provider
    monkeypatch.setattr(main, "data_service", service)
    app = FastAPI()
    app.get("/bars", response_model=MarketDataResponse)(main.market_bars)
    with TestClient(app) as client:
        yield client, service, provider


def test_bounded_history_normalizes_and_forwards_window(history_client):
    client, service, provider = history_client
    response = client.get(
        "/bars",
        params={
            "source": "auto",
            "provider": "binance",
            "interval": "1h",
            "start": "2025-01-01T08:00:00+08:00",
            "end": "2025-01-01T03:00:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["bars"]) == 1
    _, interval, start, end, _ = provider.calls[-1]
    assert interval == "1h"
    assert start == datetime(2025, 1, 1, tzinfo=UTC)
    assert end == datetime(2025, 1, 1, 3, tzinfo=UTC)
    with service.store.connect() as database:
        assert database.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2025-01-01T00:00:00Z"},
        {"end": "2025-01-02T00:00:00Z"},
        {"start": "2025-01-02T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
        {"start": "2025-01-01T00:00:00Z", "end": "2025-02-22T02:00:00Z"},
        {"start": "2025-01-01T00:00:00Z", "end": "2025-02-22T02:15:00Z"},
    ],
)
def test_invalid_history_windows_are_rejected(history_client, params):
    client, _, provider = history_client
    response = client.get(
        "/bars", params={"source": "binance", "interval": "15m", **params}
    )

    assert response.status_code == 422
    assert provider.calls == []


def test_unbounded_market_request_keeps_default_minimum(history_client):
    client, _, provider = history_client
    provider.frame = frame(30)

    response = client.get("/bars", params={"source": "binance", "interval": "1h"})

    assert response.status_code == 200, response.text
    assert len(response.json()["bars"]) == 30
    _, _, start, end, _ = provider.calls[-1]
    assert start is None
    assert end is None


def test_locked_sina_empty_window_does_not_fall_back_to_yahoo(history_client):
    client, service, _ = history_client
    sina = ErrorProvider(NoMarketData("新浪在请求区间没有行情"))
    yahoo = ErrorProvider(ProviderError("不应调用Yahoo"))
    service.providers["sina"] = sina
    service.providers["yahoo"] = yahoo

    response = client.get(
        "/bars",
        params={
            "symbol": "AAPL",
            "asset_class": "equity",
            "interval": "1d",
            "source": "auto",
            "provider": "sina",
            "start": "2010-01-01T00:00:00Z",
            "end": "2010-01-10T00:00:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["bars"] == []
    assert response.json()["source"] == "sina"
    assert "没有行情" in response.json()["source_note"]
    assert sina.calls == 1
    assert yahoo.calls == 0


def test_binance_successful_empty_rows_return_empty_window(history_client):
    client, service, _ = history_client
    provider = BinanceProvider()
    provider.client = EmptyClient()
    service.providers["binance"] = provider

    response = client.get(
        "/bars",
        params={
            "source": "auto",
            "provider": "binance",
            "interval": "1h",
            "start": "2010-01-01T00:00:00Z",
            "end": "2010-01-01T03:00:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["bars"] == []
    assert response.json()["last_bar_time"] == int(
        datetime(2010, 1, 1, 3, tzinfo=UTC).timestamp()
    )


def test_locked_provider_network_failure_remains_502(history_client):
    client, service, _ = history_client
    service.providers["binance"] = ErrorProvider(ProviderError("网络不可用"))

    response = client.get(
        "/bars",
        params={
            "source": "auto",
            "provider": "binance",
            "interval": "1h",
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T03:00:00Z",
        },
    )

    assert response.status_code == 502
    assert "网络不可用" in response.json()["detail"]


def test_provider_hint_locks_non_default_feed(history_client):
    client, service, _ = history_client
    sina = ErrorProvider(ProviderError("不应调用新浪"))
    yahoo = RecordingProvider(frame(1))
    service.providers["sina"] = sina
    service.providers["yahoo"] = yahoo

    response = client.get(
        "/bars",
        params={
            "symbol": "AAPL",
            "asset_class": "equity",
            "interval": "1h",
            "source": "auto",
            "provider": "yahoo",
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T03:00:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "yahoo"
    assert len(yahoo.calls) == 1
    assert sina.calls == 0


def test_auto_source_preserves_empty_type_only_when_all_candidates_are_empty(
    history_client,
):
    _, service, _ = history_client
    service.providers["sina"] = ErrorProvider(NoMarketData("新浪无数据"))
    service.providers["yahoo"] = ErrorProvider(NoMarketData("Yahoo无数据"))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 2, tzinfo=UTC)

    with pytest.raises(NoMarketData):
        service.fetch(
            "AAPL",
            "equity",
            "1h",
            start,
            end,
            source="auto",
            minimum_bars=1,
            cache_history=False,
        )

    service.providers["yahoo"] = ErrorProvider(ProviderError("Yahoo网络错误"))
    with pytest.raises(ProviderError) as failure:
        service.fetch(
            "AAPL",
            "equity",
            "1h",
            start,
            end,
            source="auto",
            minimum_bars=1,
            cache_history=False,
        )
    assert not isinstance(failure.value, NoMarketData)


def test_history_capacity_rejects_and_recovers_without_consuming_a_provider_call(history_client, monkeypatch):
    client, _, provider = history_client
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(main, "market_history_slots", slots)
    params = {"source": "binance", "interval": "1h", "start": "2025-01-01T00:00:00Z", "end": "2025-01-02T00:00:00Z"}
    assert slots.acquire(blocking=False)
    try:
        assert client.get("/bars", params=params).status_code == 429
        assert provider.calls == []
    finally:
        slots.release()
    assert client.get("/bars", params=params).status_code == 200
    assert slots.acquire(blocking=False)
    slots.release()
