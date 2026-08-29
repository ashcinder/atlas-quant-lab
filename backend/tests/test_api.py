from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_catalog():
    assert client.get("/api/v1/health").status_code == 200
    assets = client.get("/api/v1/assets/search", params={"q": "黄金"}).json()
    assert any(asset["symbol"] == "GC=F" for asset in assets)
    strategies = client.get("/api/v1/strategies", params={"mode": "single"}).json()
    assert len(strategies) >= 12
    dynamic = client.get("/api/v1/assets/search", params={"q": "TSLA"}).json()
    assert dynamic[0]["symbol"] == "TSLA"


def test_demo_market_and_backtest_endpoints():
    market = client.get(
        "/api/v1/market/bars",
        params={"symbol": "BTC-USD", "asset_class": "crypto", "interval": "1d", "source": "demo"},
    )
    assert market.status_code == 200, market.text
    market_payload = market.json()
    assert market_payload["source"] == "demo"
    assert market_payload["last_bar_time"] == market_payload["bars"][-1]["time"]
    assert market_payload["is_stale"] is False
    assert market_payload["source_note"] == "离线演示数据，不是真实行情"
    response = client.post(
        "/api/v1/backtests",
        json={
            "symbol": "BTC-USD",
            "asset_class": "crypto",
            "interval": "1d",
            "data_source": "demo",
            "strategy_id": "sma_cross",
            "params": {"fast": 12, "slow": 48},
            "persist": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metrics"]["trade_count"] > 0
    assert payload["trades"]


def test_portfolio_endpoint():
    response = client.post(
        "/api/v1/portfolio/backtests",
        json={
            "assets": [
                {"symbol": "SPY", "asset_class": "etf"},
                {"symbol": "TLT", "asset_class": "etf"},
                {"symbol": "IEF", "asset_class": "etf"},
                {"symbol": "GLD", "asset_class": "etf"},
                {"symbol": "DBC", "asset_class": "etf"},
            ],
            "strategy_id": "all_weather",
            "data_source": "demo",
            "persist": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert abs(sum(payload["weights"].values()) - 1) < 0.02
    assert payload["metrics"]["trade_count"] > 0
    assert payload["metrics"]["trade_count"] < 100
    assert 8 <= len(payload["weight_history"]) <= 20


def test_quantjudge_public_market_and_receipt_verification():
    overview = client.get("/api/v1/quantjudge/overview")
    assert overview.status_code == 200
    assert overview.json()["agents"] >= 6

    agents = client.get("/api/v1/quantjudge/agents", params={"report_type": "live"})
    assert agents.status_code == 200
    payload = agents.json()
    assert payload
    assert all(agent["latest_report"]["report_type"] == "live" for agent in payload)
    assert all("developer_token" not in agent for agent in payload)

    receipt_id = payload[0]["latest_report"]["id"]
    verification = client.get(
        f"/api/v1/quantjudge/reports/{receipt_id}/verify", params={"refresh_chain": False}
    )
    assert verification.status_code == 200
    assert verification.json()["attestation_signature_valid"] is True
    assert verification.json()["chain"]["status"] == "not_anchored"
