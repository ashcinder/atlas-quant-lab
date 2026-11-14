"""Integration checks for the multi-stock lab, using disposable data and a test Runner."""
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import lab_portfolio, lab_portfolio_engine, main
from app.compute_objects import ComputeObjects
from app.lab_portfolio import LabPortfolioStore
from app.lab_portfolio_market import CHINA, PortfolioMarketError, session_windows
from app.lab_strategies import LabStrategyStore
from app import publish_portfolio_market
from app.strategy_runtime import StrategyRuntimeStore

ROOT = "/api/v1/lab-multi"
SYMBOLS = ["600519.SS", "000001.SZ"]
SOURCE = """from atlas_strategy_sdk import BaseStrategy, TargetPosition

class Strategy(BaseStrategy):
    def generate_targets(self, context):
        return [TargetPosition("600519.SS", 0.5, 1.0, "buy")]
"""


class TestRunner:
    __test__ = False

    def __init__(self, archive, parameters, checkpoint=None, **kwargs):
        self.image = ""
        self.checkpoint = checkpoint

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def seed_history(self, history):
        self.history = history

    def exchange(self, context):
        return {"targets": [{"symbol": SYMBOLS[0], "target_weight": .5}]}


def dataset(days, profile="historical"):
    manifest = {"schema": "atlas.cn.market/v1", "profile": profile, "interval": "1d", "source": "test-fixture",
                "symbols": SYMBOLS, "sessions": [day.isoformat() for day in days]}
    if profile == "live":
        manifest["calendar_through"] = datetime.now(CHINA).date().isoformat()
    rows = []
    for i, day in enumerate(days):
        opened, closed = session_windows(day, "1d")[0]
        rows.append({"time": closed, "bars": {symbol: {"open_time": opened, "open": 10 + i, "high": 11 + i,
                     "low": 9 + i, "close": 10 + i, "volume": 10_000_000, "lot_size": 100,
                     "limit_up": 100, "limit_down": 1} for symbol in SYMBOLS}})
    return manifest, rows


def register():
    from app.journal.router import _attempts

    _attempts.clear()
    client = TestClient(main.app)
    response = client.post("/api/register", json={"email": f"{uuid4()}@example.test", "password": "test-portfolio-password"})
    assert response.status_code == 201
    client.headers["X-Atlas-Lab-Owner"] = response.json()["userId"]
    return client


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_portfolio, "runner_status", lambda: (True, None))
    monkeypatch.setattr(lab_portfolio_engine, "PortfolioSandbox", TestRunner)
    original = lab_portfolio_engine.run_portfolio_backtest
    monkeypatch.setattr(lab_portfolio_engine, "run_portfolio_backtest",
                        lambda *args, **kwargs: original(*args, sandbox_factory=TestRunner, **kwargs))
    db_path = tmp_path / "lab.sqlite"
    objects = ComputeObjects(tmp_path / "objects")
    runtime = StrategyRuntimeStore(main.data_service, db_path)
    drafts = LabStrategyStore(db_path)
    store = main.lab_portfolio_store
    replacement = LabPortfolioStore(drafts, runtime, SimpleNamespace(objects=objects))
    for field in ("drafts", "runtime", "market", "objects", "stop_event"):
        monkeypatch.setattr(store, field, getattr(replacement, field))
    monkeypatch.setattr(main.lab_strategy_store, "path", db_path)
    monkeypatch.setattr(main.strategy_runtime_store, "path", db_path)
    client, other = register(), register()
    yield store, client, other
    client.close()
    other.close()


