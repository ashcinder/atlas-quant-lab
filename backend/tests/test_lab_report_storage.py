import copy
import csv
import io
import json
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import lab_report_storage as reports
from app import rqalpha_backtests as rq
from app.compute_objects import ComputeObjects, canonical_bytes
from app.lab_portfolio import LabPortfolioStore, portfolio_router
from app.lab_strategies import LabDraftCreate, LabStrategyStore
from app.sandbox import RunnerFailure

SOURCE = "def init(context):\n    pass\n\ndef handle_bar(context, bar_dict):\n    pass\n"
SYMBOLS = ["600519.SS", "000001.SZ"]
START = int(datetime(2025, 1, 2, 7, tzinfo=UTC).timestamp())
END = int(datetime(2025, 1, 3, 7, tzinfo=UTC).timestamp())
ROOT = "/api/v1/lab-multi"


def log(sequence=0, **patch):
    return {
        "sequence": sequence,
        "time": START,
        "level": "INFO",
        "source": "strategy",
        "message": "测试输出",
        **patch,
    }


def report_result(trade_count=3):
    trades = [
        {
            "time": START + index,
            "symbol": SYMBOLS[index % 2],
            "name": "测试股份",
            "side": "buy" if index % 2 else "sell",
            "position_effect": "OPEN",
            "quantity": 100 + index,
            "price": 10,
            "fee": 5,
            "commission": 5,
            "tax": 0,
            "order_id": str(index + 1),
            "exec_id": str(index + 1),
        }
        for index in range(trade_count)
    ]
    rows = {
        "trades": trades,
        "positions": [
            {
                "time": START,
                "symbol": SYMBOLS[0],
                "name": "测试股份",
                "last_price": 10,
                "direction": "LONG",
                "quantity": 100,
                "avg_price": 11,
                "market_value": 1000,
                "pnl": -100,
                "fee": 5,
                "sellable": 0,
            }
        ],
        "accounts": [
            {
                "time": stamp,
                "account_type": "stock",
                "cash": 9000,
                "equity": 10000,
                "market_value": 1000,
                "margin": None,
                "fee": 5,
                "daily_pnl": -5,
            }
            for stamp in (START, END)
        ],
        "logs": [log(), log(1, level="WARN", time=END, message="测试拒单")],
    }
    report = {
        "schema_version": "atlas.rqalpha.report/v1",
        "benchmark": None,
        "conventions": {"timezone": "Asia/Shanghai"},
        "metrics": [],
        "series": [],
        "annual_returns": [
            {
                "year": 2025,
                "start": START,
                "end": END,
                "partial": True,
                "strategy": 0.01,
                "benchmark": None,
            }
        ],
        "drawdown": None,
        "performance": {"enabled": False},
        "logs_truncated": False,
        "tables": {
            table: {"count": len(records), "recorded": True} for table, records in rows.items()
        },
    }
    return {
        "engine_id": "rqalpha",
        "engine_version": rq.ENGINE_VERSION,
        "initial_capital": 10000,
        "final_equity": 10000,
        "total_return": 0,
        "equity": [{"time": START, "equity": 10000, "cash": 9000, "market_value": 1000}],
        "trades": trades,
        "positions": [],
        "report": report,
        "report_rows": rows,
    }


@pytest.fixture
def setup(tmp_path):
    drafts = LabStrategyStore(tmp_path / "lab.sqlite")
    objects = ComputeObjects(tmp_path / "objects")
    store = LabPortfolioStore(drafts, SimpleNamespace(), SimpleNamespace(objects=objects))
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get("X-Test-User", "owner"))
        return await call_next(request)

    app.include_router(portfolio_router(store))
    with TestClient(app) as client:
        client.headers.update({"X-Test-User": "owner", "X-Atlas-Lab-Owner": "owner"})
        yield store, client, objects


