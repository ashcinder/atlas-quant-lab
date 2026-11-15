from pathlib import Path
from subprocess import TimeoutExpired
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import main, sector_backtests

ENDPOINT = "/api/v1/lab-sector-backtests"


@pytest.fixture
def client():
    from app.journal.router import _attempts

    _attempts.clear()
    session = TestClient(main.app)
    try:
        response = session.post("/api/register", json={
            "email": f"{uuid4()}@example.test", "password": "isolated-sector-test-password",
        })
        assert response.status_code == 201
        session.headers["X-Atlas-Lab-Owner"] = response.json()["userId"]
        yield session
    finally:
        session.close()


def test_catalog_and_run_require_current_session(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_SECTOR_REPLAY_ROOT", str(tmp_path))
    anonymous = TestClient(main.app)
    try:
        assert anonymous.get(ENDPOINT).status_code == 401
        assert anonymous.post(ENDPOINT, json={"industry": "space"}).status_code == 401
    finally:
        anonymous.close()
    assert client.get(ENDPOINT, headers={"X-Atlas-Lab-Owner": "old-owner"}).status_code == 403
    assert client.post(ENDPOINT, json={"industry": "space"}, headers={"Origin": "https://invalid.example"}).status_code == 403
    catalog = client.get(ENDPOINT)
    assert catalog.headers["cache-control"] == "no-store"
    assert [row["id"] for row in catalog.json()] == list(sector_backtests.INDUSTRIES)
    assert not any(row["available"] for row in catalog.json())
    assert client.post(ENDPOINT, json={"industry": "space"}).status_code == 503


@pytest.mark.parametrize("payload", [{"industry": "../space"}, {"industry": "space", "config": "/tmp/winner.json"}])
def test_run_rejects_paths_and_extra_options(client, payload):
    assert client.post(ENDPOINT, json=payload).status_code == 422


def test_run_limits_and_failure_release(client, monkeypatch):
    monkeypatch.setattr(sector_backtests, "missing_runtime", lambda *_: False)
    assert sector_backtests.SLOTS.acquire(blocking=False)
    try:
        assert client.post(ENDPOINT, json={"industry": "space"}).status_code == 429
    finally:
        sector_backtests.SLOTS.release()

    def timed_out(*_):
        raise TimeoutExpired(["private path"], 90)

    monkeypatch.setattr(sector_backtests, "execute_replay", timed_out)
    response = client.post(ENDPOINT, json={"industry": "space"})
    assert response.status_code == 504
    assert "private path" not in response.text
    assert sector_backtests.SLOTS.acquire(blocking=False)
    sector_backtests.SLOTS.release()


def test_subprocess_timeout_cleans_temporary_run(monkeypatch, tmp_path):
    config = tmp_path / sector_backtests.SNAPSHOT / "joint-search-fine/space/summary.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}")
    output = None
    monkeypatch.setenv("ATLAS_SESSION_SECRET", "secret-fixture")

    def run(command, **options):
        nonlocal output
        output = Path(options["cwd"])
        assert options["env"].get("ATLAS_SESSION_SECRET") is None
        assert options["env"]["OMP_NUM_THREADS"] == "1"
        assert command[-1] == str(output)
        assert Path(command[-4]).parent.parent == output
        assert output.is_dir()
        raise TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(sector_backtests.subprocess, "run", run)
    with pytest.raises(TimeoutExpired):
        sector_backtests.execute_replay(tmp_path, "space")
    assert output is not None and not output.exists()
