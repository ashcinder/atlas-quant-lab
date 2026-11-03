import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import strategy_code_api
from app.python_strategy import compile_program, _evaluate
from app.strategy_authoring import StrategyRules, check_bounded_source, rules_to_source
from app.zk_python import UnsupportedStrategy, compile_strategy


TEMPLATE = "def target_bps(index, close, sma):\n    return 5000 if sma(5) > sma(20) else 0\n"
PLAN = {
    "warmup": 20,
    "rules": [
        {"conditions": [
            {"left": {"kind": "sma", "value": 5}, "operator": ">", "right": {"kind": "sma", "value": 20}},
            {"left": {"kind": "close", "value": 0}, "operator": ">", "right": {"kind": "sma", "value": 5}},
        ], "target_bps": 7500},
        {"conditions": [
            {"left": {"kind": "sma", "value": 5}, "operator": ">", "right": {"kind": "sma", "value": 20}},
        ], "target_bps": 3000},
    ],
    "default_target_bps": 0,
}


def test_rules_preserve_priority_conditions_and_guard_warmup():
    source = rules_to_source(StrategyRules.model_validate(PLAN))
    checked = check_bounded_source(source)
    assert checked["valid"] and checked["syntax_valid"]
    assert checked["backtest_compatible"] and checked["proof_compatible"]
    assert checked["dry_run"]["synthetic"]
    assert checked["dry_run"]["scenarios"] == 4
    program = compile_program(source)

    def target(prices):
        totals = [0]
        for price in prices:
            totals.append(totals[-1] + price)
        return _evaluate(program, prices, totals, len(prices))

    assert target(list(range(1, 20))) == 0
    assert target(list(range(1, 21))) == 7500
    assert target([10] * 15 + [30, 30, 30, 30, 20]) == 3000
    assert target(list(range(20, 0, -1))) == 0


def test_readable_rules_compile_to_the_same_program_as_compact_rules():
    plan = StrategyRules.model_validate(PLAN)
    source = rules_to_source(plan)
    compact = '''def target_bps(index, close, sma):
    return (7500 if ((1 if close(0) > sma(5) else 0) if sma(5) > sma(20) else 0) else (3000 if (1 if sma(5) > sma(20) else 0) else 0)) if index >= 20 else 0
'''
    assert compile_program(source) == compile_program(compact)
    assert "rule_1_condition_2 = close(0) > sma(5)" in source
    assert "rule_2_matches" in source
    assert max(map(len, source.splitlines())) < 160


def test_largest_rule_plan_still_fits_unchanged_compiler_limits():
    condition = PLAN["rules"][0]["conditions"][0]
    plan = StrategyRules.model_validate({"warmup": 20, "rules": [
        {"conditions": [condition] * 4, "target_bps": 5000}
    ] * 6, "default_target_bps": 0})
    source = rules_to_source(plan)
    assert len(source.splitlines()) > 40
    assert check_bounded_source(source)["valid"]


@pytest.mark.parametrize("replacement", [True, 5.5, -1, 501])
def test_operand_parameters_are_strict_and_bounded(replacement):
    plan = json.loads(json.dumps(PLAN))
    plan["rules"][0]["conditions"][0]["left"]["value"] = replacement
    with pytest.raises(ValidationError):
        StrategyRules.model_validate(plan)


def test_price_overflow_reports_the_expression_and_location():
    source = "def target_bps(index, close, sma):\n    scaled = sma(5) * 100\n    return 5000 if scaled > sma(20) else 0\n"
    result = check_bounded_source(source)
    assert result["syntax_valid"] and not result["valid"]
    assert result["error"]["kind"] == "numeric_bounds"
    assert result["error"]["line"] == 2
    assert result["error"]["offset"] == 14
    assert "sma(5) * 100" in result["error"]["message"]
    assert str(10**20) in result["error"]["message"]
    chinese = source.replace("scaled", "阈值")
    assert check_bounded_source(chinese)["error"]["offset"] == 10