def insert_job(store, result=None, *, owner="owner", status="succeeded"):
    identifier, strategy_id = uuid4().hex, uuid4().hex
    draft = LabDraftCreate.model_validate(
        {
            "id": strategy_id,
            "name": "固定版本",
            "kind": "multi_python",
            "language": "python",
            "source": SOURCE,
            "settings": {"engine_id": "rqalpha", "symbols": SYMBOLS},
        }
    )
    store.drafts.create(owner, draft)
    snapshot = {
        "name": "固定版本",
        "source": SOURCE,
        "source_sha256": sha256(SOURCE.encode()).hexdigest(),
        "settings": draft.settings.model_dump(mode="json"),
        "package_b64": None,
        "package_sha256": None,
        "runner_image": "sha256:" + "a" * 64,
        "engine_version": rq.ENGINE_VERSION,
        "market": {
            "digest": "d" * 64,
            "rule_version": "rqalpha-test",
            "count": 2,
            "sessions": ["2025-01-02", "2025-01-03"],
        },
    }
    digest = reports.store_result(store.objects, result) if result is not None else None
    with store.connect() as db:
        db.execute(
            """INSERT INTO lab_multi_jobs
                      (id,owner,request_id,strategy_id,revision,snapshot,status,progress,
                       result_digest,created_at) VALUES (?,?,?,?,1,?,?,0,?,?)""",
            (
                identifier,
                owner,
                uuid4().hex,
                strategy_id,
                json.dumps(snapshot),
                status,
                digest,
                "2025-01-02T00:00:00+00:00",
            ),
        )
    return identifier, strategy_id


def test_split_large_report_and_page_more_than_fifty_thousand_positions(setup, monkeypatch):
    store, client, objects = setup
    raw = report_result()
    count = 60_123
    raw["report_rows"]["positions"] = [
        {
            **raw["report_rows"]["positions"][0],
            "time": START + index,
            "quantity": index,
            "name": "测试证券名称" * 24,
        }
        for index in range(count)
    ]
    raw["report"]["tables"]["positions"]["count"] = count
    assert len(canonical_bytes(raw)) > 16 * 1024 * 1024
    with pytest.raises(ValueError, match="16MiB"):
        objects.put("private", raw)
    identifier, _ = insert_job(store, raw)
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert "_report_tables" not in payload["result"]
    assert "report_rows" not in payload["result"]
    assert payload["result"]["trades_complete"] is True
    with store.connect() as db:
        digest = db.execute(
            "SELECT result_digest FROM lab_multi_jobs WHERE id=?", (identifier,)
        ).fetchone()[0]
    stored = objects.read("private", digest)
    references = stored["_report_tables"]["positions"]
    assert len(references["chunks"]) == 61
    assert references["count"] == count
    assert all(
        objects.path("private", entry["digest"]).stat().st_size < 16 * 1024 * 1024
        for entry in references["chunks"]
    )
    reads = []
    original = objects.read

    def read(visibility, digest):
        reads.append(digest)
        return original(visibility, digest)

    monkeypatch.setattr(objects, "read", read)
    page = client.get(
        f"{ROOT}/jobs/{identifier}/report/positions", params={"offset": 60000, "limit": 500}
    ).json()
    assert page["total"] == count and page["unfiltered_total"] == count
    assert [row["quantity"] for row in page["rows"]] == list(range(60000, count))
    assert len(reads) == 2
    seen = []
    for offset in range(0, count, 500):
        page = reports.page_rows(objects, stored, "positions", {"offset": offset, "limit": 500})
        seen.extend(row["quantity"] for row in page["rows"])
    assert seen == list(range(count))


def test_large_trade_table_is_explicitly_non_inline_and_full_snapshot_restores_it(setup):
    store, client, _ = setup
    raw = report_result(trade_count=1007)
    identifier, _ = insert_job(store, raw)
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["result"]["trades"] == []
    assert payload["result"]["trades_complete"] is False
    page = client.get(
        f"{ROOT}/jobs/{identifier}/report/trades", params={"offset": 1000, "limit": 500}
    )
    assert page.json()["rows"] == raw["trades"][1000:]
    snapshot = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "snapshot"})
    assert snapshot.status_code == 200
    restored = snapshot.json()
    assert restored["result"]["trades"] == raw["trades"]
    assert restored["result"]["report_rows"] == raw["report_rows"]
    assert restored["result"]["trades_complete"] is True
    assert "_report_tables" not in snapshot.text
    assert "result_digest" not in snapshot.text


