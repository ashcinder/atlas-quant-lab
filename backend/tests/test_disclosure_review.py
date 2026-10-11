from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import disclosure_review as dr


def sample(**changes):
    return dr.DisclosureInput(
        **(
            dict(
                fund_code="DEMO",
                fund_name="演示",
                disclosure_date="2026-10-08",
                records_date="2026-10-08",
                disclosure_source="报告p8",
                records_source="估值表V1",
                scope="全部股票，股/元",
                currency="CNY",
                same_basis=True,
                complete_scope=True,
                quantity_tolerance="0",
                value_tolerance="0",
                demo=True,
                disclosure_csv="code,name,quantity,value\nA,公司A,10,100\nB,公司B,20,200",
                records_csv="code,name,quantity,value\nA,公司A,10,100\nB,公司B,21,210\nC,公司C,3,30",
            )
            | changes
        )
    )


def test_differences_and_missing():
    result = dr.calculate(sample())
    assert result["issue_count"] == 2
    assert result["rows"][1]["value_delta"] == "-10"
    assert result["rows"][2]["value_delta"] is None
    assert result["rows"][2]["issues"] == ["仅底层记录存在"]


def test_scope_and_date():
    assert dr.calculate(sample(complete_scope=False))["rows"][2]["issues"] == [
        "披露范围未确认，待核对"
    ]
    result = dr.calculate(sample(records_date="2026-10-09"))
    assert not result["comparable"]
    assert all(row["value_delta"] is None for row in result["rows"])
    assert not dr.calculate(sample(same_basis=False))["comparable"]


def test_tolerance_and_names():
    result = dr.calculate(sample(quantity_tolerance="1", value_tolerance="10"))
    assert result["rows"][1]["issues"] == []
    result = dr.calculate(sample(records_csv="code,name,quantity,value\nA,别名,10,100"))
    assert result["rows"][0]["issues"] == ["名称差异"]
    assert result["rows"][1]["issues"] == ["仅披露数据存在"]


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-1", "1e17", "0.0000001", "abc"])
def test_invalid_numbers(text):
    with pytest.raises(ValueError):
        dr.calculate(sample(disclosure_csv=f"code,name,quantity,value\nA,A,1,{text}"))


def test_duplicate_rejected():
    with pytest.raises(ValueError):
        dr.calculate(sample(disclosure_csv="code,name,quantity,value\nA,A,1,1\nA,A,2,2"))


def test_reports_are_owned_and_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DB", tmp_path / "reports.db")
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if request.headers.get("x-user"):
            request.state.user = SimpleNamespace(id=request.headers["x-user"])
        return await call_next(request)

    app.include_router(dr.router)
    with TestClient(app) as client:
        base = "/api/v1/disclosure-review/reports"
        assert client.get(base).status_code == 401
        response = client.post(base, json=sample().model_dump(mode="json"), headers={"x-user": "a"})
        assert response.status_code == 200
        report = response.json()
        assert client.get(base, headers={"x-user": "b"}).json() == []
        assert client.get(base + "/" + report["id"], headers={"x-user": "b"}).status_code == 404
        assert client.get(base + "/" + report["id"], headers={"x-user": "a"}).json() == report
        assert client.delete(base + "/" + report["id"], headers={"x-user": "a"}).status_code == 405
