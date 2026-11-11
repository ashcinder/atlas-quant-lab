from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.data.providers import NoMarketData, ProviderError


@pytest.fixture
def client():
    from app.journal.router import _attempts

    _attempts.clear()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/register",
            json={
                "email": f"{uuid4()}@example.test",
                "password": "test-password-123",
            },
        )
        assert response.status_code == 201
        yield client


@pytest.mark.parametrize(
    "interval,step",
    [
        ("1m", 60),
        ("5m", 300),
        ("15m", 900),
        ("1h", 3600),
        ("4h", 14400),
        ("1d", 86400),
        ("1wk", 604800),
    ],
)
def test_chart_history_exclusive_and_empty(client, monkeypatch, interval, step):
    monkeypatch.setenv("ATLAS_COMPUTE_MODE", "browser")
    before = 1705000000
    calls = []

    def fetch(asset, actual_interval, start, end, adjustment):
        calls.append((actual_interval, start, end))
        if len(calls) == 2:
            raise NoMarketData("empty")
        index = pd.to_datetime([before - 2 * step, before - step], unit="s", utc=True)
        return pd.DataFrame(
            {
                "open": [10.0, 10.0],
                "high": [12.0, 12.0],
                "low": [9.0, 9.0],
                "close": [11.0, 11.0],
                "volume": [2.0, 2.0],
            },
            index=index,
        )

    monkeypatch.setattr(main.data_service.providers["binance"], "fetch_bars", fetch)
    params = {"symbol": "BTC-USD", "interval": interval, "before": before}
    first = client.get("/api/v1/market/chart", params=params)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["source"] == "binance"
    assert [b["time"] for b in body["bars"]] == [before - 2 * step, before - step]
    assert calls[0][0] == interval and calls[0][1] is None
    assert calls[0][2].timestamp() == before - 0.001
    second = client.get("/api/v1/market/chart", params=params)
    assert second.status_code == 200 and second.json()["bars"] == []


def test_chart_failures_are_not_reported_as_history_end(client, monkeypatch):
    def fail(*args):
        raise ProviderError("offline")

    monkeypatch.setattr(main.data_service.providers["binance"], "fetch_bars", fail)
    response = client.get("/api/v1/market/chart", params={"symbol": "BTC-USD", "interval": "1m"})
    assert response.status_code == 502
    assert response.json()["detail"] == "offline"