def create_draft(client, **kwargs):
    body = {"id": uuid4().hex, "name": "跨股", "kind": "multi_python", "language": "python", "source": SOURCE,
            "settings": {"symbols": SYMBOLS}, **kwargs}
    response = client.post("/api/v1/lab-strategies", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def complete_job(store, client):
    settings = create_draft(client)
    manifest, events = dataset([date(2025, 1, d) for d in (2, 3, 6)])
    digest = store.market.publish(manifest, events)
    assert client.post(ROOT + "/preflight", json={"settings": settings["settings"]}).json()["dataset_sha256"] == digest
    body = {"strategy_id": settings["id"], "expected_revision": 1, "request_id": uuid4().hex}
    response = client.post(ROOT + "/jobs", json=body)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert client.post(ROOT + "/jobs", json=body).json()["id"] == job["id"]
    store.work_job()
    result = client.get(ROOT + "/jobs/" + job["id"]).json()
    assert result["status"] == "succeeded", result
    assert result["result"]["trades"][0]["symbol"] == SYMBOLS[0]
    assert result["result"]["currency"] == "CNY"
    return settings, result


def test_draft_job_release_permissions_and_idempotency(setup):
    store, client, other = setup
    draft, result = complete_job(store, client)
    assert other.get(ROOT + "/jobs/" + result["id"]).status_code == 404
    assert other.get("/api/v1/lab-strategies/" + draft["id"]).status_code == 404
    release_data = {"strategy_id": draft["id"], "expected_revision": 1, "job_id": result["id"]}
    response = client.post(ROOT + "/releases", json=release_data)
    assert response.status_code == 201, response.text
    release = response.json()
    identifier = release["id"]
    assert release["lab_strategy_id"] == draft["id"]
    assert client.post(ROOT + "/releases", json=release_data).json()["id"] == identifier
    assert other.get(ROOT + f"/releases/{identifier}/draft").status_code == 404
    assert client.get(ROOT + f"/releases/{identifier}/draft").json()["source"] == SOURCE
    assert client.post(f"/api/v1/strategy-releases/{identifier}/publish").status_code == 200
    public = next(item for item in other.get("/api/v1/strategy-releases").json() if item["id"] == identifier)
    assert public["source_kind"] == "multi_python"
    assert not {"source", "archive", "lab_strategy_id", "lab_run_id", "package_b64"} & public.keys()
    assert client.get("/api/v1/compute/capabilities", params={"release_id": identifier}).json()["available"] is False


def test_missing_rules_and_cancelled_job(setup):
    store, client, _ = setup
    draft = create_draft(client)
    assert client.post(ROOT + "/preflight", json={"settings": draft["settings"]}).json()["available"] is False
    manifest, events = dataset([date(2025, 1, d) for d in (2, 3)])
    del events[1]["bars"][SYMBOLS[1]]["limit_up"]
    with pytest.raises(PortfolioMarketError, match="涨跌停"):
        store.market.publish(manifest, events)
    events[1]["bars"][SYMBOLS[1]]["limit_up"] = 100
    store.market.publish(manifest, events)
    body = {"strategy_id": draft["id"], "expected_revision": 1, "request_id": uuid4().hex}
    job = client.post(ROOT + "/jobs", json=body).json()
    assert client.post(ROOT + f"/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    store.work_job()
    assert client.get(ROOT + f"/jobs/{job['id']}").json()["result"] is None


def test_market_watcher_retries_mismatched_batch_without_replacing_snapshot(setup, tmp_path, monkeypatch, capsys):
    store, _, _ = setup
    manifest, events = dataset([date(2025, 1, d) for d in (2, 3)])
    initial = store.market.publish(manifest, events)
    manifest, events = dataset([date(2025, 1, d) for d in (2, 3, 6)])
    payload = "".join(json.dumps(event) + "\n" for event in events).encode()
    path = tmp_path / "next.events.jsonl"
    path.write_bytes(payload[:-3])
    (tmp_path / "next.manifest.json").write_text(json.dumps({
        **manifest, "events_sha256": sha256(payload).hexdigest(),
    }))
    ticks = 0

    def sleep(_):
        nonlocal ticks
        ticks += 1
        with store.connect() as db:
            digests = [row[0] for row in db.execute("SELECT digest FROM lab_multi_market")]
        if ticks == 1:
            assert digests == [initial]
            path.write_bytes(payload)
        elif ticks == 3:
            assert len(digests) == 2
            raise KeyboardInterrupt

    monkeypatch.setattr(publish_portfolio_market.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        publish_portfolio_market.watch(store.market, tmp_path, 5)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["status"] for line in lines] == ["failed", "published"]


def test_simulation_pause_reanchor_and_ledger(setup, monkeypatch):
    store, client, other = setup
    draft, result = complete_job(store, client)
    release = client.post(ROOT + "/releases", json={
        "strategy_id": draft["id"], "expected_revision": 1, "job_id": result["id"],
    }).json()
    days = [datetime.now(CHINA).date() - timedelta(days=n) for n in (6, 5, 4, 3, 2)]
    manifest, events = dataset(days, "live")
    latest = events[0]
    store.market.publish(manifest, events)
    monkeypatch.setattr(store.market, "latest", lambda *_: latest)
    monkeypatch.setattr(store.market, "is_current", lambda _: True)
    body = {"release_id": release["id"], "initial_capital": 10_000, "request_id": uuid4().hex}
    response = client.post(ROOT + "/runs", json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert client.post(ROOT + "/runs", json=body).json()["id"] == identifier
    assert other.post(ROOT + "/runs", json=body).status_code == 403

    # Synthetic historical clock for this scheduler fixture. The activation is
    # after the first open and before the second open.
    with store.connect() as db:
        db.execute("UPDATE lab_multi_runs SET activated_at=? WHERE id=?", (latest["time"] + 1, identifier))

    # Publish only the candles available at each simulated scheduler boundary.
    original_resolve = store.market.resolve
    monkeypatch.setattr(store.market, "resolve", lambda settings, profile: {
        **original_resolve(settings, profile), "end": latest["time"],
    })
    store.work_runs()
    assert client.get(ROOT + f"/runs/{identifier}/trades").json() == []
    latest = events[1]
    store.work_runs()
    fills = client.get(ROOT + f"/runs/{identifier}/trades").json()
    assert len(fills) == 1
    store.work_runs()
    assert client.get(ROOT + f"/runs/{identifier}/trades").json() == fills
    assert client.post(ROOT + f"/runs/{identifier}/pause").json()["status"] == "paused"
    latest = events[-1]
    assert client.post(ROOT + f"/runs/{identifier}/resume").json()["status"] == "waiting"
    store.work_runs()
    assert client.get(ROOT + f"/runs/{identifier}/trades").json() == fills
    ledger = store.runtime.ledger(client.headers["X-Atlas-Lab-Owner"], "CN", "platform_sim", identifier,
                                  None, None, None, None, 50, 0)
    assert len(ledger["fills"]) == 1
    assert ledger["positions"][0]["symbol"] == SYMBOLS[0]
    assert ledger["runs"][0]["execution_mode"] == "portfolio_sim"
    assert other.get(ROOT + f"/runs/{identifier}/trades").status_code == 404

    subscriber = other.headers["X-Atlas-Lab-Owner"]
    subscription_id = uuid4().hex
    # Isolate the runtime entitlement check from actual chain payment.
    with store.connect() as db:
        db.execute("INSERT INTO strategy_subscriptions VALUES (?,?,?,'active',?,NULL)",
                   (subscription_id, subscriber, release["id"], datetime.now(CHINA).isoformat()))
    subscribed = other.post(ROOT + "/runs", json={
        **body, "subscription_id": subscription_id, "request_id": uuid4().hex,
    })
    assert subscribed.status_code == 201, subscribed.text
    with store.connect() as db:
        db.execute("UPDATE strategy_subscriptions SET status='cancelled' WHERE id=?", (subscription_id,))
    store.work_runs()
    instance = next(row for row in other.get(ROOT + "/runs").json() if row["id"] == subscribed.json()["id"])
    assert instance["status"] == "paused"
    assert instance["latest"] is None
    assert other.post(ROOT + f"/runs/{instance['id']}/resume").status_code == 403


RQ_SOURCE = "def init(context):\n    pass\n\ndef handle_bar(context, bar_dict):\n    pass\n"


def configure_rqalpha(monkeypatch):
    rq = lab_portfolio.rqalpha_backtests
    market = {"digest": "d" * 64, "rule_version": rq.RULE_VERSION,
              "engine_version": rq.ENGINE_VERSION, "engine_id": "rqalpha",
              "start": 1735801200, "end": 1735887600, "count": 2,
              "sessions": ["2025-01-02", "2025-01-03"],
              "window": {"start": "2025-01-02", "end": "2025-01-03"}}
    monkeypatch.setattr(rq, "runner_status", lambda: (True, None))
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "a" * 64)
    monkeypatch.setattr(rq, "resolve", lambda settings: market)

    def execute(source, settings, snapshot, **kwargs):
        assert snapshot == market and settings.engine_id == "rqalpha"
        return {"kind": "multi_python", "engine_id": "rqalpha", "engine_version": rq.ENGINE_VERSION,
                "matching_type": "current_bar", "equity": [], "trades": [], "positions": [],
                "initial_capital": settings.initial_capital, "final_equity": settings.initial_capital,
                "total_return": 0}

    monkeypatch.setattr(rq, "execute", execute)
    return rq


def test_rqalpha_job_engine_identity_permissions_and_publish_denial(setup, monkeypatch):
    store, client, other = setup
    rq = configure_rqalpha(monkeypatch)
    draft = create_draft(client, source=RQ_SOURCE,
                         settings={"symbols": SYMBOLS, "engine_id": "rqalpha"})
    cap = client.get(ROOT + "/capabilities", params={"engine_id": "rqalpha"}).json()
    assert cap["engine_id"] == "rqalpha" and cap["can_release"] is False
    assert cap["matching_type"] == "current_bar"
    checked = client.post(ROOT + "/check", json={"engine_id": "rqalpha", "source": RQ_SOURCE})
    assert checked.json()["valid"] is True
    assert "静态" in checked.json()["note"]
    assert client.post(ROOT + "/preflight", json={"settings": draft["settings"]}).json()["available"]
    body = {"strategy_id": draft["id"], "expected_revision": 1, "request_id": uuid4().hex}
    job = client.post(ROOT + "/jobs", json=body)
    assert job.status_code == 202, job.text
    identifier = job.json()["id"]
    assert client.post(ROOT + "/jobs", json=body).json()["id"] == identifier
    assert other.get(ROOT + "/jobs/" + identifier).status_code == 404
    with store.connect() as db:
        saved = json.loads(db.execute("SELECT snapshot FROM lab_multi_jobs WHERE id=?",
                                      (identifier,)).fetchone()[0])
    assert saved["engine_version"] == rq.ENGINE_VERSION
    assert saved["schema_version"] == "atlas.lab-job/v2"
    assert saved["archive"] is None
    store.work_job()
    result = client.get(ROOT + "/jobs/" + identifier).json()
    assert result["status"] == "succeeded", result
    assert result["engine_id"] == "rqalpha"
    assert result["result"]["proof_status"] == "unverified"
    assert result["result"]["runner_image"] == "sha256:" + "a" * 64
    release = client.post(ROOT + "/releases", json={
        "strategy_id": draft["id"], "expected_revision": 1, "job_id": identifier,
    })
    assert release.status_code == 422
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM strategy_releases").fetchone()[0] == 0


def test_rqalpha_cancel_prevents_late_result_commit(setup, monkeypatch):
    store, client, _ = setup
    rq = configure_rqalpha(monkeypatch)
    draft = create_draft(client, source=RQ_SOURCE,
                         settings={"symbols": SYMBOLS, "engine_id": "rqalpha"})
    body = {"strategy_id": draft["id"], "expected_revision": 1, "request_id": uuid4().hex}
    identifier = client.post(ROOT + "/jobs", json=body).json()["id"]
    original = rq.execute

    def cancelled(*args, **kwargs):
        assert client.post(ROOT + f"/jobs/{identifier}/cancel").status_code == 200
        return original(*args, **kwargs)

    monkeypatch.setattr(rq, "execute", cancelled)
    store.work_job()
    result = client.get(ROOT + "/jobs/" + identifier).json()
    assert result["status"] == "cancelled" and result["result"] is None


def test_rqalpha_version_drift_and_invalid_source_do_not_fallback(setup, monkeypatch):
    store, client, _ = setup
    rq = configure_rqalpha(monkeypatch)
    bad = create_draft(client, settings={"symbols": SYMBOLS, "engine_id": "rqalpha"})
    invalid = client.post(ROOT + "/jobs", json={
        "strategy_id": bad["id"], "expected_revision": 1, "request_id": uuid4().hex,
    })
    assert invalid.status_code == 422
    draft = create_draft(client, source=RQ_SOURCE,
                         settings={"symbols": SYMBOLS, "engine_id": "rqalpha"})
    response = client.post(ROOT + "/jobs", json={
        "strategy_id": draft["id"], "expected_revision": 1, "request_id": uuid4().hex,
    })
    assert response.status_code == 202
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "b" * 64)
    store.work_job()
    result = client.get(ROOT + "/jobs/" + response.json()["id"]).json()
    assert result["status"] == "failed" and "变更" in result["error"]
    assert result["result"] is None


def test_rqalpha_cleanup_failure_remains_visible_after_cancel(setup, monkeypatch, caplog):
    from app.sandbox import RunnerCleanupFailure

    store, client, _ = setup
    rq = configure_rqalpha(monkeypatch)
    draft = create_draft(client, source=RQ_SOURCE,
                         settings={"symbols": SYMBOLS, "engine_id": "rqalpha"})
    response = client.post(ROOT + "/jobs", json={
        "strategy_id": draft["id"], "expected_revision": 1, "request_id": uuid4().hex,
    })
    identifier = response.json()["id"]

    def cleanup_failure(*args, **kwargs):
        client.post(ROOT + f"/jobs/{identifier}/cancel")
        raise RunnerCleanupFailure("RQAlpha 容器清理未确认")

    monkeypatch.setattr(rq, "execute", cleanup_failure)
    store.work_job()
    result = client.get(ROOT + "/jobs/" + identifier).json()
    assert result["status"] == "cancelled"
    assert result["result"] is None
    assert "清理未确认" in result["error"]
    assert "cleanup failed" in caplog.text
