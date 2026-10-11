from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import style_review as sr


@pytest.fixture
def sample():
    return dict(
        fund_code="DEMO",
        fund_name="消费演示",
        theme="消费",
        rule_version="R1",
        rule_basis="合同示例80%",
        denominator_basis="CNY全部非现金资产",
        as_of="2026-10-08",
        effective_on="2026-10-08",
        previous_effective_on="2026-10-01",
        library_version="V2",
        previous_version="V1",
        change_reason="新增B，待补证据",
        threshold="80",
        denominator="100",
        complete=True,
        demo=True,
        source="合成数据",
        holdings_csv="code,name,value\nA,公司A,75\nB,公司B,10\nC,公司C,15",
        library_csv="code,name,basis\nA,公司A,消费\nB,公司B,",
        previous_library_csv="code,name,basis\nA,公司A,消费",
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "DB", tmp_path / "review.db")
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if request.headers.get("x-test-user"):
            request.state.user = SimpleNamespace(id=request.headers["x-test-user"])
        return await call_next(request)

    app.include_router(sr.router)
    return TestClient(app, headers={"x-test-user": "alice"})


def test_fixed_holdings_library_effect(sample):
    result = sr.calculate(sr.ReviewInput(**sample))
    assert result["previous_pct"] == 75
    assert result["current_pct"] == 85
    assert result["library_effect_pp"] == 10
    assert result["missing_basis"] == ["B"]
    assert result["added"] == ["B"]
    assert sum(r["contribution_pp"] for r in result["rows"]) == 10


def test_partial_data_is_not_assumed_compliant(sample):
    sample.update(complete=False, holdings_csv="code,name,value\nA,公司A,75")
    result = sr.calculate(sr.ReviewInput(**sample))
    assert result["status"] == "证据不足"
    assert (result["current_pct"], result["upper_pct"]) == (75, 100)


def test_partial_data_can_establish_failure(sample):
    sample.update(complete=False, holdings_csv="code,name,value\nC,公司C,30")
    result = sr.calculate(sr.ReviewInput(**sample))
    assert result["status"] == "比例偏离"
    assert result["upper_pct"] == 70


@pytest.mark.parametrize(
    "holdings",
    [
        "code,name,value\nA,a,NaN",
        "code,name,value\nA,a,Infinity",
        "code,name,value\nA,a,-1",
        "code,name,value\nA,a,101",
        "code,name,value\nA,a,75\nA,a,25",
        "code,name,value\nA,a,1,extra",
        "code,name,value\nA,a,0.0000001",
        "code,name,value\n",
    ],
)
def test_invalid_holdings_rejected(sample, holdings):
    sample["holdings_csv"] = holdings
    with pytest.raises(ValueError):
        sr.calculate(sr.ReviewInput(**sample))


def test_complete_reconciles_and_exact_boundary(sample):
    sample["holdings_csv"] = "code,name,value\nA,a,79.999999\nC,c,20.000001"
    assert sr.calculate(sr.ReviewInput(**sample))["status"] == "比例偏离"
    sample["holdings_csv"] = "code,name,value\nA,a,80\nC,c,20"
    assert sr.calculate(sr.ReviewInput(**sample))["status"] == "本项比例达标"
    sample["denominator"] = "101"
    with pytest.raises(ValueError, match="完整数据"):
        sr.calculate(sr.ReviewInput(**sample))


def test_future_version_rejected(sample):
    sample["effective_on"] = "2026-10-09"
    with pytest.raises(ValidationError):
        sr.ReviewInput(**sample)


def test_immutable_versions_and_transaction_rollback(client, sample):
    url = "/api/v1/style-review/reports"
    first = client.post(url, json=sample)
    assert first.status_code == 200, first.text
    report = first.json()
    sample["library_csv"] += "\nC,公司C,新依据"
    assert client.post(url, json=sample).status_code == 409
    sample["library_version"] = "V3"
    assert client.post(url, json=sample).status_code == 200
    assert client.get(url + "/" + report["payload"]["id"]).json()["sha256"] == report["sha256"]
    assert len(client.get(url).json()) == 2
    sample["rule_basis"] = "改写合同"
    assert client.post(url, json=sample).status_code == 409


def test_owner_isolation_and_append_only_notes(client, sample):
    url = "/api/v1/style-review/reports"
    report = client.post(url, json=sample).json()
    detail = url + "/" + report["payload"]["id"]
    assert client.get(detail, headers={"x-test-user": "bob"}).status_code == 404
    assert client.get(url, headers={"x-test-user": "bob"}).json() == []
    note = {"text": "请补入库材料", "outcome": "待补材料"}
    assert (
        client.post(detail + "/notes", json=note, headers={"x-test-user": "bob"}).status_code == 404
    )
    assert client.post(detail + "/notes", json=note).status_code == 200
    saved = client.get(detail).json()
    assert saved["payload"] == report["payload"]
    assert saved["notes"][0]["actor"] == "alice"
    assert client.delete(detail).status_code == 405
    assert client.put(detail, json=sample).status_code == 405
    assert client.post(detail + "/notes", json={**note, "text": "  "}).status_code == 422


def test_bundle_recompute_detects_tampering(client, sample):
    report = client.post("/api/v1/style-review/reports", json=sample).json()
    url = "/api/v1/style-review/verify"
    assert client.post(url, json=report).json()["calculation_matches"]
    changed = deepcopy(report)
    changed["payload"]["result"]["current_pct"] = 99
    check = client.post(url, json=changed).json()
    assert not check["hash_matches"] and not check["calculation_matches"]
    changed["sha256"] = sr.digest(changed["payload"])
    check = client.post(url, json=changed).json()
    assert check["hash_matches"] and not check["calculation_matches"]
    assert client.post(url, json={"payload": []}).status_code == 422
    assert client.post(url, json=report, headers={"x-test-user": "bob"}).status_code == 200


def test_browser_numeric_roundtrip(client, sample):
    report = client.post("/api/v1/style-review/reports", json=sample).json()

    def js_numbers(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {k: js_numbers(v) for k, v in item.items()}
        if isinstance(item, list):
            return [js_numbers(v) for v in item]
        return item

    check = client.post("/api/v1/style-review/verify", json=js_numbers(report)).json()
    assert check["hash_matches"] and check["calculation_matches"]
    assert sr.digest({"x": 1.0}) == sr.digest({"x": 1})
    assert sr.digest({"x": 1}) != sr.digest({"x": "1"})


def test_no_session_rejected(client):
    client.headers.pop("x-test-user")
    assert client.get("/api/v1/style-review/reports").status_code == 401


def test_identical_version_names_cannot_hide_changes(client, sample):
    sample["library_version"] = sample["previous_version"]
    assert client.post("/api/v1/style-review/reports", json=sample).status_code == 409
    assert client.get("/api/v1/style-review/reports").json() == []