def test_owner_is_checked_for_every_report_source_and_export(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, report_result())
    headers = {"X-Test-User": "other", "X-Atlas-Lab-Owner": "other"}
    for path in (
        f"jobs/{identifier}",
        f"jobs/{identifier}/source",
        f"jobs/{identifier}/report/trades",
        f"jobs/{identifier}/export?table=snapshot",
    ):
        assert client.get(f"{ROOT}/{path}", headers=headers).status_code == 404
    assert (
        client.get(
            f"{ROOT}/jobs/{identifier}/source", headers={"X-Atlas-Lab-Owner": "other"}
        ).status_code
        == 403
    )
    for identifier in ("not-an-id", "..", "0" * 32):
        assert client.get(f"{ROOT}/jobs/{identifier}/source").status_code == 404


def test_source_reads_fixed_job_revision_not_current_draft(setup):
    store, client, _ = setup
    identifier, strategy_id = insert_job(store, report_result())
    with store.connect() as db:
        db.execute(
            "UPDATE lab_strategies SET source=?,revision=2 WHERE id=?",
            (SOURCE + "\nprint('changed')", strategy_id),
        )
    response = client.get(f"{ROOT}/jobs/{identifier}/source")
    assert response.json() == {
        "source": SOURCE,
        "source_sha256": sha256(SOURCE.encode()).hexdigest(),
        "revision": 1,
    }


def test_table_filters_sort_null_last_and_date_uses_beijing(setup):
    store, client, _ = setup
    raw = report_result()
    raw["report_rows"]["trades"] = [
        {**raw["trades"][0], "time": START, "price": 20, "symbol": SYMBOLS[0], "side": "buy"},
        {**raw["trades"][0], "time": START + 1, "price": None, "symbol": SYMBOLS[0], "side": "buy"},
        {**raw["trades"][0], "time": END, "price": 10, "symbol": SYMBOLS[1], "side": "sell"},
    ]
    identifier, _ = insert_job(store, raw)
    url = f"{ROOT}/jobs/{identifier}/report/trades"
    filtered = client.get(
        url,
        params={
            "symbol": SYMBOLS[0],
            "side": "buy",
            "start": "2025-01-02",
            "end": "2025-01-02",
            "sort": "price",
            "descending": True,
        },
    ).json()
    assert filtered["unfiltered_total"] == 3 and filtered["total"] == 2
    assert [row["price"] for row in filtered["rows"]] == [20, None]
    logs = client.get(
        f"{ROOT}/jobs/{identifier}/report/logs", params={"levels": "WARN,ERROR"}
    ).json()
    assert logs["total"] == 1 and logs["rows"][0]["level"] == "WARN"
    for params in (
        {"start": "2025-01-04", "end": "2025-01-02"},
        {"start": "bad"},
        {"limit": 501},
        {"offset": -1},
        {"levels": "FATAL"},
        {"sort": "time;DROP TABLE lab_multi_jobs"},
    ):
        assert client.get(url, params=params).status_code == 422


