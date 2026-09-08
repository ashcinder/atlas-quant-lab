import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai_runtime import LocalAIGuard
from app.execution import run_private_strategy
from app.execution_api import execution_router
from app.execution_models import ExecutionRequest
from app.sandbox import DockerSandbox, RunnerFailure, RunnerUnavailable
from tests.test_strategy_studio import create_private_agent, package_bytes


def dataset():
    return {
        "symbol": "BTC-USD",
        "interval": "1d",
        "bars": [
            {
                "time": 1700000000 + i * 86400,
                "open_micros": 100_000_000,
                "close_micros": (100 + i) * 1_000_000,
                "high_micros": 120_000_000,
                "low_micros": 90_000_000,
                "volume_micros": 100_000_000_000,
            }
            for i in range(5)
        ],
    }


class ProposalSandbox:
    seen = []
    target = 1.0

    def __init__(self, archive, parameters):
        self.seen.clear()
        assert parameters == {"lookback": 20}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def exchange(self, message):
        assert all(b["time"] <= message["time"] for b in message["bars"])
        self.seen.append(len(message["bars"]))
        return {"targets": [{"symbol": "BTC-USD", "target_weight": self.target}]}


def request(**kwargs):
    return ExecutionRequest(market_data_hash="ab" * 32, acknowledge_host_visibility=True, **kwargs)


def test_causal_execution_host_accounting_and_no_proof_upgrade():
    result = run_private_strategy(
        package_bytes(), dataset(), request(), sandbox_factory=ProposalSandbox
    )
    assert ProposalSandbox.seen == [1, 2, 3, 4]
    assert result["metrics"]["trade_count"] > 0
    assert result["evidence_level"] == "sandbox_research"
    assert not result["zk_verified"] and not result["tee_verified"]
    assert not result["operator_confidential"]
    assert "strategy.py" not in json.dumps(result)
    assert "parameters" not in result


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.1])
def test_rejects_malicious_proposals(value):
    class Invalid(ProposalSandbox):
        target = value

    with pytest.raises(ValueError):
        run_private_strategy(package_bytes(), dataset(), request(), sandbox_factory=Invalid)


def test_bad_parameters_and_missing_privacy_consent():
    with pytest.raises(RunnerFailure, match="确认"):
        run_private_strategy(
            package_bytes(), dataset(), ExecutionRequest(market_data_hash="ab" * 32)
        )
    with pytest.raises(RunnerFailure, match="未声明"):
        run_private_strategy(package_bytes(), dataset(), request(parameters={"secret": "x"}))


def test_runner_never_falls_back_to_host(monkeypatch):
    monkeypatch.delenv("ATLAS_RUNNER_ENABLED", raising=False)
    with pytest.raises(RunnerUnavailable):
        with DockerSandbox(package_bytes(), {}):
            pytest.fail("must not execute")
    monkeypatch.setenv("ATLAS_RUNNER_ENABLED", "1")
    monkeypatch.setenv("ATLAS_RUNNER_IMAGE", "python:latest")
    with pytest.raises(RunnerUnavailable, match="sha256"):
        with DockerSandbox(package_bytes(), {}):
            pytest.fail("must not execute")


def test_real_provider_protocol_and_reduce_only(monkeypatch):
    monkeypatch.setenv("ATLAS_AI_MODEL", "unit-test-model-not-real-inference")
    original = httpx.Client

    def handler(req):
        body = json.loads(req.content)
        evidence = json.loads(body["messages"][1]["content"])
        answer = {"request_id": evidence["request_id"], "action": "reduce", "scale": 0.5}
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    weight, audit = LocalAIGuard().review({"drawdown": -0.1}, 0.8, "reduce_only")
    assert weight == 0.4 and audit["status"] == "inference_completed"
    assert not audit["attested"]


def test_ai_unavailable_denies_and_external_urls_rejected(monkeypatch):
    monkeypatch.setenv("ATLAS_AI_MODEL", "test")
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"message": {"content": "pretend success"}})
            ),
            **kwargs,
        ),
    )
    weight, audit = LocalAIGuard().review({}, 0.8, "advisory")
    assert weight == 0 and audit["status"] == "failed_closed"
    monkeypatch.setenv("ATLAS_AI_URL", "https://external.example/api/chat")
    with pytest.raises(RunnerUnavailable):
        LocalAIGuard()


def test_execution_endpoints_require_owner_token_and_tee_fails_closed(tmp_path, monkeypatch):
    studio, created = create_private_agent(tmp_path)
    agent, token = created["agent"]["id"], created["developer_token"]
    package = studio.upload_package(agent, "strategy.qstrategy", package_bytes(), token)
    app = FastAPI()
    app.include_router(execution_router(studio, None))
    client = TestClient(app)
    path = f"/api/v1/quantjudge/agents/{agent}/packages/{package['id']}"
    assert client.post(path + "/execute", json=request().model_dump()).status_code == 401
    monkeypatch.delenv("ATLAS_NITRO_ROOT_CERT", raising=False)
    response = client.post(path + "/tee/challenge", headers={"X-Developer-Token": token})
    assert response.status_code == 503
    assert (
        client.get("/api/v1/quantjudge/studio/execution-capabilities").json()["general_python_zkp"]
        is False
    )
