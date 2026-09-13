"""Exercise authenticated strategy and proof uploads through the merged middleware."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.journal.router import _attempts
from tests.test_integrated_api import registered
from tests.test_quantjudge import create_agent
from tests.test_strategy_studio import package_bytes


@pytest.fixture
def owner():
    _attempts.clear()
    client, _, _ = registered()
    agent = create_agent(main.quantjudge_store)
    yield client, agent["agent"]["id"], {"X-Developer-Token": agent["developer_token"]}
    client.close()


def test_historical_package_created_in_store_remains_downloadable(owner):
    client, agent_id, headers = owner
    content = package_bytes()
    endpoint = f"/api/v1/quantjudge/agents/{agent_id}/packages"
    package = main.strategy_studio_store.upload_package(
        agent_id, "historical.qstrategy", content, headers["X-Developer-Token"]
    )
    package_id = package["id"]
    downloaded = client.get(f"{endpoint}/{package_id}/download", headers=headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content


def test_package_upload_is_authenticated_and_reaches_validated_store(owner, monkeypatch):
    client, agent_id, headers = owner
    endpoint = f"/api/v1/quantjudge/agents/{agent_id}/packages"
    files = {"file": ("merge.qstrategy", package_bytes())}
    writes = []
    monkeypatch.setattr(
        main.strategy_studio_store,
        "upload_package",
        lambda *args: writes.append(args) or {"id": "test-package"},
    )

    with TestClient(main.app) as anonymous:
        assert anonymous.post(endpoint, headers=headers, files=files).status_code == 401
    assert client.post(endpoint, headers={**headers, "Origin": "https://other.example"}, files=files).status_code == 403
    response = client.post(endpoint, headers=headers, files=files)
    assert response.status_code == 201
    assert response.json() == {"id": "test-package"}
    assert len(writes) == 1
    assert writes[0][0] == agent_id
    assert writes[0][1] == "merge.qstrategy"
    assert writes[0][3] == headers["X-Developer-Token"]


def test_uploads_keep_json_boundaries(owner):
    client, _, _ = owner
    files = {"file": ("merge.qstrategy", package_bytes())}
    assert client.post("/api/v1/backtests", files=files).status_code == 415
    assert client.post("/api/v1/backtests", content=b"x" * 4_000_001, headers={"Content-Type": "application/json"}).status_code == 413


def test_zk_receipt_multipart_reaches_verifier(owner, monkeypatch):
    client, agent_id, headers = owner
    seen = []

    def register(*args):
        seen.append(args)
        return {"id": "test-transport-only"}

    monkeypatch.setattr(main.zk_proof_store, "register_receipt", register)
    result = client.post(
        f"/api/v1/quantjudge/agents/{agent_id}/zk-proofs?proof_profile=transport-test",
        headers=headers, files={"file": ("receipt.r0", b"test-receipt")},
    )
    assert result.status_code == 201, result.text
    assert seen == [(agent_id, "transport-test", b"test-receipt", headers["X-Developer-Token"])]