def test_csv_exports_complete_filtered_set_not_current_page_and_neutralizes_formulas(setup):
    store, client, _ = setup
    raw = report_result(13)
    raw["report_rows"]["trades"][1]["name"] = '=HYPERLINK("https://untrusted.invalid")'
    raw["report_rows"]["positions"][0]["symbol"] = "000001"
    identifier, _ = insert_job(store, raw)
    response = client.get(
        f"{ROOT}/jobs/{identifier}/export",
        params={
            "table": "trades",
            "side": "buy",
            "offset": 10,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-report-total"] == "6"
    assert response.headers["x-report-unfiltered-total"] == "13"
    assert '"side":"buy"' in response.headers["x-report-filters"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["成交时间", "合约代码", "合约名称"]
    assert len(rows) == 7
    assert rows[1][0] == "2025-01-02 15:00:01"
    assert rows[1][2].startswith("'=HYPERLINK")
    positions = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "positions"})
    rows = list(csv.reader(io.StringIO(positions.content.decode("utf-8-sig"))))
    assert rows[1][1] == "'000001"
    assert rows[1][8] == "-100"
    assert positions.headers["content-disposition"] == (
        f'attachment; filename="atlas-report-{identifier}-positions.csv"'
    )


def test_annual_and_log_exports_are_typed_and_do_not_fake_missing_values(setup):
    store, client, _ = setup
    raw = report_result()
    raw["report_rows"]["logs"][0]["line"] = 8
    raw["report"]["logs_truncated"] = True
    identifier, _ = insert_job(store, raw)
    annual = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "annual"})
    rows = list(csv.reader(io.StringIO(annual.content.decode("utf-8-sig"))))
    assert rows[1] == ["2025", "2025-01-02", "2025-01-03", "True", "0.01", ""]
    logs = client.get(
        f"{ROOT}/jobs/{identifier}/export", params={"table": "logs", "levels": "INFO"}
    )
    assert logs.headers["x-report-logs-truncated"] == "true"
    assert "2025-01-02 15:00:00 INFO strategy [策略行 8] 测试输出" in logs.text
    assert "测试拒单" not in logs.text


def test_old_history_has_only_recorded_trades_without_reconstruction(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, {"trades": [], "positions": [{"symbol": SYMBOLS[0]}]})
    trades = client.get(f"{ROOT}/jobs/{identifier}/report/trades").json()
    assert trades["recorded"] and trades["rows"] == []
    for table in ("positions", "accounts", "logs"):
        response = client.get(f"{ROOT}/jobs/{identifier}/report/{table}").json()
        assert response["recorded"] is False and response["rows"] == []
        assert (
            client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": table}).status_code
            == 409
        )
    assert (
        client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "annual"}).status_code
        == 409
    )
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["started_at"] is None and payload["finished_at"] is None
    assert payload["elapsed_seconds"] is None


def test_pending_table_does_not_trigger_execution(setup, monkeypatch):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    monkeypatch.setattr(store, "work_job", lambda: pytest.fail("reads must not execute"))
    assert client.get(f"{ROOT}/jobs/{identifier}/report/logs").status_code == 409
    assert client.get(f"{ROOT}/jobs/{identifier}/source").status_code == 200
    assert (
        client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "snapshot"}).status_code
        == 409
    )
    assert client.get(f"{ROOT}/jobs/{identifier}").json()["elapsed_seconds"] is None


@pytest.mark.parametrize("cancelled", [False, True])
def test_worker_failure_and_cancellation_preserve_private_logs_and_timing(
    setup, monkeypatch, cancelled
):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "a" * 64)

    def execute(*args, **kwargs):
        with store.connect() as db:
            running = db.execute(
                "SELECT started_at,finished_at FROM lab_multi_jobs WHERE id=?", (identifier,)
            ).fetchone()
        assert running["started_at"] and running["finished_at"] is None
        if cancelled:
            store.cancel("owner", identifier)
        error = RunnerFailure("策略执行未完成")
        error.report_logs = [log(message="私有诊断", line=4)]
        error.logs_truncated = True
        raise error

    monkeypatch.setattr(rq, "execute", execute)
    store.work_job()
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["status"] == ("cancelled" if cancelled else "failed")
    assert payload["result"] is None
    assert payload["report"]["tables"]["logs"]["recorded"] is True
    assert payload["report"]["tables"]["positions"]["recorded"] is False
    assert payload["report"]["metrics"] == []
    assert payload["report"]["logs_truncated"] is True
    assert payload["started_at"] and payload["finished_at"]
    assert payload["elapsed_seconds"] >= 0
    logs = client.get(f"{ROOT}/jobs/{identifier}/report/logs").json()
    assert logs["rows"][0]["message"] == "私有诊断"
    if cancelled:
        assert logs["rows"][-1]["source"] == "system"
    assert "diagnostic_digest" not in payload
    assert (
        client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "snapshot"}).status_code
        == 409
    )


