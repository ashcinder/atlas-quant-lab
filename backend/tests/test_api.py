import pytest
from fastapi.testclient import TestClient
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


def test_workflow_api_accepts_returned_id_for_subsequent_revision(client):
    from app.strategy_studio import workflow_templates

    workflow = workflow_templates()[0]["workflow"]
    agent_input = {
        "name": "Workflow revision contract",
        "developer_alias": "Test author",
        "category": "allocation",
        "asset_classes": ["crypto"],
        "description": "A test identity for saving and reading independent workflow revisions.",
        "strategy_commitment": "e" * 64,
    }
    results = []
    for _ in range(2):
        created = client.post("/api/v1/quantjudge/agents", json=agent_input)
        assert created.status_code == 201
        agent = created.json()
        path = f"/api/v1/quantjudge/agents/{agent['agent']['id']}/workflows/"
        headers = {"X-Developer-Token": agent["developer_token"]}
        initial = client.put(path + workflow["id"], headers=headers, json={"workflow": workflow})
        assert initial.status_code == 200
        results.append(initial.json())

    first, second = results
    assert first["id"] != second["id"]
    assert first["revision"] == second["revision"] == 1
    payload = {"workflow": {**workflow, "name": "Second author's revised workflow"}}
    scoped_path = path + second["id"]
    revised = client.put(scoped_path, headers=headers, json=payload)
    assert revised.status_code == 200
    assert revised.json()["revision"] == 2
    assert client.get(scoped_path, headers=headers).json() == revised.json()
    assert client.put(path + first["id"] + "-other", headers=headers, json=payload).status_code == 422
    created_project = client.post("/api/v1/strategy-projects", json={
        "name": "Scoped workflow project",
        "thesis": "Confirm that a scoped workflow can be linked to a strategy project.",
        "asset_symbol": "BTC-USD",
        "asset_class": "crypto",
    })
    assert created_project.status_code == 201
    project = created_project.json()
    linked = client.post(
        f"/api/v1/strategy-projects/{project['id']}/artifacts",
        headers=headers,
        json={"expected_revision": project["revision"], "kind": "workflow", "artifact_id": second["id"]},
    )
    assert linked.status_code == 200
    assert linked.json()["workflow_id"] == second["id"]
    assert linked.json()["workflow_revision"] == 2


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
    from app.main import quantjudge_store
    from tests.test_quantjudge import create_agent, make_report

    created = create_agent(quantjudge_store)
    report = quantjudge_store.publish_report(
        created["agent"]["id"], make_report(), created["developer_token"]
    )
    overview = client.get("/api/v1/quantjudge/overview")
    assert overview.status_code == 200
    assert overview.json()["agents"] >= 1

    agents = client.get("/api/v1/quantjudge/agents", params={"report_type": "live"})
    assert agents.status_code == 200
    payload = agents.json()
    assert payload
    assert all(agent["latest_report"]["report_type"] == "live" for agent in payload)
    assert all("developer_token" not in agent for agent in payload)

    assert any(agent["id"] == created["agent"]["id"] for agent in payload)
    receipt_id = report["id"]
    verification = client.get(
        f"/api/v1/quantjudge/reports/{receipt_id}/verify", params={"refresh_chain": False}
    )
    assert verification.status_code == 200
    assert verification.json()["attestation_signature_valid"] is True
    assert verification.json()["chain"]["status"] == "not_anchored"
