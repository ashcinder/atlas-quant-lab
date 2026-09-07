import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.journal.domain import empty_ledger
from app.journal.router import _attempts
from app.journal.scheduler import JournalScheduler
from app.journal.store import JournalStore
from app.main import app, research_service, workspace_store
from app.models import CustomStrategySpec, IndicatorSpec, RuleNode
from app.workspace import WorkspaceStore


@pytest.fixture(autouse=True)
def reset_limits():
    _attempts.clear()


def registered():
    client = TestClient(app)
    email = f"{uuid4()}@example.test"
    password = "integration-password-123"
    response = client.post("/api/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return client, email, password


def test_registration_login_logout_password_and_isolation():
    first, email, password = registered()
    second, _, _ = registered()
    assert first.get("/api/session").json()["authenticated"]
    wrong_password = first.post(
        "/api/change-password",
        json={"currentPassword": "wrong-password", "newPassword": "new-password-123"},
    )
    assert wrong_password.status_code == 403
    assert first.get("/api/session").json()["authenticated"]
    original = first.get("/api/ledger").json()
    assert original["state"]["accounts"] == []
    original["state"]["settings"]["name"] = "Only mine"
    saved = first.put("/api/ledger", json=original)
    assert saved.status_code == 200, saved.text
    assert second.get("/api/ledger").json()["state"]["settings"]["name"] != "Only mine"
    assert first.put("/api/ledger", json=original).status_code == 409
    assert (
        first.put("/api/ledger", json={"state": original["state"], "revision": True}).status_code
        == 400
    )
    other_device = TestClient(app)
    assert (
        other_device.post("/api/login", json={"email": email, "password": password}).status_code
        == 200
    )
    assert (
        first.post(
            "/api/change-password",
            json={"currentPassword": password, "newPassword": "new-password-123"},
        ).status_code
        == 200
    )
    assert other_device.get("/api/ledger").status_code == 401
    assert first.get("/api/ledger").status_code == 200
    assert first.post("/api/logout").status_code == 200
    assert first.get("/api/ledger").status_code == 401
    assert first.get("/api/v1/runs").status_code == 401


def test_request_security_and_invalid_payloads():
    client, _, _ = registered()
    assert client.get("/api/ledger").headers["cache-control"] == "no-store"
    for path in [
        "/api/logout",
        "/api/login",
        "/api/register",
        "/api/change-password",
        "/api/reset",
        "/api/v1/notifications/read",
    ]:
        assert (
            client.post(path, headers={"Origin": "https://untrusted.example"}, json={}).status_code
            == 403
        )
    assert (
        client.put("/api/ledger", headers={"Sec-Fetch-Site": "cross-site"}, json={}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/login", content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.post("/api/login", json=[]).status_code == 400
    assert (
        client.post(
            "/api/login", content="email=a", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.put(
            "/api/ledger", content="x" * 4_000_001, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    client.cookies.set("atlas_session", "invalid.signature")
    assert client.get("/api/ledger").status_code == 401


def test_login_rate_limit_separate_from_registration_and_success():
    client, email, password = registered()
    for _ in range(6):
        assert (
            client.post("/api/login", json={"email": email, "password": password}).status_code
            == 200
        )
    for _ in range(5):
        assert (
            client.post(
                "/api/login", json={"email": email, "password": "wrong-password"}
            ).status_code
            == 401
        )
    assert client.post("/api/login", json={"email": email, "password": password}).status_code == 429


def test_reset_confirmation_cas_and_preserve_account_image():
    client, _, _ = registered()
    data = client.get("/api/ledger").json()
    data["state"]["accounts"] = [
        {
            "id": "a",
            "name": "Account",
            "platform": "Test",
            "note": "",
            "category": "crypto",
            "currency": "USD",
            "archived": False,
        }
    ]
    response = client.put("/api/ledger", json=data)
    assert response.status_code == 200
    revision = response.json()["revision"]
    assert (
        client.post(
            "/api/reset", json={"revision": revision, "confirmation": "wrong", "keepAccounts": True}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/reset",
            json={"revision": revision - 1, "confirmation": "清空", "keepAccounts": True},
        ).status_code
        == 409
    )
    cleared = client.post(
        "/api/reset", json={"revision": revision, "confirmation": "清空", "keepAccounts": True}
    )
    assert cleared.status_code == 200, cleared.text
    assert len(cleared.json()["state"]["accounts"]) == 1
    assert cleared.json()["state"]["plans"] == []
    final = client.post(
        "/api/reset",
        json={
            "revision": cleared.json()["revision"],
            "confirmation": "清空",
            "keepAccounts": False,
        },
    )
    assert final.json()["state"]["accounts"] == []


def test_templates_with_same_id_and_private_alerts():
    first, _, _ = registered()
    second, _, _ = registered()
    spec = CustomStrategySpec(
        id="shared-template-name",
        name="First private",
        entry=RuleNode(
            kind="condition", left=IndicatorSpec(field="close"), operator="gt", right_value=1
        ),
        exit=RuleNode(
            kind="condition", left=IndicatorSpec(field="close"), operator="lt", right_value=1
        ),
    ).model_dump(mode="json")
    path = "/api/v1/custom-strategies/shared-template-name"
    assert first.put(path, json=spec).status_code == 200
    spec["name"] = "Second private"
    assert second.put(path, json=spec).status_code == 200
    assert first.get("/api/v1/custom-strategies").json()[0]["spec"]["name"] == "First private"
    assert second.delete(path).status_code == 204
    assert len(first.get("/api/v1/custom-strategies").json()) == 1
    rule = {
        "name": "private",
        "symbol": "BTC-USD",
        "asset_class": "crypto",
        "kind": "price_above",
        "threshold": 1,
        "data_source": "demo",
    }
    created = first.post("/api/v1/alerts", json=rule)
    assert created.status_code == 201, created.text
    alert_id = created.json()["id"]
    assert second.get("/api/v1/alerts").json() == []
    assert second.put(f"/api/v1/alerts/{alert_id}", json=rule).status_code == 404
    assert second.delete(f"/api/v1/alerts/{alert_id}").status_code == 404
    owner = first.get("/api/session").json()["userId"]
    alert = workspace_store.list_alerts(owner)[0]
    workspace_store.add_notification(alert, "private notification", 100, owner)
    assert second.get("/api/v1/notifications").json() == []
    second.post("/api/v1/notifications/read")
    assert first.get("/api/v1/notifications").json()[0]["read"] is False


def test_backtest_and_research_ownership(monkeypatch):
    first, _, _ = registered()
    second, _, _ = registered()
    response = first.post(
        "/api/v1/backtests",
        json={
            "symbol": "BTC-USD",
            "asset_class": "crypto",
            "strategy_id": "sma_cross",
            "interval": "1d",
            "data_source": "demo",
            "persist": True,
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert first.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert second.get("/api/v1/runs").json() == []
    assert second.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert second.delete(f"/api/v1/runs/{run_id}").status_code == 404
    monkeypatch.setattr(research_service.executor, "submit", lambda *args: None)
    job = first.post(
        "/api/v1/research/jobs",
        json={
            "symbol": "BTC-USD",
            "asset_class": "crypto",
            "data_source": "demo",
            "experiments": [{"strategy_id": "sma_cross", "params": {"fast": 5, "slow": 20}}],
        },
    )
    assert job.status_code == 202, job.text
    job_id = job.json()["id"]
    assert first.get(f"/api/v1/research/jobs/{job_id}").status_code == 200
    assert second.get(f"/api/v1/research/jobs/{job_id}").status_code == 404
    assert second.delete(f"/api/v1/research/jobs/{job_id}").status_code == 404


def test_scheduler_persistence_and_bad_user_does_not_block_others(tmp_path):
    local = JournalStore(tmp_path / "ledger.sqlite")
    bad = local.create_user("bad@example.test", "password-123")
    good = local.create_user("good@example.test", "password-123")
    local.read_ledger(bad.id, {})
    state = empty_ledger()
    from app.journal.domain import _today

    state["accounts"] = [
        {
            "id": "a",
            "name": "A",
            "platform": "",
            "note": "",
            "category": "crypto",
            "currency": "USD",
            "archived": False,
        }
    ]
    state["plans"] = [
        {
            "id": "p",
            "accountId": "a",
            "name": "Daily",
            "amount": 10,
            "frequency": "daily",
            "day": 1,
            "time": "00:00",
            "startDate": _today(),
            "market": "CRYPTO",
            "paused": False,
            "mode": "auto",
        }
    ]
    local.read_ledger(good.id, state)
    scheduler = JournalScheduler(local)
    scheduler._run_once()
    restarted = JournalStore(local.path)
    updated = restarted.read_ledger(good.id, {})
    assert len(updated["state"]["entries"]) == 1
    assert updated["state"]["entries"][0]["automatic"]
    scheduler._run_once()
    assert restarted.read_ledger(good.id, {})["revision"] == updated["revision"]


def test_legacy_template_schema_migrates_without_exposing_old_rows(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE custom_strategies (id TEXT PRIMARY KEY, spec_json TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO custom_strategies VALUES ('legacy', '{}', '2026-01-01', '2026-01-01')"
        )
    WorkspaceStore(path)
    restarted = WorkspaceStore(path)
    assert restarted.list_custom_strategies("new-user") == []
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT id, owner_id FROM custom_strategies"
        ).fetchall() == [("legacy", "local")]
        columns = connection.execute("PRAGMA table_info(custom_strategies)").fetchall()
        assert {row[1] for row in columns if row[5]} == {"id", "owner_id"}