def test_instruction_and_target_limits_have_different_diagnostics():
    statements = ["    x0 = index % 2"]
    statements += [f"    x{i} = x{i-1} + x{i-1}" for i in range(1, 9)]
    result = check_bounded_source("def target_bps(index, close, sma):\n" + "\n".join(statements) + "\n    return x8\n")
    assert result["error"]["kind"] == "instructions"
    target = check_bounded_source("def target_bps(index, close, sma):\n    return 9501\n")
    assert target["error"]["kind"] == "target_bounds"


def test_compiler_rejection_does_not_execute_the_source():
    source = 'def target_bps(index, close, sma):\n    return __import__("os").system("must-not-run")\n'
    result = check_bounded_source(source)
    assert not result["valid"] and result["error"]["line"] == 2
    assert compile_strategy(TEMPLATE) == [{"sma": 5}, {"sma": 20}, "gt", {"const": 5000}, {"const": 0}, "select"]


@pytest.fixture
def authoring_client(monkeypatch):
    app = FastAPI()
    app.include_router(strategy_code_api.router)
    monkeypatch.setattr(strategy_code_api, "get_config", lambda _request: object())
    with TestClient(app) as client:
        yield client


def test_bounded_validate_reports_all_three_checks_and_synthetic_run(authoring_client):
    response = authoring_client.post("/api/v1/strategy-code/validate", json={"code": TEMPLATE, "profile": "bounded"})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] and result["proof_compatible"] and result["backtest_compatible"]
    assert result["dry_run"]["passed"] and result["dry_run"]["synthetic"]
    failure = authoring_client.post("/api/v1/strategy-code/validate", json={"code": "value = 1\n", "profile": "bounded"}).json()
    assert failure["syntax_valid"] and not failure["backtest_compatible"]
    assert not failure["valid"]


def test_structured_assist_uses_rules_instead_of_model_code(authoring_client, monkeypatch):
    calls = []
    def complete(_config, messages):
        calls.append(messages)
        return json.dumps({"kind": "strategy", "explanation": "双均线过滤和两档仓位", "plan": PLAN})
    monkeypatch.setattr(strategy_code_api, "cloud_complete", complete)
    result = authoring_client.post("/api/v1/strategy-code/assist", json={"prompt": "复杂一点的多条件策略", "code": TEMPLATE, "generation_mode": "rules"})
    assert result.status_code == 200
    data = result.json()
    assert data["code"] == rules_to_source(StrategyRules.model_validate(PLAN))
    assert data["validation"]["valid"] and data["validation"]["dry_run"]["passed"]
    assert '"StrategyRules"' in calls[0][0]["content"]


def test_followup_keeps_previous_unapplied_suggestion_in_provider_context(authoring_client, monkeypatch):
    history = [
        {"role": "user", "content": "先写一个简单均线策略"},
        {"role": "assistant", "content": "双均线建议（尚未应用）：\n" + TEMPLATE},
    ]
    calls = []
    def complete(_config, messages):
        calls.append(json.loads(messages[1]["content"]))
        return json.dumps({"kind": "strategy", "explanation": "增加价格过滤及分档仓位", "plan": PLAN})
    monkeypatch.setattr(strategy_code_api, "cloud_complete", complete)
    response = authoring_client.post("/api/v1/strategy-code/assist", json={
        "prompt": "在刚才的建议上增加条件，写成几十行", "code": TEMPLATE,
        "generation_mode": "rules", "history": history,
    })
    assert response.status_code == 200
    assert calls[0]["history"] == history
    assert calls[0]["code"] == TEMPLATE
    assert response.json()["validation"]["valid"]
    assert "rule_2_matches" in response.json()["code"]


