"""Private multi-stock drafts, historical jobs and server-side paper runs."""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZipInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app import lab_report_storage, rqalpha_backtests
from app.compute_objects import canonical_bytes
from app.execution import parameter_values
from app.lab_portfolio_market import PortfolioMarket, PortfolioMarketError
from app.lab_strategies import MAX_LAB_PACKAGE_B64, LabMultiSettings, require_lab_owner
from app.sandbox import RunnerCleanupFailure, RunnerFailure, RunnerUnavailable
from app.strategy_studio import StrategyPackageError, inspect_strategy_package

LOGGER = logging.getLogger(__name__)
EXAMPLES = {"semiconductor": "半导体", "defense": "军工", "space": "商业航天", "robotics": "机器人"}
MAX_QUEUE = 8
MAX_RUNS_PER_OWNER = 3
MAX_GLOBAL_RUNS = 12
SOURCE_BYTES = 60_000


def now_iso():
    return datetime.now(UTC).isoformat()


def encode(value):
    return canonical_bytes(value).decode()


def read_package(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        inspection = inspect_strategy_package(raw)
        if inspection.manifest.language != "python":
            raise StrategyPackageError("多股入口仅接受 Python 策略包")
        return raw, inspection.manifest
    except (binascii.Error, BadZipFile, OSError, RuntimeError, RecursionError, KeyError) as exc:
        raise StrategyPackageError("策略包格式不正确") from exc


def package_draft(encoded):
    archive, manifest = read_package(encoded)
    with ZipFile(BytesIO(archive)) as bundle:
        source = bundle.read(manifest.entrypoint.split(":", 1)[0]).decode()
    return {"kind": "multi_python", "language": "python", "name": manifest.name[:80], "source": source,
            "package_b64": encoded}


def build_package(source, package_b64, settings=None):
    try:
        source_bytes = source.encode("utf-8")
    except UnicodeError as exc:
        raise StrategyPackageError("源码必须是有效的 UTF-8 文本") from exc
    if not source_bytes.strip() or len(source_bytes) > SOURCE_BYTES:
        raise StrategyPackageError("请输入不超过 60,000 UTF-8 字节的 Python 源码")
    if package_b64:
        original, manifest = read_package(package_b64)
        entry = manifest.entrypoint.split(":", 1)[0]
        with ZipFile(BytesIO(original)) as archive:
            files = {item.filename: archive.read(item) for item in archive.infolist() if not item.is_dir()}
    else:
        entry = "strategy.py"
        files = {"strategy.json": encode({"id": "lab_portfolio", "name": "多股代码策略", "version": "1.0.0",
                                         "language": "python", "entrypoint": "strategy.py:Strategy",
                                         "description": "A-share portfolio strategy in the strategy lab",
                                         "asset_classes": ["cn_stock"], "intervals": ["1d", "15m"]})}
    files[entry] = source_bytes
    stream = BytesIO()
    with ZipFile(stream, "w") as bundle:
        for name, content in sorted(files.items()):
            bundle.writestr(ZipInfo(name), content)
    archive = stream.getvalue()
    inspection = inspect_strategy_package(archive)
    if settings and settings.interval not in inspection.manifest.intervals:
        raise StrategyPackageError("策略包未声明所选周期")
    params = parameter_values(inspection.manifest, settings.parameters if settings else {})
    return archive, params


def runner_status():
    if os.getenv("ATLAS_LAB_MULTI_ENABLED") != "1":
        return False, "多股执行服务尚未启用"
    from app.sandbox import portfolio_runner_status

    return portfolio_runner_status()


def runner_image():
    return os.environ.get("ATLAS_PORTFOLIO_RUNNER_IMAGE", "")


class MultiInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PackageInput(MultiInput):
    package_b64: str = Field(max_length=MAX_LAB_PACKAGE_B64)


class CheckInput(MultiInput):
    engine_id: Literal["atlas_portfolio", "rqalpha"] = "atlas_portfolio"
    source: str = Field(max_length=SOURCE_BYTES)
    package_b64: str | None = Field(default=None, max_length=MAX_LAB_PACKAGE_B64)


class PreflightInput(MultiInput):
    settings: LabMultiSettings


class DraftRef(MultiInput):
    strategy_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_revision: int = Field(ge=1)


class JobInput(DraftRef):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class ReleaseInput(DraftRef):
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RunInput(MultiInput):
    release_id: str = Field(max_length=64)
    subscription_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    initial_capital: float = Field(gt=0, le=1e12)
    commission_rate: float = Field(default=.001, ge=0, le=.1)
    slippage_rate: float = Field(default=.0005, ge=0, le=.1)


class LabPortfolioStore:
    def __init__(self, drafts, runtime, publications):
        self.drafts, self.runtime = drafts, runtime
        self.market = PortfolioMarket(self.connect, publications.objects)
        self.objects = publications.objects
        self.stop_event = threading.Event()
        self.workers = []
        self.worker_lock = None
        self.check_slot = threading.BoundedSemaphore()
        # The job snapshot and simulation state live in the same SQLite database
        # as subscriptions, allowing authorization to be checked at commit.
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS lab_multi_market (
                digest TEXT PRIMARY KEY, profile TEXT NOT NULL, interval TEXT NOT NULL, universe TEXT NOT NULL,
                start INTEGER NOT NULL, end INTEGER NOT NULL, manifest TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS lab_multi_market_lookup ON lab_multi_market(profile,interval,universe,end);
            CREATE TABLE IF NOT EXISTS lab_multi_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                revision INTEGER NOT NULL, snapshot TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL,
                error TEXT, result_digest TEXT, created_at TEXT NOT NULL,
                UNIQUE(owner, request_id)
            );
            CREATE INDEX IF NOT EXISTS lab_multi_jobs_owner ON lab_multi_jobs(owner,strategy_id,created_at);
            CREATE TABLE IF NOT EXISTS lab_multi_runs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, release_id TEXT NOT NULL, subscription_id TEXT,
                settings TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT,
                state TEXT, latest TEXT, generation INTEGER NOT NULL DEFAULT 0, market_digest TEXT
            );
            CREATE INDEX IF NOT EXISTS lab_multi_runs_owner ON lab_multi_runs(owner,status);
            CREATE TABLE IF NOT EXISTS lab_multi_trades (
                run_id TEXT NOT NULL, event_time INTEGER NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(run_id,event_time,sequence)
            );
            """)
            db.execute("BEGIN IMMEDIATE")
            job_columns = {row["name"] for row in db.execute("PRAGMA table_info(lab_multi_jobs)")}
            for column in ("started_at", "finished_at", "diagnostic_digest"):
                if column not in job_columns:
                    db.execute(f"ALTER TABLE lab_multi_jobs ADD COLUMN {column} TEXT")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(lab_multi_runs)")}
            if "request_id" not in columns:
                db.execute("ALTER TABLE lab_multi_runs ADD COLUMN request_id TEXT")
            if "activated_at" not in columns:
                db.execute("ALTER TABLE lab_multi_runs ADD COLUMN activated_at REAL NOT NULL DEFAULT 0")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lab_multi_run_request ON lab_multi_runs(owner,request_id)")

    def connect(self):
        db = sqlite3.connect(self.drafts.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def fresh_draft(self, owner, body):
        draft = self.drafts.get(owner, body.strategy_id)
        if draft["revision"] != body.expected_revision:
            raise HTTPException(409, "策略已修改，请重新打开并保存")
        if draft["kind"] != "multi_python":
            raise HTTPException(422, "此入口需要 A 股多股策略")
        return draft, LabMultiSettings.model_validate(draft["settings"])

    @staticmethod
    def ensure_runner():
        available, reason = runner_status()
        if not available:
            raise HTTPException(503, reason or "多股隔离 Runner 未就绪")

    def job_payload(self, row, *, detail=False):
        snap = json.loads(row["snapshot"])
        data = {
            key: row[key]
            for key in (
                "id",
                "strategy_id",
                "revision",
                "status",
                "progress",
                "error",
                "created_at",
            )
        }
        started, finished = row["started_at"], row["finished_at"]
        elapsed = None
        if started and finished:
            elapsed = max(
                0,
                (
                    datetime.fromisoformat(finished) - datetime.fromisoformat(started)
                ).total_seconds(),
            )
        data.update(
            settings=snap["settings"],
            source_sha256=snap["source_sha256"],
            name=snap.get("name", ""),
            started_at=started,
            finished_at=finished,
            elapsed_seconds=elapsed,
            package_sha256=snap["package_sha256"],
            dataset_sha256=snap["market"]["digest"],
            rule_version=snap["market"]["rule_version"],
            runner_image=snap["runner_image"],
            result=None,
            engine_id=snap["settings"].get("engine_id", "atlas_portfolio"),
            engine_version=snap.get("engine_version"),
            matching_type="current_bar"
            if snap["settings"].get("engine_id") == "rqalpha"
            else "next_open",
        )
        if data["engine_id"] == "rqalpha" and row["status"] == "running":
            data["progress"] = None
        if detail and row["result_digest"]:
            data["result"] = lab_report_storage.public_result(
                self.objects.read("private", row["result_digest"])
            )
        if detail and row["diagnostic_digest"] and data["result"] is None:
            diagnostic = self.objects.read("private", row["diagnostic_digest"])
            data["report"] = diagnostic["report"]
        return data

    def owned_job(self, owner, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "多股回测不存在")
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM lab_multi_jobs WHERE owner=? AND id=?", (owner, identifier)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "多股回测不存在")
        return row

    def job(self, owner, identifier):
        return self.job_payload(self.owned_job(owner, identifier), detail=True)

    def job_source(self, owner, identifier):
        row = self.owned_job(owner, identifier)
        snapshot = json.loads(row["snapshot"])
        return {
            "source": snapshot["source"],
            "source_sha256": snapshot["source_sha256"],
            "revision": row["revision"],
        }

    def report_result(self, row):
        digest = row["result_digest"] or row["diagnostic_digest"]
        if digest:
            return self.objects.read("private", digest)
        if row["status"] in ("queued", "running"):
            raise HTTPException(409, "回测尚未生成报告明细")
        return {}

    def report_rows(self, owner, identifier, table, query):
        row = self.owned_job(owner, identifier)
        return lab_report_storage.page_rows(self.objects, self.report_result(row), table, query)

    def report_export(self, owner, identifier, table, query):
        row = self.owned_job(owner, identifier)
        result = self.report_result(row)
        report = result.get("report", {})
        if table == "snapshot":
            if not row["result_digest"]:
                raise HTTPException(409, "该任务未生成完整回测结果")
            body = lab_report_storage.snapshot_export(self.objects, self.job_payload(row), result)
            extension, media_type, count = "json", "application/json", None
        elif table == "annual":
            if not row["result_digest"] or not report:
                raise HTTPException(409, "该历史任务未记录年度收益")
            records = report["annual_returns"]
            if query.get("start"):
                start = lab_report_storage._timestamp_boundary(query["start"])
                records = [record for record in records if record["end"] >= start]
            if query.get("end"):
                end = lab_report_storage._timestamp_boundary(query["end"], upper=True)
                records = [record for record in records if record["start"] < end]
            if query.get("descending"):
                records = list(reversed(records))
            body = lab_report_storage.csv_export(table, records)
            extension, media_type, count = "csv", "text/csv", len(records)
        else:
            metadata = lab_report_storage.table_metadata(result, table)
            if not metadata["recorded"]:
                raise HTTPException(409, "该历史任务未记录此项报告数据")
            records = lab_report_storage.select_rows(self.objects, result, table, query)
            body = (
                lab_report_storage.logs_export(records)
                if table == "logs"
                else lab_report_storage.csv_export(table, records)
            )
            extension, media_type, count = (
                ("txt", "text/plain", len(records))
                if table == "logs"
                else ("csv", "text/csv", len(records))
            )
        headers = {
            "Content-Disposition": f'attachment; filename="atlas-report-{identifier}-{table}.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Report-Filters": json.dumps(
                {
                    key: str(value)
                    for key, value in query.items()
                    if key not in ("offset", "limit") and value not in (None, "", False)
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
        }
        if count is not None:
            headers["X-Report-Total"] = str(count)
            headers["X-Report-Unfiltered-Total"] = str(
                len(report.get("annual_returns", [])) if table == "annual" else metadata["count"]
            )
        if table == "logs":
            headers["X-Report-Logs-Truncated"] = str(bool(report.get("logs_truncated"))).lower()
        return StreamingResponse(lab_report_storage.bounded_chunks(body),
                                 media_type=media_type, headers=headers)

    def jobs(self, owner, strategy_id):
        self.drafts.require_owned(owner, strategy_id)
        with self.connect() as db:
            return [self.job_payload(row) for row in db.execute(
                "SELECT * FROM lab_multi_jobs WHERE owner=? AND strategy_id=? ORDER BY created_at DESC LIMIT 50",
                (owner, strategy_id))]

    def submit(self, owner, body):
        def previous(db):
            existing = db.execute("SELECT * FROM lab_multi_jobs WHERE owner=? AND request_id=?",
                                  (owner, body.request_id)).fetchone()
            if existing and (existing["strategy_id"] != body.strategy_id or existing["revision"] != body.expected_revision):
                raise HTTPException(409, "此请求标识已用于另一份策略快照")
            return existing

        with self.connect() as db:
            existing = previous(db)
        if existing:
            return self.job_payload(existing)
        draft, settings = self.fresh_draft(owner, body)
        if settings.engine_id == "rqalpha":
            rqalpha_backtests.validate_source(draft["source"], draft["package_b64"])
            available, reason = rqalpha_backtests.runner_status()
            if not available:
                raise HTTPException(503, reason or "RQAlpha 隔离执行环境未就绪")
            market = rqalpha_backtests.resolve(settings)
            archive, params = None, settings.parameters
            image, engine_version = rqalpha_backtests.runner_image(), rqalpha_backtests.ENGINE_VERSION
        else:
            from app.lab_portfolio_engine import ENGINE_VERSION

            self.ensure_runner()
            market = self.market.resolve(settings, "historical")
            from itertools import islice

            if len(list(islice(self.market.events(market, settings), 2))) < 2:
                raise PortfolioMarketError("选择的时间区间内不足两根已发布行情")
            archive, params = build_package(draft["source"], draft["package_b64"], settings)
            image, engine_version = runner_image(), ENGINE_VERSION
        identifier = uuid4().hex
        snapshot = {"name": draft["name"], "source": draft["source"], "package_b64": draft["package_b64"],
                    "source_sha256": hashlib.sha256(draft["source"].encode()).hexdigest(),
                    "package_sha256": hashlib.sha256(archive).hexdigest() if archive else None,
                    "parameters": params, "archive": base64.b64encode(archive).decode() if archive else None,
                    "settings": settings.model_dump(mode="json"), "schema_version": "atlas.lab-job/v2",
                    "market": market, "runner_image": image, "engine_version": engine_version}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = previous(db)
            if existing:
                return self.job_payload(existing)
            current = db.execute("SELECT revision FROM lab_strategies WHERE id=? AND owner_id=?",
                                 (body.strategy_id, owner)).fetchone()
            if not current or current["revision"] != body.expected_revision:
                raise HTTPException(409, "保存后策略又被修改，请重新发起回测")
            counts = db.execute("""SELECT COUNT(*), COUNT(CASE WHEN owner=? THEN 1 END)
                                   FROM lab_multi_jobs WHERE status IN ('queued','running')""", (owner,)).fetchone()
            if counts[0] >= MAX_QUEUE or counts[1]:
                raise HTTPException(429, "回测队列繁忙，每个账号同时运行一项多股回测")
            db.execute("""INSERT INTO lab_multi_jobs
                        (id,owner,request_id,strategy_id,revision,snapshot,status,progress,created_at)
                        VALUES(?,?,?,?,?,?,'queued',0,?)""",
                       (identifier, owner, body.request_id, body.strategy_id, body.expected_revision,
                        encode(snapshot), now_iso()))
        return self.job(owner, identifier)

    def cancel(self, owner, identifier):
        row = self.owned_job(owner, identifier)
        with self.connect() as db:
            changed = db.execute(
                """UPDATE lab_multi_jobs SET status='cancelled',error=NULL,
                                  finished_at=CASE WHEN status='queued' THEN ? ELSE finished_at END
                                  WHERE owner=? AND id=? AND status IN ('queued','running')""",
                (now_iso(), owner, identifier),
            ).rowcount
        if not changed:
            current = self.job(owner, identifier)
            if current["status"] != "cancelled":
                raise HTTPException(409, "该回测已经结束")
        elif row["status"] == "queued":
            self.save_diagnostics(identifier, [], cancelled=True)
        return self.job(owner, identifier)

    def save_diagnostics(self, identifier, logs, truncated=False, *, cancelled=False):
        with self.connect() as db:
            row = db.execute(
                "SELECT snapshot,status FROM lab_multi_jobs WHERE id=?", (identifier,)
            ).fetchone()
        if row is None or json.loads(row["snapshot"])["settings"].get("engine_id") != "rqalpha":
            return
        cancelled = cancelled and row["status"] == "cancelled"
        if logs is None and not cancelled:
            return
        records = list(logs or [])
        cancellation_message = "任务已取消；未生成完整经济结果"
        log_size = sum(len(record.get("message", "").encode("utf-8")) for record in records)
        if (
            cancelled
            and len(records) < 2000
            and log_size + len(cancellation_message.encode()) <= 1024 * 1024
        ):
            records.append(
                {
                    "sequence": len(records),
                    "time": None,
                    "level": "INFO",
                    "source": "system",
                    "message": cancellation_message,
                }
            )
        elif cancelled:
            truncated = True
        try:
            digest = lab_report_storage.store_diagnostics(self.objects, records, truncated)
        except (OSError, ValueError, KeyError, TypeError):
            LOGGER.error("Private diagnostic persistence failed for job %s", identifier)
            return
        with self.connect() as db:
            db.execute(
                """UPDATE lab_multi_jobs SET diagnostic_digest=?
                          WHERE id=? AND status IN ('running','failed','cancelled')""",
                (digest, identifier),
            )

    def finish_cancelled(self, identifier):
        with self.connect() as db:
            db.execute(
                """UPDATE lab_multi_jobs SET finished_at=COALESCE(finished_at,?)
                          WHERE id=? AND status='cancelled'""",
                (now_iso(), identifier),
            )

    def work_job(self):
        from app.lab_portfolio_engine import run_portfolio_backtest

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM lab_multi_jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return
            identifier = row["id"]
            db.execute(
                """UPDATE lab_multi_jobs SET status='running',started_at=?,finished_at=NULL
                          WHERE id=?""",
                (now_iso(), identifier),
            )

        last_poll, cancelled_flag, last_progress = 0.0, False, -1.0

        def cancelled():
            nonlocal last_poll, cancelled_flag
            if self.stop_event.is_set() or cancelled_flag:
                return True
            if time.monotonic() - last_poll > 0.3:
                last_poll = time.monotonic()
                with self.connect() as db:
                    cancelled_flag = (
                        db.execute(
                            "SELECT status FROM lab_multi_jobs WHERE id=?", (identifier,)
                        ).fetchone()[0]
                        != "running"
                    )
            return cancelled_flag

        def progress(completed, total):
            nonlocal last_progress
            fraction = min(0.99, completed / (total or snapshot["market"]["count"]))
            if fraction - last_progress >= 0.01:
                with self.connect() as db:
                    db.execute(
                        "UPDATE lab_multi_jobs SET progress=? WHERE id=? AND status='running'",
                        (fraction, identifier),
                    )
                last_progress = fraction

        try:
            snapshot = json.loads(row["snapshot"])
            settings = LabMultiSettings.model_validate(snapshot["settings"])
            if settings.engine_id == "rqalpha":
                image, version = rqalpha_backtests.runner_image(), rqalpha_backtests.ENGINE_VERSION
                if snapshot["runner_image"] != image or snapshot.get("engine_version") != version:
                    raise RunnerFailure("RQAlpha 执行镜像或版本已变更，请重新创建回测")
                result = rqalpha_backtests.execute(
                    snapshot["source"], settings, snapshot["market"], cancelled=cancelled
                )
            else:
                from app.lab_portfolio_engine import ENGINE_VERSION

                if (
                    snapshot["runner_image"] != runner_image()
                    or snapshot.get("engine_version", ENGINE_VERSION) != ENGINE_VERSION
                ):
                    raise RunnerFailure("隔离 Runner 或引擎版本已变更，请重新创建回测")
                result = run_portfolio_backtest(
                    base64.b64decode(snapshot["archive"]),
                    self.market.events(snapshot["market"], settings),
                    settings.model_dump(mode="json"),
                    snapshot["parameters"],
                    cancelled=cancelled,
                    progress=progress,
                )
                result["engine_id"] = "atlas_portfolio"
            if cancelled():
                logs = result.get("report_rows", {}).get("logs", [])
                self.save_diagnostics(
                    identifier,
                    logs,
                    result.get("report", {}).get("logs_truncated", False),
                    cancelled=True,
                )
                self.finish_cancelled(identifier)
                return
            result.update(
                source_sha256=snapshot["source_sha256"],
                package_sha256=snapshot["package_sha256"],
                dataset_sha256=snapshot["market"]["digest"],
                rule_version=snapshot["market"]["rule_version"],
                runner_image=snapshot["runner_image"],
                proof_status="unverified",
                currency="CNY",
            )
            digest = lab_report_storage.store_result(self.objects, result)
            with self.connect() as db:
                changed = db.execute(
                    """UPDATE lab_multi_jobs SET status='succeeded',progress=1,
                                      result_digest=?,finished_at=?
                                      WHERE id=? AND status='running'""",
                    (digest, now_iso(), identifier),
                ).rowcount
            if not changed:
                self.save_diagnostics(
                    identifier,
                    result.get("report_rows", {}).get("logs", []),
                    result.get("report", {}).get("logs_truncated", False),
                    cancelled=True,
                )
                self.finish_cancelled(identifier)
        except RunnerCleanupFailure as exc:
            LOGGER.error("Isolated runner cleanup failed for job %s", identifier)
            self.save_diagnostics(
                identifier,
                getattr(exc, "report_logs", None),
                getattr(exc, "logs_truncated", False),
                cancelled=cancelled(),
            )
            self.finish_cancelled(identifier)
            with self.connect() as db:
                db.execute(
                    "UPDATE lab_multi_jobs SET error=? WHERE id=? AND status='cancelled'",
                    (str(exc)[:400], identifier),
                )
            if not self.stop_event.is_set():
                self.fail_job(identifier, str(exc))
        except (RunnerFailure, RunnerUnavailable, PortfolioMarketError) as exc:
            self.save_diagnostics(
                identifier,
                getattr(exc, "report_logs", None),
                getattr(exc, "logs_truncated", False),
                cancelled=cancelled(),
            )
            self.finish_cancelled(identifier)
            if not self.stop_event.is_set():
                self.fail_job(identifier, str(exc))
        except Exception:
            LOGGER.error("Multi-stock job failed: %s", identifier)
            self.finish_cancelled(identifier)
            if not self.stop_event.is_set():
                self.fail_job(identifier, "多股回测未完成，请检查数据与运行环境")

    def fail_job(self, identifier, error):
        with self.connect() as db:
            db.execute(
                """UPDATE lab_multi_jobs SET status='failed',error=?,finished_at=?
                          WHERE id=? AND status='running'""",
                (error[:400], now_iso(), identifier),
            )

    def create_release(self, owner, body):
        _, settings = self.fresh_draft(owner, body)
        if settings.engine_id == "rqalpha":
            raise HTTPException(422, "RQAlpha 首期仅支持历史回测，暂不支持发布或持续模拟")
        with self.connect() as db:
            row = db.execute("""SELECT * FROM lab_multi_jobs WHERE owner=? AND id=? AND strategy_id=?
                                AND revision=? AND status='succeeded'""",
                             (owner, body.job_id, body.strategy_id, body.expected_revision)).fetchone()
        if row is None:
            raise HTTPException(409, "需要当前保存修订的成功回测才能创建运行版本")
        snapshot = json.loads(row["snapshot"])
        return self.runtime.create_lab_portfolio_release(owner, row, snapshot)

    def release_draft(self, owner, identifier):
        with self.runtime._connect() as db:
            row = self.runtime._release_for(db, identifier)
        if row["owner_id"] != owner:
            raise HTTPException(404, "运行版本不存在")
        snapshot = json.loads(row["snapshot"])
        if row["source_kind"] == "multi_python":
            return {key: snapshot[key] for key in ("name", "source", "package_b64", "settings")} | {
                "kind": "multi_python", "language": "python"}
        if row["source_kind"] == "python" and snapshot.get("lab_settings"):
            return {"kind": "single_bounded", "name": row["name"], "language": "python",
                    "source": snapshot["python_source"], "settings": snapshot["lab_settings"]}
        raise HTTPException(404, "此历史版本未关联策略草稿设置")

    @staticmethod
    def authorized(db, owner, release, subscription_id):
        return release["owner_id"] == owner or db.execute(
            """SELECT 1 FROM strategy_subscriptions WHERE owner_id=? AND release_id=?
               AND id=? AND status='active'""", (owner, release["id"], subscription_id)).fetchone() is not None

    def run_payload(self, row):
        with self.connect() as db:
            release = db.execute("SELECT name,version FROM strategy_releases WHERE id=?", (row["release_id"],)).fetchone()
        settings = json.loads(row["settings"])
        latest = json.loads(row["latest"]) if row["latest"] else None
        return {key: row[key] for key in ("id", "release_id", "status", "updated_at", "error")} | {
            "name": release["name"], "version": release["version"], "settings": settings, "latest": latest,
            "market": "CN", "environment": "platform_sim", "currency": "CNY", "proof_status": "unverified",
            "account_id": row["id"], "valuation_complete": row["status"] == "active" and latest is not None}

    def find_run(self, db, owner, identifier):
        row = db.execute("SELECT * FROM lab_multi_runs WHERE id=? AND owner=?", (identifier, owner)).fetchone()
        if row is None:
            raise HTTPException(404, "多股模拟实例不存在")
        return row

    def create_run(self, owner, body):
        def previous(db):
            if not body.request_id:
                return None
            existing = db.execute("SELECT * FROM lab_multi_runs WHERE owner=? AND request_id=?",
                                  (owner, body.request_id)).fetchone()
            if existing is not None:
                settings = json.loads(existing["settings"])
                if (existing["release_id"] != body.release_id or existing["subscription_id"] != body.subscription_id
                        or any(settings[key] != getattr(body, key)
                               for key in ("initial_capital", "commission_rate", "slippage_rate"))):
                    raise HTTPException(409, "此请求标识已用于另一份运行配置")
            return existing

        with self.connect() as db:
            existing = previous(db)
        if existing:
            return self.run_payload(existing)
        self.ensure_runner()
        with self.connect() as db:
            release = self.runtime._release_for(db, body.release_id)
            if release["source_kind"] != "multi_python" or not self.authorized(db, owner, release, body.subscription_id):
                raise HTTPException(403, "请选择拥有有效授权的多股运行版本")
        snapshot = json.loads(release["snapshot"])
        if snapshot.get("settings", {}).get("engine_id", "atlas_portfolio") != "atlas_portfolio":
            raise HTTPException(422, "此回测引擎暂不支持平台持续模拟")
        if snapshot["runner_image"] != runner_image():
            raise HTTPException(503, "运行版本锁定的隔离镜像当前不可用")
        settings = LabMultiSettings.model_validate({
            **snapshot["settings"], **body.model_dump(exclude={"release_id", "subscription_id", "request_id"}),
            "start": None, "end": None,
        })
        market = self.market.resolve(settings, "live")
        self.market.latest(market, settings)
        identifier = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = previous(db)
            if existing:
                return self.run_payload(existing)
            if not self.authorized(db, owner, release, body.subscription_id):
                raise HTTPException(403, "订阅授权已失效")
            counts = db.execute("""SELECT COUNT(*), COUNT(CASE WHEN owner=? THEN 1 END)
                                   FROM lab_multi_runs WHERE status!='stopped'""", (owner,)).fetchone()
            if counts[0] >= MAX_GLOBAL_RUNS or counts[1] >= MAX_RUNS_PER_OWNER:
                raise HTTPException(429, "多股模拟实例已达到容量上限")
            db.execute("""INSERT INTO lab_multi_runs
                          (id,owner,release_id,subscription_id,settings,status,updated_at,request_id,activated_at)
                          VALUES (?,?,?,?,?,'waiting',?,?,?)""",
                       (identifier, owner, body.release_id, body.subscription_id, settings.model_dump_json(),
                        now_iso(), body.request_id, time.time()))
            row = self.find_run(db, owner, identifier)
        return self.run_payload(row)

    def set_run_state(self, owner, identifier, action):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.find_run(db, owner, identifier)
            allowed = {"pause": {"active", "waiting"}, "resume": {"paused"}, "stop": {"active", "waiting", "paused"}}
            if row["status"] not in allowed[action]:
                raise HTTPException(409, "当前状态无法执行此操作")
            release = self.runtime._release_for(db, row["release_id"])
            if action == "resume" and not self.authorized(db, owner, release, row["subscription_id"]):
                raise HTTPException(403, "订阅授权已失效")
            target = {"pause": "paused", "resume": "waiting", "stop": "stopped"}[action]
            db.execute("""UPDATE lab_multi_runs SET status=?,updated_at=?,error=NULL,generation=generation+1,
                          activated_at=CASE WHEN ?='waiting' THEN ? ELSE activated_at END
                          WHERE id=?""", (target, now_iso(), target, time.time(), identifier))
            updated = self.find_run(db, owner, identifier)
        return self.run_payload(updated)

    def run_trades(self, owner, identifier):
        with self.connect() as db:
            self.find_run(db, owner, identifier)
            return [json.loads(row["payload"]) for row in db.execute(
                "SELECT payload FROM lab_multi_trades WHERE run_id=? ORDER BY event_time DESC,sequence DESC LIMIT 2000",
                (identifier,))]

    def runs(self, owner):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM lab_multi_runs WHERE owner=? ORDER BY updated_at DESC", (owner,)).fetchall()
        return [self.run_payload(row) for row in rows]

    def set_waiting(self, row, message):
        if row["status"] == "waiting" and row["error"] == message:
            return
        with self.connect() as db:
            db.execute("""UPDATE lab_multi_runs SET status='waiting',error=?,updated_at=?
                          WHERE id=? AND generation=? AND status IN ('active','waiting')""",
                       (message, now_iso(), row["id"], row["generation"]))

    def tick_run(self, row):
        from app.lab_portfolio_engine import PortfolioEngine, PortfolioSandbox

        owner, identifier = row["owner"], row["id"]
        with self.connect() as db:
            release = self.runtime._release_for(db, row["release_id"])
            if not self.authorized(db, owner, release, row["subscription_id"]):
                db.execute("""UPDATE lab_multi_runs SET status='paused',error='订阅授权已失效',updated_at=?
                              WHERE id=? AND generation=? AND status IN ('waiting','active')""",
                           (now_iso(), identifier, row["generation"]))
                return
        snapshot = json.loads(release["snapshot"])
        if snapshot["runner_image"] != runner_image():
            self.set_waiting(row, "运行版本锁定的隔离镜像当前不可用")
            return
        settings = LabMultiSettings.model_validate_json(row["settings"])
        market = self.market.resolve(settings, "live")
        state = json.loads(row["state"]) if row["state"] else None
        last = state["time"] if state else None
        if not self.market.is_current(market):
            self.set_waiting(row, "行情过期或未完整发布，等待下一次更新")
            return
        if last is not None and market["end"] <= last:
            return
        event = self.market.latest(market, settings)
        intervening = self.market.events(market, settings, after=last)
        first = next(intervening, None)
        contiguous = (row["status"] == "active" and last is not None and first is not None
                      and first["time"] == event["time"] and self.market.contains_time(market, last))
        if any(bar["open_time"] < row["activated_at"] for bar in event["bars"].values()):
            contiguous = False
        if (last is not None and not self.market.contains_time(market, last)
                and any(position.get("quantity", 0) for position in json.loads(row["latest"]).get("positions", []))):
            raise PortfolioMarketError("新行情清单未覆盖上次处理时间，暂无法核对持仓与公司行动")
        engine = PortfolioEngine(settings.model_dump(mode="json"), state)
        with PortfolioSandbox(base64.b64decode(snapshot["archive"]), snapshot["parameters"],
                              checkpoint=state.get("strategy_state") if state else None,
                              cancelled=self.stop_event.is_set) as sandbox:
            sandbox.seed_history(engine.history())
            if first is not None and first["time"] < event["time"]:
                from itertools import chain

                for item in chain((first,), intervening):
                    if item["time"] >= event["time"]:
                        break
                    # The strategy may update indicators from observed history.
                    # Missed events never consume a pending order.
                    engine.step(item, sandbox.exchange, allow_fills=False)
            latest = engine.step(event, sandbox.exchange, allow_fills=contiguous)
        if self.stop_event.is_set():
            return
        state = engine.snapshot()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.authorized(db, owner, release, row["subscription_id"]):
                return
            changed = db.execute("""UPDATE lab_multi_runs SET status='active',updated_at=?,error=NULL,
                                    state=?,latest=?,market_digest=?,generation=generation+1
                                    WHERE id=? AND generation=? AND status IN ('active','waiting')""",
                                 (now_iso(), encode(state), encode(latest), market["digest"], identifier,
                                  row["generation"])).rowcount
            if changed:
                db.executemany("INSERT INTO lab_multi_trades VALUES (?,?,?,?)",
                               [(identifier, event["time"], i, encode(trade))
                                for i, trade in enumerate(latest["trades"])])

    def work_runs(self):
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM lab_multi_runs WHERE status IN ('active','waiting')
                                 OR (status IN ('paused','stopped') AND state IS NOT NULL)""").fetchall()
        for row in rows:
            if self.stop_event.is_set():
                break
            try:
                if row["status"] in ("paused", "stopped"):
                    self.mark_run(row)
                else:
                    self.tick_run(row)
            except (RunnerUnavailable, RunnerFailure, PortfolioMarketError) as exc:
                self.set_waiting(row, str(exc)[:400])
            except Exception:
                LOGGER.exception("Multi-stock simulation failed: %s", row["id"])
                self.set_waiting(row, "模拟运行暂不可用，请检查行情与运行环境")

    def mark_run(self, row):
        from app.lab_portfolio_engine import PortfolioEngine

        state = json.loads(row["state"])
        if not state.get("holdings"):
            return
        settings = LabMultiSettings.model_validate_json(row["settings"])
        market = self.market.resolve(settings, "live")
        if (market["end"] <= json.loads(row["latest"])["time"] or not self.market.is_current(market)
                or not self.market.contains_time(market, state["time"])):
            return
        engine = PortfolioEngine(settings.model_dump(mode="json"), state)
        latest = None
        for event in self.market.events(market, settings, after=state["time"]):
            latest = engine.step(event, None, allow_fills=False)
        if latest:
            with self.connect() as db:
                db.execute("""UPDATE lab_multi_runs SET latest=?,market_digest=?,updated_at=?
                              WHERE id=? AND generation=? AND status IN ('paused','stopped')""",
                           (encode(latest), market["digest"], now_iso(), row["id"], row["generation"]))

    def loop(self, action, interval):
        while not self.stop_event.is_set():
            try:
                action()
            except Exception:
                LOGGER.exception("Multi-stock scheduler iteration failed")
            self.stop_event.wait(interval)

    def start(self):
        if self.workers or os.getenv("ATLAS_LAB_MULTI_ENABLED") != "1":
            return
        lock = open(Path(self.drafts.path).with_suffix(".lab-multi.lock"), "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return
        self.worker_lock = lock
        with self.connect() as db:
            db.execute("UPDATE lab_multi_jobs SET status='queued',progress=0 WHERE status='running'")
            db.execute("""UPDATE lab_multi_runs SET status='waiting',error='服务已重启，等待最新行情重新定位',
                          activated_at=? WHERE status='active'""", (time.time(),))
        self.stop_event.clear()
        self.workers = [threading.Thread(target=self.loop, args=(action, interval), daemon=True, name=name)
                        for action, interval, name in ((self.work_job, 1, "lab-multi-backtest"),
                                                       (self.work_runs, 5, "lab-multi-simulation"))]
        for worker in self.workers:
            worker.start()

    def stop(self):
        self.stop_event.set()
        for worker in self.workers:
            worker.join(timeout=12)
        if not any(worker.is_alive() for worker in self.workers):
            self.workers.clear()
            if self.worker_lock:
                self.worker_lock.close()
                self.worker_lock = None


def examples_root():
    path = os.environ.get("ATLAS_LAB_MULTI_EXAMPLES")
    return Path(path) if path else None


def report_query(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    start: date | None = None,
    end: date | None = None,
    symbol: str | None = Query(None, max_length=80, pattern=r"^[A-Z0-9.]+$"),
    side: Literal["buy", "sell", ""] = "",
    levels: str = Query("", max_length=32),
    descending: bool = False,
    sort: Literal[
        "time", "symbol", "quantity", "price", "fee", "market_value", "pnl", "equity"
    ] = "time",
):
    if start and end and start > end:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    if set(levels.split(",")) - {"", *lab_report_storage.LOG_LEVELS}:
        raise HTTPException(422, "日志等级不支持")
    return {
        "offset": offset,
        "limit": limit,
        "start": start,
        "end": end,
        "symbol": symbol,
        "side": side,
        "levels": levels,
        "descending": descending,
        "sort": sort,
    }


def portfolio_router(store):
    router = APIRouter(prefix="/api/v1/lab-multi")

    @router.get("/capabilities")
    def capabilities(request: Request, engine_id: Literal["atlas_portfolio", "rqalpha"] = "atlas_portfolio"):
        require_lab_owner(request)
        if engine_id == "rqalpha":
            available, reason = rqalpha_backtests.runner_status()
            try:
                benchmarks = rqalpha_backtests.benchmark_options()
            except (RunnerFailure, RunnerUnavailable, OSError, ValueError):
                benchmarks = []
            return {"available": available, "reason": reason, "engine_id": engine_id,
                    "engine_version": rqalpha_backtests.ENGINE_VERSION, "benchmarks": benchmarks,
                    "can_release": False, "matching_type": "current_bar"}
        from app.lab_portfolio_engine import ENGINE_VERSION

        available, reason = runner_status()
        return {"available": available, "reason": reason, "engine_id": engine_id,
                "engine_version": ENGINE_VERSION, "can_release": True, "matching_type": "next_open"}

    @router.post("/inspect")
    def inspect(body: PackageInput, request: Request):
        require_lab_owner(request)
        return package_draft(body.package_b64)

    @router.post("/check")
    def check(body: CheckInput, request: Request):
        from app.lab_portfolio_engine import PortfolioSandbox

        require_lab_owner(request)
        if not store.check_slot.acquire(blocking=False):
            raise HTTPException(429, "代码检查繁忙，请稍后重试")
        try:
            if body.engine_id == "rqalpha":
                rqalpha_backtests.validate_source(body.source, body.package_b64)
                return {"valid": True, "error": None,
                        "note": "仅静态语法和入口检查，未运行历史回测或生成证明"}
            archive, params = build_package(body.source, body.package_b64)
            available, reason = runner_status()
            if not available:
                return {"valid": False, "error": {"message": f"静态检查通过。{reason or '隔离 Runner 未就绪'}"}}
            with PortfolioSandbox(archive, params):
                pass
            return {"valid": True, "error": None}
        except (StrategyPackageError, RunnerUnavailable, RunnerFailure, UnicodeError) as exc:
            return {"valid": False, "error": {"message": str(exc)[:400]}}
        finally:
            store.check_slot.release()

    @router.post("/preflight")
    def preflight(body: PreflightInput, request: Request):
        require_lab_owner(request)
        try:
            if body.settings.engine_id == "rqalpha":
                market = rqalpha_backtests.resolve(body.settings)
                return {"available": True, "reason": None, "start": market["start"],
                        "end": market["end"], "dataset_sha256": market["digest"]}
            market = store.market.resolve(body.settings, "historical")
            events = store.market.events(market, body.settings)
            first = next(events, None)
            last = next(events, None)
            if first is None or last is None:
                raise PortfolioMarketError("选择的时间区间内不足两根已发布行情")
            if body.settings.end is None:
                last_time = market["end"]
            else:
                for event in events:
                    last = event
                last_time = last["time"]
        except (PortfolioMarketError, RunnerFailure, RunnerUnavailable) as exc:
            return {"available": False, "reason": str(exc), "start": None, "end": None}
        return {"available": True, "reason": None, "start": first["time"], "end": last_time,
                "dataset_sha256": market["digest"]}

    @router.get("/examples")
    def examples(request: Request):
        require_lab_owner(request)
        root = examples_root()
        return [{"id": slug, "name": name} for slug, name in EXAMPLES.items()
                if root and (root / f"{slug}.qstrategy").is_file() and (root / f"{slug}.json").is_file()]

    @router.get("/examples/{slug}")
    def example(slug: str, request: Request):
        require_lab_owner(request)
        root = examples_root()
        if root is None or slug not in EXAMPLES:
            raise HTTPException(404, "策略示例未安装")
        try:
            with (root / f"{slug}.qstrategy").open("rb") as stream:
                raw = stream.read(MAX_LAB_PACKAGE_B64 * 3 // 4 + 1)
            encoded = base64.b64encode(raw).decode()
            if len(encoded) > MAX_LAB_PACKAGE_B64:
                raise HTTPException(503, "策略示例超过导入大小限制")
            draft = package_draft(encoded)
            settings = LabMultiSettings.model_validate_json((root / f"{slug}.json").read_text())
            return {**draft, "settings": settings.model_dump(mode="json")}
        except FileNotFoundError:
            raise HTTPException(404, "策略示例未安装") from None

    @router.post("/jobs", status_code=202)
    def submit(body: JobInput, request: Request):
        owner = require_lab_owner(request)
        try:
            return store.submit(owner, body)
        except (RunnerFailure, PortfolioMarketError, StrategyPackageError) as exc:
            raise HTTPException(422, str(exc)[:400]) from exc
        except RunnerUnavailable as exc:
            raise HTTPException(503, str(exc)[:400]) from exc

    @router.get("/jobs")
    def jobs(strategy_id: str, request: Request):
        return store.jobs(require_lab_owner(request), strategy_id)

    @router.get("/jobs/{identifier}/source")
    def source(identifier: str, request: Request):
        return store.job_source(require_lab_owner(request), identifier)

    @router.get("/jobs/{identifier}/report/{table}")
    def report_rows(
        identifier: str,
        table: Literal["trades", "positions", "accounts", "logs"],
        request: Request,
        query: Annotated[dict, Depends(report_query)],
    ):
        return store.report_rows(require_lab_owner(request), identifier, table, query)

    @router.get("/jobs/{identifier}/export")
    def report_export(
        identifier: str,
        table: Literal["trades", "positions", "accounts", "annual", "logs", "snapshot"],
        request: Request,
        query: Annotated[dict, Depends(report_query)],
    ):
        return store.report_export(require_lab_owner(request), identifier, table, query)

    @router.get("/jobs/{identifier}")
    def job(identifier: str, request: Request):
        return store.job(require_lab_owner(request), identifier)

    @router.post("/jobs/{identifier}/cancel")
    def cancel(identifier: str, request: Request):
        return store.cancel(require_lab_owner(request), identifier)

    @router.post("/releases", status_code=201)
    def release(body: ReleaseInput, request: Request):
        return store.create_release(require_lab_owner(request), body)

    @router.get("/releases/{identifier}/draft")
    def release_draft(identifier: str, request: Request):
        return store.release_draft(require_lab_owner(request), identifier)

    @router.get("/runs")
    def runs(request: Request):
        return store.runs(require_lab_owner(request))

    @router.post("/runs", status_code=201)
    def start(body: RunInput, request: Request):
        return store.create_run(require_lab_owner(request), body)

    @router.get("/runs/{identifier}/trades")
    def trades(identifier: str, request: Request):
        return store.run_trades(require_lab_owner(request), identifier)

    @router.post("/runs/{identifier}/{action}")
    def run_action(identifier: str, action: Literal["pause", "resume", "stop"], request: Request):
        return store.set_run_state(require_lab_owner(request), identifier, action)

    return router