def test_queued_cancel_records_only_system_event_without_fake_strategy_logs(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    response = client.post(f"{ROOT}/jobs/{identifier}/cancel")
    payload = response.json()
    assert payload["status"] == "cancelled" and payload["finished_at"]
    assert payload["started_at"] is None and payload["elapsed_seconds"] is None
    logs = client.get(f"{ROOT}/jobs/{identifier}/report/logs").json()
    assert logs["total"] == 1
    assert logs["rows"][0]["source"] == "system" and logs["rows"][0]["time"] is None


def test_late_success_cannot_replace_cancelled_job_but_keeps_produced_logs(setup, monkeypatch):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "a" * 64)

    def execute(*args, **kwargs):
        store.cancel("owner", identifier)
        return report_result()

    monkeypatch.setattr(rq, "execute", execute)
    store.work_job()
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["status"] == "cancelled" and payload["result"] is None
    logs = client.get(f"{ROOT}/jobs/{identifier}/report/logs").json()
    assert logs["total"] == 3 and logs["rows"][-1]["source"] == "system"


def test_diagnostic_validation_and_corrupt_chunk_fail_closed(tmp_path):
    objects = ComputeObjects(tmp_path / "objects")
    for logs in (
        [log(sequence=-1)],
        [log(level="FATAL")],
        [log(), log()],
        [log(time=float("nan"))],
        [log(message="x" * 8193)],
    ):
        with pytest.raises(ValueError, match="日志|文本|数值"):
            reports.store_diagnostics(objects, logs)
    raw = report_result()
    digest = reports.store_result(objects, raw)
    stored = objects.read("private", digest)
    original = copy.deepcopy(stored)
    stored["_report_tables"]["trades"]["chunks"][0]["count"] += 1
    with pytest.raises(ValueError, match="分块"):
        list(reports.table_rows(objects, stored, "trades"))
    reference = original["_report_tables"]["trades"]["chunks"][0]
    objects.path("private", reference["digest"]).write_text("{}")
    with pytest.raises(ValueError, match="完整性"):
        list(reports.table_rows(objects, original, "trades"))


def test_empty_recorded_tables_stay_distinct_from_unrecorded(tmp_path):
    objects = ComputeObjects(tmp_path / "objects")
    raw = report_result(0)
    raw["report_rows"]["logs"] = []
    raw["report"]["tables"]["logs"] = {"count": 0, "recorded": True}
    stored = objects.read("private", reports.store_result(objects, raw))
    for table in ("trades", "logs"):
        page = reports.page_rows(objects, stored, table, {})
        assert page["recorded"] and page["total"] == 0 and page["rows"] == []
    assert reports.page_rows(objects, {}, "logs", {})["recorded"] is False


def test_empty_captured_failure_logs_remain_recorded_and_exportable(setup, monkeypatch):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "a" * 64)

    def execute(*args, **kwargs):
        error = RunnerFailure("策略执行未完成")
        error.report_logs = []
        error.logs_truncated = False
        raise error

    monkeypatch.setattr(rq, "execute", execute)
    store.work_job()
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["result"] is None
    assert payload["report"]["tables"]["logs"] == {"count": 0, "recorded": True}
    response = client.get(f"{ROOT}/jobs/{identifier}/report/logs").json()
    assert response["recorded"] and response["rows"] == []
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "logs"})
    assert exported.status_code == 200 and exported.text == ""


def test_maximum_valid_end_date_does_not_overflow(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, report_result())
    response = client.get(f"{ROOT}/jobs/{identifier}/report/trades", params={"end": "9999-12-31"})
    assert response.status_code == 200 and response.json()["total"] == 3


@pytest.mark.parametrize("stamp", [START, None])
def test_same_time_log_sort_uses_original_sequence(setup, stamp):
    store, client, _ = setup
    raw = report_result()
    raw["report_rows"]["logs"] = [log(0, time=stamp), log(1, time=stamp)]
    identifier, _ = insert_job(store, raw)
    response = client.get(
        f"{ROOT}/jobs/{identifier}/report/logs", params={"descending": True}
    ).json()
    assert [row["sequence"] for row in response["rows"]] == [1, 0]


