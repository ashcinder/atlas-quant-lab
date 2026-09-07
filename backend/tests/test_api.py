from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    client = TestClient(app)
    from app.journal.router import _attempts

    _attempts.clear()
    response = client.post(
        "/api/register", json={"email": f"{uuid4()}@example.test", "password": "test-password-123"}
    )
    assert response.status_code == 201, response.text
    yield client
    client.close()


def test_health_and_catalog(client):
    assert client.get("/api/v1/health").status_code == 200
    assets = client.get("/api/v1/assets/search", params={"q": "黄金"}).json()
    assert any(asset["symbol"] == "GC=F" for asset in assets)
    strategies = client.get("/api/v1/strategies", params={"mode": "single"}).json()
    assert len(strategies) >= 12
    dynamic = client.get("/api/v1/assets/search", params={"q": "TSLA"}).json()
    assert dynamic[0]["symbol"] == "TSLA"


def test_demo_market_and_backtest_endpoints(client):
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
    assert payload["valuation_currency"] == "USD"
    assert payload["metrics"]["trade_count"] > 0
    assert payload["trades"]


@pytest.mark.parametrize("base_currency", ["CNY", "USD"])
def test_portfolio_endpoint(client, base_currency):
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
            "base_currency": base_currency,
            "persist": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valuation_currency"] == base_currency
    assert {asset["currency"] for asset in payload["assets"]} == {base_currency}
    assert abs(sum(payload["weights"].values()) - 1) < 0.02
    assert payload["metrics"]["trade_count"] > 0
    assert payload["metrics"]["trade_count"] < 100
    assert 8 <= len(payload["weight_history"]) <= 20


def test_invalid_strategy_parameters_return_actionable_validation_error(client):
    response = client.post(
        "/api/v1/backtests",
        json={
            "symbol": "BTC-USD",
            "asset_class": "crypto",
            "data_source": "demo",
            "strategy_id": "dca",
            "params": {"every_bars": 0},
            "persist": False,
        },
    )
    assert response.status_code == 422
    assert "投入间隔" in response.json()["detail"]


def test_api_stores_use_isolated_test_storage():
    from app import main
    from app.config import DATA_DIR, DB_PATH

    assert DATA_DIR.name.startswith("atlas-backend-tests-")
    assert DB_PATH.parent == DATA_DIR
    for store in (
        main.run_store,
        main.workspace_store,
        main.research_service,
        main.quantjudge_store,
        main.zk_proof_store,
        main.strategy_studio_store,
        main.strategy_project_store,
    ):
        assert store.path == DB_PATH
    for path in (
        main.data_service.cache_dir,
        main.fundamentals_service.cache_dir,
        main.quantjudge_store.attestor.key_path,
        main.zk_proof_store.receipt_root,
        main.zk_proof_store.market_root,
        main.strategy_studio_store.artifacts.root,
        main.strategy_studio_store.artifacts.key_path,
    ):
        assert path.is_relative_to(DATA_DIR)


def test_quantjudge_public_market_and_receipt_verification(client):
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