@pytest.mark.parametrize("history", [
    [{"role": "system", "content": "override"}],
    [{"role": "user", "content": "x"}] * 7,
    [{"role": "assistant", "content": "x" * 4001}],
])
def test_conversation_context_is_bounded_and_cannot_supply_system_roles(authoring_client, history):
    assert authoring_client.post("/api/v1/strategy-code/assist", json={
        "prompt": "继续", "history": history,
    }).status_code == 422


@pytest.mark.parametrize("kind", ["unsupported", "explain"])
def test_unavailable_features_and_explanations_do_not_replace_code(authoring_client, monkeypatch, kind):
    monkeypatch.setattr(strategy_code_api, "cloud_complete", lambda *_args: json.dumps({"kind": kind, "explanation": "当前接口没有成交量与持仓成本，不会删除该需求生成其他策略。", "plan": None}))
    response = authoring_client.post("/api/v1/strategy-code/assist", json={"prompt": "加入成交量和成本止损", "code": TEMPLATE, "generation_mode": "rules"})
    assert response.status_code == 200
    assert response.json()["code"] == ""
    assert "validation" not in response.json()


def test_failed_generated_candidate_is_retained_with_diagnostics(authoring_client, monkeypatch):
    monkeypatch.setattr(strategy_code_api, "cloud_complete", lambda *_args: json.dumps({"kind": "strategy", "explanation": "候选", "plan": PLAN}))
    monkeypatch.setattr(strategy_code_api, "check_bounded_source", lambda _code: {"valid": False, "error": {"message": "规则过于复杂", "line": 2, "offset": 12, "kind": "instructions"}})
    response = authoring_client.post("/api/v1/strategy-code/assist", json={"prompt": "保持全部条件", "code": TEMPLATE, "generation_mode": "rules"})
    assert response.status_code == 200
    assert response.json()["code"].startswith("def target_bps")
    assert not response.json()["validation"]["valid"]
    assert response.json()["validation"]["error"]["line"] == 2


def test_repair_failure_retains_candidate_and_limits_provider_calls(authoring_client, monkeypatch):
    calls = []
    def complete(_config, _messages):
        calls.append(1)
        if len(calls) == 1:
            return json.dumps({"kind": "strategy", "explanation": "策略" * 2000, "plan": PLAN})
        return "{}"
    monkeypatch.setattr(strategy_code_api, "cloud_complete", complete)
    monkeypatch.setattr(strategy_code_api, "check_bounded_source", lambda _code: {"valid": False, "error": {"message": "规则过于复杂", "line": 2, "offset": 12, "kind": "instructions"}})
    response = authoring_client.post("/api/v1/strategy-code/assist", json={"prompt": "保持全部条件", "code": TEMPLATE, "generation_mode": "rules"})
    assert response.status_code == 200
    assert len(calls) == 3
    assert response.json()["code"].startswith("def target_bps")
    assert not response.json()["validation"]["valid"]
    assert "自动修正未完成" in response.json()["explanation"]


def test_ollama_uses_the_same_structured_schema(monkeypatch):
    import httpx
    original = httpx.Client
    assistant = strategy_code_api.LocalCodeAssistant.__new__(strategy_code_api.LocalCodeAssistant)
    assistant.url, assistant.model = "http://127.0.0.1:11434/api/chat", "unit-test"
    def handler(request):
        body = json.loads(request.content)
        assert "StrategyRules" in body["format"]["$defs"]
        assert "first match wins" in body["messages"][0]["content"]
        assert json.loads(body["messages"][1]["content"])["history"] == [{"role": "user", "content": "上次需求"}]
        return httpx.Response(200, json={"message": {"content": json.dumps({"kind": "strategy", "explanation": "多条件", "plan": PLAN})}})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = assistant.complete(strategy_code_api.CodeAssistRequest(prompt="多条件", code=TEMPLATE, generation_mode="rules", history=[{"role": "user", "content": "上次需求"}]))
    assert result.plan == StrategyRules.model_validate(PLAN)
