import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

SUPPORTED_LANGUAGES = [
    "python",
    "javascript",
    "typescript",
    "cpp",
    "c",
    "java",
    "csharp",
    "go",
    "rust",
    "r",
    "julia",
    "pine",
    "mql4",
    "mql5",
]


@pytest.fixture(scope="module")
def client():
    client = TestClient(app)
    response = client.post(
        "/api/register",
        json={"email": f"{uuid4()}@example.test", "password": "test-password-123"},
    )
    assert response.status_code == 201, response.text
    yield client
    client.close()


def test_strategy_code_endpoints_require_login():
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/strategy-code/capabilities").status_code == 401
        assert (
            anonymous.post(
                "/api/v1/strategy-code/assist", json={"prompt": "写一个策略", "code": ""}
            ).status_code
            == 401
        )


def test_capabilities_and_assist_fail_clearly_without_provider(client, monkeypatch):
    monkeypatch.delenv("ATLAS_AI_MODEL", raising=False)
    monkeypatch.delenv("ATLAS_AI_URL", raising=False)

    capability = client.get("/api/v1/strategy-code/capabilities")
    assert capability.status_code == 200
    assert capability.json() == {
        "configured": False,
        "provider": "local_ollama",
        "model": None,
        "language": "python",
        "languages": SUPPORTED_LANGUAGES,
        "supports": ["generate", "edit", "explain"],
        "max_prompt_chars": 4000,
        "max_code_chars": 60000,
        "code_execution": False,
    }
    response = client.post(
        "/api/v1/strategy-code/assist", json={"prompt": "写一个策略", "code": ""}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI 代码助手尚未配置"


def test_assist_calls_configured_provider_and_returns_generated_code(client, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_MODEL", "unit-test-model")
    monkeypatch.delenv("ATLAS_AI_URL", raising=False)
    original_client = httpx.Client
    generated = (
        "from atlas_strategy_sdk import BaseStrategy, StrategyContext\n\n"
        "class Strategy(BaseStrategy):\n"
        "    def generate_targets(self, context: StrategyContext):\n"
        "        return []\n"
    )

    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "unit-test-model"
        system_prompt = payload["messages"][0]["content"]
        assert "ctx.history(symbol, lookback)" in system_prompt
        assert "Bar exposes open, high, low, close, volume, and timestamp" in system_prompt
        assert "TargetPosition(symbol, target_weight, confidence, reason_code)" in system_prompt
        task = json.loads(payload["messages"][1]["content"])
        assert task == {
            "instruction": "写一个空仓策略",
            "language": "python",
            "current_source": "",
        }
        result = {"explanation": "生成一个保持空仓的最小策略。", "code": generated}
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = client.post(
        "/api/v1/strategy-code/assist", json={"prompt": "写一个空仓策略", "code": ""}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"explanation": "生成一个保持空仓的最小策略。", "code": generated}


def test_assist_sends_selected_language_and_avoids_python_sdk_for_other_languages(
    client, monkeypatch
):
    monkeypatch.setenv("ATLAS_AI_MODEL", "unit-test-model")
    monkeypatch.delenv("ATLAS_AI_URL", raising=False)
    original_client = httpx.Client

    def handler(request):
        payload = json.loads(request.content)
        system_prompt = payload["messages"][0]["content"]
        assert "typescript" in system_prompt
        assert "Do not invent or import an Atlas SDK" in system_prompt
        assert "atlas_strategy_sdk" not in system_prompt
        task = json.loads(payload["messages"][1]["content"])
        assert task == {
            "instruction": "写一个均线信号函数",
            "language": "typescript",
            "current_source": "",
        }
        result = {
            "explanation": "生成 TypeScript 信号函数。",
            "code": "export function signal() {}",
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = client.post(
        "/api/v1/strategy-code/assist",
        json={"prompt": "写一个均线信号函数", "code": "", "language": "typescript"},
    )
    assert response.status_code == 200, response.text


def test_assist_rejects_unknown_language(client, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_MODEL", "unit-test-model")
    response = client.post(
        "/api/v1/strategy-code/assist",
        json={"prompt": "写一个策略", "code": "", "language": "brainfuck"},
    )
    assert response.status_code == 422


def test_assist_rejects_client_endpoint_and_hides_provider_failure(client, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_MODEL", "unit-test-model")
    monkeypatch.delenv("ATLAS_AI_URL", raising=False)
    rejected = client.post(
        "/api/v1/strategy-code/assist",
        json={"prompt": "修改策略", "code": "", "endpoint": "https://attacker.example"},
    )
    assert rejected.status_code == 422
    assert (
        client.post(
            "/api/v1/strategy-code/assist", json={"prompt": "x" * 4001, "code": ""}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/strategy-code/assist", json={"prompt": "修改策略", "code": "x" * 60001}
        ).status_code
        == 422
    )

    original_client = httpx.Client

    def handler(_request):
        return httpx.Response(500, text="provider-secret-token")

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    failed = client.post(
        "/api/v1/strategy-code/assist", json={"prompt": "修改策略", "code": "pass\n"}
    )
    assert failed.status_code == 502
    assert failed.json()["detail"] == "AI 服务暂时不可用"
    assert "provider-secret-token" not in failed.text

    def timeout_handler(request):
        raise httpx.ReadTimeout("provider-secret-token", request=request)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(timeout_handler), **kwargs
        ),
    )
    timed_out = client.post(
        "/api/v1/strategy-code/assist", json={"prompt": "修改策略", "code": "pass\n"}
    )
    assert timed_out.status_code == 504
    assert timed_out.json()["detail"] == "AI 服务响应超时"
    assert "provider-secret-token" not in timed_out.text


def test_validate_reports_python_syntax_location(client):
    valid = client.post("/api/v1/strategy-code/validate", json={"code": "value = 1\n"})
    assert valid.status_code == 200
    assert valid.json() == {"valid": True, "error": None}

    invalid = client.post("/api/v1/strategy-code/validate", json={"code": "def broken(:\n"})
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["error"]["line"] == 1
    assert invalid.json()["error"]["offset"] is not None

    context_invalid = client.post("/api/v1/strategy-code/validate", json={"code": "return 1\n"})
    assert context_invalid.status_code == 200
    assert context_invalid.json()["valid"] is False
    assert "outside function" in context_invalid.json()["error"]["message"]


def test_validate_rejects_languages_without_static_validation(client):
    for language in SUPPORTED_LANGUAGES[1:]:
        response = client.post(
            "/api/v1/strategy-code/validate",
            json={"code": "valid-looking source", "language": language},
        )
        assert response.status_code == 422
        assert (
            response.json()["detail"]
            == f"暂不支持 {language} 静态语法检查；当前仅支持 Python"
        )


def test_validate_rejects_unknown_language(client):
    response = client.post(
        "/api/v1/strategy-code/validate",
        json={"code": "value = 1", "language": "brainfuck"},
    )
    assert response.status_code == 422