def test_worker_shutdown_does_not_claim_user_cancellation(setup, monkeypatch):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="queued")
    monkeypatch.setattr(rq, "runner_image", lambda: "sha256:" + "a" * 64)

    def execute(*args, **kwargs):
        store.stop_event.set()
        error = RunnerFailure("执行已中断")
        error.report_logs = [log()]
        error.logs_truncated = False
        raise error

    monkeypatch.setattr(rq, "execute", execute)
    store.work_job()
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["status"] == "running" and payload["finished_at"] is None
    logs = client.get(f"{ROOT}/jobs/{identifier}/report/logs").json()["rows"]
    assert len(logs) == 1 and logs[0]["source"] == "strategy"
    assert "任务已取消" not in json.dumps(logs, ensure_ascii=False)


def test_cancellation_at_log_limit_preserves_logs_and_marks_truncation(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, status="cancelled")
    store.save_diagnostics(identifier, [log(index) for index in range(2000)], cancelled=True)
    payload = client.get(f"{ROOT}/jobs/{identifier}").json()
    assert payload["report"]["logs_truncated"] is True
    logs = client.get(
        f"{ROOT}/jobs/{identifier}/report/logs", params={"offset": 1990, "limit": 100}
    ).json()
    assert logs["total"] == 2000
    assert [row["sequence"] for row in logs["rows"]] == list(range(1990, 2000))


def test_zero_quantity_dividend_position_and_native_account_components_are_exported(setup):
    store, client, _ = setup
    raw = report_result()
    position = raw["report_rows"]["positions"][0]
    position.update(
        quantity=0, market_value=0, sellable=0, pnl=0, dividend_receivable=123.45, direction="long"
    )
    native_components = {
        "frozen_cash": 15.0,
        "dividend_receivable": 123.45,
        "cash_liabilities": 20.0,
        "cash_liabilities_interest": 1.25,
        "pending_cash_flow": -35.5,
    }
    for account in raw["report_rows"]["accounts"]:
        account.update(native_components)
    identifier, _ = insert_job(store, raw)
    position_page = client.get(f"{ROOT}/jobs/{identifier}/report/positions").json()
    assert position_page["total"] == 1
    assert position_page["rows"][0]["quantity"] == 0
    assert position_page["rows"][0]["dividend_receivable"] == 123.45
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "positions"})
    positions = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(positions) == 1
    assert positions[0]["数量"] == "0" and positions[0]["市值"] == "0"
    assert positions[0]["应收分红"] == "123.45" and positions[0]["多/空"] == "多"
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "accounts"})
    accounts = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    labels = {
        "冻结资金": "15.0",
        "应收分红": "123.45",
        "现金负债": "20.0",
        "负债利息": "1.25",
        "待到账申赎": "-35.5",
    }
    assert len(accounts) == 2
    for account in accounts:
        assert {label: account[label] for label in labels} == labels
    page = client.get(f"{ROOT}/jobs/{identifier}/report/accounts").json()
    assert all(row["pending_cash_flow"] == -35.5 for row in page["rows"])
    assert reports._csv_value("pending_cash_flow", -35.5) == -35.5
    assert isinstance(reports._csv_value("pending_cash_flow", -35.5), float)


@pytest.mark.parametrize(
    "value,translated",
    [
        ("open", "开"),
        ("close", "平"),
        ("close_today", "平今"),
        ("close_yesterday", "平昨"),
    ],
)
def test_lowercase_position_effect_exports_match_report_translation(setup, value, translated):
    store, client, _ = setup
    raw = report_result(1)
    raw["report_rows"]["trades"][0].update(position_effect=value, side="buy")
    identifier, _ = insert_job(store, raw)
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "trades"})
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["开/平"] == translated and rows[0]["买/卖"] == "买入"
    assert reports._csv_value("position_effect", value.upper()) == translated


@pytest.mark.parametrize("value,translated", [("long", "多"), ("short", "空")])
def test_lowercase_direction_exports_match_report_translation(value, translated):
    assert reports._csv_value("direction", value) == translated
    assert reports._csv_value("direction", value.upper()) == translated


