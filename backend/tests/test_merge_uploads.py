"""Exercise uploads through the merged login middleware, not a standalone router."""

import secrets

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


def test_authenticated_package_upload_over_json_limit_and_download(owner):
    client, agent_id, headers = owner
    content = package_bytes({"README.md": secrets.token_hex(4_100_000)})
    assert 4_000_000 < len(content) < 10 * 1024 * 1024
    endpoint = f"/api/v1/quantjudge/agents/{agent_id}/packages"
    uploaded = client.post(endpoint, headers=headers, files={"file": ("merge.qstrategy", content)})
    assert uploaded.status_code == 201, uploaded.text
    package_id = uploaded.json()["id"]
    downloaded = client.get(f"{endpoint}/{package_id}/download", headers=headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content


def test_uploads_keep_login_origin_token_and_json_boundaries(owner):
    client, agent_id, headers = owner
    endpoint = f"/api/v1/quantjudge/agents/{agent_id}/packages"
    files = {"file": ("merge.qstrategy", package_bytes())}
    with TestClient(main.app) as anonymous:
        assert anonymous.post(endpoint, headers=headers, files=files).status_code == 401
    assert client.post(endpoint, files=files).status_code == 401
    assert client.post(endpoint, headers={**headers, "Origin": "https://other.example"}, files=files).status_code == 403
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
