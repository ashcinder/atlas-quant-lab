import pytest

from app.main import quantjudge_store
from app.quantjudge_models import QuantAgentCreate
from tests.test_integrated_api import registered
from tests.test_strategy_projects import custom_strategy
from tests.test_strategy_studio import package_bytes


def create_private_agent(store):
    created = store.create_agent(
        QuantAgentCreate(
            name="Merge fixture",
            developer_alias="Fixture",
            category="allocation",
            asset_classes=["crypto"],
            description="Private fixture for account and multipart integration boundaries.",
            strategy_commitment="ab" * 32,
        )
    )
    return created["agent"], created["developer_token"]


@pytest.fixture
def accounts():
    from app.journal.router import _attempts

    _attempts.clear()
    first, _, _ = registered()
    second, _, _ = registered()
    yield first, second
    first.close()
    second.close()


def test_project_and_artifact_ownership(accounts):
    first, second = accounts
    payload = {
        "name": "Private hypothesis",
        "thesis": "Only this account should see this hypothesis.",
        "asset_symbol": "BTC-USD",
        "asset_class": "crypto",
    }
    project = first.post("/api/v1/strategy-projects", json=payload).json()
    path = f"/api/v1/strategy-projects/{project['id']}"
    assert project["id"] not in {p["id"] for p in second.get("/api/v1/strategy-projects").json()}
    assert second.get(path).status_code == 404
    assert second.patch(path, json={"expected_revision": 1, "name": "Stolen"}).status_code == 404
    assert (
        second.post(path + "/freeze", json={"expected_revision": 1, "version": "1.0.0"}).status_code
        == 404
    )
    strategy = custom_strategy().model_dump(mode="json")
    assert (
        second.put(f"/api/v1/custom-strategies/{strategy['id']}", json=strategy).status_code == 200
    )
    link = {"expected_revision": 1, "kind": "strategy", "artifact_id": strategy["id"]}
    assert first.post(path + "/artifacts", json=link).status_code == 422
    strategy["name"] = "My isolated same-ID template"
    assert (
        first.put(f"/api/v1/custom-strategies/{strategy['id']}", json=strategy).status_code == 200
    )
    assert first.post(path + "/artifacts", json=link).status_code == 200


def test_authenticated_multipart_upload_and_private_artifact_binding(accounts):
    first, second = accounts
    agent, token = create_private_agent(quantjudge_store)
    headers = {"X-Developer-Token": token}
    path = f"/api/v1/quantjudge/agents/{agent['id']}"
    response = first.post(
        path + "/packages",
        headers=headers,
        files={"file": ("strategy.qstrategy", package_bytes(), "application/zip")},
    )
    assert response.status_code == 201, response.text
    package = response.json()
    project = second.post(
        "/api/v1/strategy-projects",
        json={
            "name": "Package project",
            "thesis": "Private artifacts require their independent capability token.",
            "asset_symbol": "BTC-USD",
            "asset_class": "crypto",
        },
    ).json()
    link = {"expected_revision": 1, "kind": "package", "artifact_id": package["id"]}
    target = f"/api/v1/strategy-projects/{project['id']}/artifacts"
    assert second.post(target, json=link).status_code == 422
    assert second.post(target, json=link, headers=headers).status_code == 200
    # JSON-only middleware must not reject valid multipart before the verifier.
    response = first.post(
        path + "/zk-proofs?proof_profile=atlas_program_backtest_risc0_v2",
        headers=headers,
        files={"file": ("invalid.r0", b"invalid-receipt", "application/octet-stream")},
    )
    assert response.status_code in {422, 503}, response.text
    assert (
        first.put(
            "/api/ledger", content=b"x", headers={"Content-Type": "multipart/form-data"}
        ).status_code
        == 415
    )


def test_subscription_alias_does_not_grant_cross_account_access(accounts):
    first, second = accounts
    agent, _ = create_private_agent(quantjudge_store)
    response = first.post(
        f"/api/v1/quantjudge/agents/{agent['id']}/subscriptions",
        json={"investor_alias": "shared-public-name"},
    )
    assert response.status_code == 201
    params = {"investor_alias": "shared-public-name"}
    assert len(first.get("/api/v1/quantjudge/subscriptions", params=params).json()) == 1
    assert second.get("/api/v1/quantjudge/subscriptions", params=params).json() == []