def test_unrecorded_native_components_are_blank_not_invented_in_csv(setup):
    store, client, _ = setup
    identifier, _ = insert_job(store, report_result())
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "positions"})
    positions = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert positions[0]["应收分红"] == ""
    exported = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "accounts"})
    accounts = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    for account in accounts:
        assert all(
            account[label] == ""
            for label in ("冻结资金", "应收分红", "现金负债", "负债利息", "待到账申赎")
        )


def test_bounded_chunks_preserve_small_json_token_bytes():
    value = {"中文键": [None, True, 1.25, '引号"与换行\n、反斜杠\\和é'], "empty": []}
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    expected = "".join(encoder.iterencode(value)).encode("utf-8")
    chunks = list(reports.bounded_chunks(encoder.iterencode(value)))
    assert len(chunks) == 1
    assert b"".join(chunks) == expected
    assert json.loads(b"".join(chunks)) == value
    assert list(reports.bounded_chunks(iter(["", ""]))) == []


def test_bounded_csv_chunks_preserve_bom_chinese_and_special_character_bytes():
    rows = [
        {
            "time": START,
            "symbol": SYMBOLS[0],
            "name": '中文,"引号"\r\n新行\\é',
            "side": "buy",
            "position_effect": "open",
            "quantity": 0,
            "price": 1.5,
            "fee": -3.25,
        },
        {"time": END, "symbol": SYMBOLS[1], "name": "=SUM(1,2)", "side": "sell"},
    ]
    expected = "".join(reports.csv_export("trades", rows)).encode("utf-8")
    combined = b"".join(reports.bounded_chunks(reports.csv_export("trades", rows)))
    assert combined == expected and combined.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.DictReader(io.StringIO(combined.decode("utf-8-sig"))))
    assert parsed[0]["合约名称"] == rows[0]["name"]
    assert parsed[0]["费用"] == "-3.25"
    assert parsed[1]["合约名称"] == "'=SUM(1,2)"


def test_bounded_chunks_remain_lazy_and_bound_large_parts():
    consumed = 0

    def parts():
        nonlocal consumed
        for _ in range(100_000):
            consumed += 1
            yield "中" * 10

    chunks = reports.bounded_chunks(parts())
    assert consumed == 0
    first = next(chunks)
    assert len(first) == 64 * 1024
    assert consumed == 2185
    chunks.close()
    text = ('中文,"引号"\r\n\\é' * 100_000) + "结尾"
    encoded = text.encode("utf-8")
    expected = sha256(encoded).digest()
    actual = sha256()
    total, count = 0, 0
    for chunk in reports.bounded_chunks(iter(["", text, ""])):
        assert 0 < len(chunk) <= 64 * 1024
        actual.update(chunk)
        total += len(chunk)
        count += 1
    assert actual.digest() == expected and total == len(encoded)
    assert count == (len(encoded) + 64 * 1024 - 1) // (64 * 1024)


def test_buffered_snapshot_export_bytes_and_all_private_rows_remain_identical(setup):
    store, client, objects = setup
    raw = report_result(1207)
    raw["report_rows"]["positions"] = [
        {**raw["report_rows"]["positions"][0], "time": START + index} for index in range(1601)
    ]
    raw["report"]["tables"]["positions"]["count"] = 1601
    identifier, _ = insert_job(store, raw)
    row = store.owned_job("owner", identifier)
    stored = store.report_result(row)
    payload = store.job_payload(row)
    expected = "".join(reports.snapshot_export(objects, payload, stored)).encode("utf-8")
    chunks = list(reports.bounded_chunks(reports.snapshot_export(objects, payload, stored)))
    assert all(len(chunk) == 64 * 1024 for chunk in chunks[:-1])
    assert 0 < len(chunks[-1]) <= 64 * 1024
    assert b"".join(chunks) == expected
    response = client.get(f"{ROOT}/jobs/{identifier}/export", params={"table": "snapshot"})
    assert response.status_code == 200 and response.content == expected
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="atlas-report-{identifier}-snapshot.json"'
    )
    restored = json.loads(expected)["result"]
    assert restored["trades"] == raw["trades"]
    assert restored["report_rows"] == raw["report_rows"]
    assert "_report_tables" not in expected.decode("utf-8")
