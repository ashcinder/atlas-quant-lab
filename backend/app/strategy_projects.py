from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import DB_PATH
from app.quantjudge import canonical_json, sha256_hex, utc_now

ProjectStage = Literal["draft", "composed", "validated", "versioned", "published"]
ArtifactKind = Literal["strategy", "workflow", "research", "package", "report"]


class StrategyProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    thesis: str = Field(min_length=12, max_length=800)
    asset_symbol: str = Field(min_length=1, max_length=40)
    asset_class: str = Field(min_length=1, max_length=40)
    interval: Literal["15m", "1h", "4h", "1d", "1wk"] = "1d"
    benchmark: str = Field(default="BTC-USD", min_length=1, max_length=40)
    objective: Literal["sharpe", "calmar", "cagr", "total_return"] = "sharpe"
    deployment_mode: Literal["research", "paper", "live"] = "research"


class StrategyProjectUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=100)
    thesis: str | None = Field(default=None, min_length=12, max_length=800)
    asset_symbol: str | None = Field(default=None, min_length=1, max_length=40)
    asset_class: str | None = Field(default=None, min_length=1, max_length=40)
    interval: Literal["15m", "1h", "4h", "1d", "1wk"] | None = None
    benchmark: str | None = Field(default=None, min_length=1, max_length=40)
    objective: Literal["sharpe", "calmar", "cagr", "total_return"] | None = None
    deployment_mode: Literal["research", "paper", "live"] | None = None


class ProjectArtifactLink(BaseModel):
    expected_revision: int = Field(ge=1)
    kind: ArtifactKind
    artifact_id: str = Field(min_length=1, max_length=120)


class ProjectFreezeRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ProjectConflictError(RuntimeError):
    pass


class ProjectGateError(ValueError):
    pass


class StrategyProjectStore:
    """Project aggregate that binds every private strategy-development artifact.

    The table stores references and content hashes only; strategy source, workflow
    prompts, and raw decisions remain in their existing private stores.
    """

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    asset_symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    benchmark TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    deployment_mode TEXT NOT NULL,
                    custom_strategy_id TEXT,
                    strategy_hash TEXT,
                    workflow_id TEXT,
                    workflow_revision INTEGER,
                    workflow_hash TEXT,
                    workflow_valid INTEGER NOT NULL DEFAULT 0,
                    hard_risk_gates INTEGER NOT NULL DEFAULT 0,
                    research_job_id TEXT,
                    research_status TEXT,
                    research_hash TEXT,
                    research_robust INTEGER NOT NULL DEFAULT 0,
                    walk_forward_windows INTEGER NOT NULL DEFAULT 0,
                    oos_trade_count INTEGER NOT NULL DEFAULT 0,
                    average_oos_sharpe REAL,
                    package_id TEXT,
                    package_content_hash TEXT,
                    package_manifest_hash TEXT,
                    quant_report_id TEXT,
                    version TEXT,
                    commitment TEXT,
                    stage TEXT NOT NULL DEFAULT 'draft',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_projects_updated
                    ON strategy_projects(updated_at DESC);
                """
            )

    @staticmethod
    def _gate_state(row: sqlite3.Row | dict[str, Any]) -> list[dict[str, Any]]:
        values = dict(row)
        strategy_ready = bool(values.get("strategy_hash"))
        workflow_ready = (
            bool(values.get("workflow_valid")) and int(values.get("hard_risk_gates") or 0) >= 1
        )
        research_complete = values.get("research_status") == "completed"
        research_robust = bool(values.get("research_robust"))
        wf_ready = int(values.get("walk_forward_windows") or 0) >= 3
        sample_ready = int(values.get("oos_trade_count") or 0) >= 30
        version_ready = bool(values.get("commitment"))
        return [
            {
                "id": "thesis",
                "label": "研究假设已登记",
                "passed": len(values.get("thesis") or "") >= 12,
                "stage": "draft",
            },
            {
                "id": "strategy",
                "label": "策略制品已绑定",
                "passed": strategy_ready,
                "stage": "draft",
            },
            {
                "id": "workflow",
                "label": "AI 工作流与硬风控通过",
                "passed": workflow_ready,
                "stage": "composed",
            },
            {
                "id": "research",
                "label": "样本外研究已完成",
                "passed": research_complete,
                "stage": "validated",
            },
            {
                "id": "robust",
                "label": "稳健性阈值通过",
                "passed": research_robust,
                "stage": "validated",
            },
            {
                "id": "walk_forward",
                "label": "至少 3 个 Walk-forward 窗口",
                "passed": wf_ready,
                "stage": "validated",
            },
            {
                "id": "sample",
                "label": "样本外交易不少于 30 笔",
                "passed": sample_ready,
                "stage": "validated",
            },
            {
                "id": "version",
                "label": "版本承诺已冻结",
                "passed": version_ready,
                "stage": "versioned",
            },
        ]

    @classmethod
    def _stage(cls, row: sqlite3.Row | dict[str, Any]) -> ProjectStage:
        values = dict(row)
        if values.get("quant_report_id"):
            return "published"
        if values.get("commitment"):
            return "versioned"
        gates = {item["id"]: item["passed"] for item in cls._gate_state(values)}
        if all(
            gates[key]
            for key in ("strategy", "workflow", "research", "robust", "walk_forward", "sample")
        ):
            return "validated"
        if gates["strategy"] and gates["workflow"]:
            return "composed"
        return "draft"

    @classmethod
    def _public(cls, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["workflow_valid"] = bool(payload["workflow_valid"])
        payload["research_robust"] = bool(payload["research_robust"])
        payload["stage"] = cls._stage(payload)
        payload["gates"] = cls._gate_state(payload)
        passed = sum(1 for item in payload["gates"] if item["passed"])
        payload["completion"] = passed / len(payload["gates"])
        payload["next_gate"] = next((item for item in payload["gates"] if not item["passed"]), None)
        return payload

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self._public(row) for row in rows]

    def get(self, project_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return self._public(row)

    def create(self, request: StrategyProjectCreate) -> dict[str, Any]:
        project_id = f"sp_{uuid4().hex[:18]}"
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO strategy_projects (
                    id, name, thesis, asset_symbol, asset_class, interval, benchmark,
                    objective, deployment_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    request.name,
                    request.thesis,
                    request.asset_symbol,
                    request.asset_class,
                    request.interval,
                    request.benchmark,
                    request.objective,
                    request.deployment_mode,
                    now,
                    now,
                ),
            )
        return self.get(project_id)

    @staticmethod
    def _assert_revision(row: sqlite3.Row, expected: int) -> None:
        if row["revision"] != expected:
            raise ProjectConflictError(
                f"项目已在其他操作中更新（当前 r{row['revision']}，提交基于 r{expected}）"
            )

    def update(self, project_id: str, request: StrategyProjectUpdate) -> dict[str, Any]:
        changes = request.model_dump(exclude_none=True, exclude={"expected_revision"})
        if not changes:
            return self.get(project_id)
        allowed = {
            "name",
            "thesis",
            "asset_symbol",
            "asset_class",
            "interval",
            "benchmark",
            "objective",
            "deployment_mode",
        }
        changes = {key: value for key, value in changes.items() if key in allowed}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            self._assert_revision(row, request.expected_revision)
            research_invalidated = bool(
                {
                    "thesis",
                    "asset_symbol",
                    "asset_class",
                    "interval",
                    "benchmark",
                    "objective",
                }.intersection(changes)
            )
            assignments = [f"{key} = ?" for key in changes]
            values: list[Any] = list(changes.values())
            assignments.extend(
                ["version = NULL", "commitment = NULL", "quant_report_id = NULL"]
            )
            if research_invalidated:
                assignments.extend(
                    [
                        "research_job_id = NULL",
                        "research_status = NULL",
                        "research_hash = NULL",
                        "research_robust = 0",
                        "walk_forward_windows = 0",
                        "oos_trade_count = 0",
                        "average_oos_sharpe = NULL",
                    ]
                )
            assignments.extend(["revision = revision + 1", "updated_at = ?"])
            values.extend([utc_now().isoformat(), project_id])
            connection.execute(
                f"UPDATE strategy_projects SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(project_id)

    def _resolve_artifact(
        self, connection: sqlite3.Connection, project: sqlite3.Row, link: ProjectArtifactLink
    ) -> dict[str, Any]:
        if link.kind == "strategy":
            row = connection.execute(
                "SELECT id, spec_json FROM custom_strategies WHERE id = ?", (link.artifact_id,)
            ).fetchone()
            if row is None:
                raise ProjectGateError("自定义策略不存在")
            return {
                "custom_strategy_id": row["id"],
                "strategy_hash": sha256_hex(canonical_json(json.loads(row["spec_json"]))),
            }
        if link.kind == "workflow":
            row = connection.execute(
                "SELECT id, revision, graph_hash, validation_json FROM qj_workflows WHERE id = ?",
                (link.artifact_id,),
            ).fetchone()
            if row is None:
                raise ProjectGateError("工作流不存在；请先使用开发者凭证保存工作流")
            validation = json.loads(row["validation_json"])
            return {
                "workflow_id": row["id"],
                "workflow_revision": row["revision"],
                "workflow_hash": row["graph_hash"],
                "workflow_valid": int(validation["valid"]),
                "hard_risk_gates": int(validation["summary"].get("hard_risk_gates", 0)),
            }
        if link.kind == "research":
            row = connection.execute(
                "SELECT id, request_json, result_json, status FROM research_jobs WHERE id = ?",
                (link.artifact_id,),
            ).fetchone()
            if row is None:
                raise ProjectGateError("研究任务不存在")
            if row["status"] != "completed" or not row["result_json"]:
                raise ProjectGateError("研究任务尚未完成")
            request = json.loads(row["request_json"])
            result = json.loads(row["result_json"])
            if (
                request["symbol"] != project["asset_symbol"]
                or request["interval"] != project["interval"]
            ):
                raise ProjectGateError("研究任务的标的或周期与当前项目不一致")
            if request.get("objective") != project["objective"]:
                raise ProjectGateError("研究任务的排名目标与当前项目不一致")
            costs = sum(
                float(request.get(key, 0))
                for key in ("commission_rate", "slippage_rate", "spread_rate")
            )
            if costs <= 0:
                raise ProjectGateError("研究任务必须包含手续费、滑点或买卖价差")
            strategy_id = project["custom_strategy_id"]
            if not strategy_id:
                raise ProjectGateError(
                    "私密策略包必须先由隔离 Runner 生成内容哈希绑定的研究回执"
                )
            matching_experiment = next(
                (
                    experiment
                    for experiment in request.get("experiments", [])
                    if experiment.get("strategy_id") == strategy_id
                    and experiment.get("custom_strategy")
                ),
                None,
            )
            if matching_experiment is None:
                raise ProjectGateError("研究任务未包含当前项目绑定的策略版本")
            experiment_hash = sha256_hex(
                canonical_json(matching_experiment["custom_strategy"])
            )
            if experiment_hash != project["strategy_hash"]:
                raise ProjectGateError("研究任务使用的策略内容哈希与当前项目不一致")
            candidates = [
                item
                for item in result.get("candidates", [])
                if item.get("strategy_id") == strategy_id
            ]
            windows = [
                item
                for item in result.get("walk_forward", [])
                if item.get("strategy_id") == strategy_id
            ]
            if not candidates or not windows:
                raise ProjectGateError("研究结果缺少当前策略的样本外候选或滚动窗口")
            sharpes = [
                float(item["test_sharpe"])
                for item in windows
                if item.get("test_sharpe") is not None
            ]
            returns = [
                float(item["test_return"])
                for item in windows
                if item.get("test_return") is not None
            ]
            profitable_ratio = (
                sum(value > 0 for value in returns) / len(returns) if returns else 0.0
            )
            strategy_robust = bool(
                sharpes and mean(sharpes) > 0.5 and returns and profitable_ratio >= 0.6
            )
            return {
                "research_job_id": row["id"],
                "research_status": row["status"],
                "research_hash": sha256_hex(canonical_json(result)),
                "research_robust": int(strategy_robust),
                "walk_forward_windows": len(windows),
                "oos_trade_count": sum(int(item.get("trades") or 0) for item in windows),
                "average_oos_sharpe": mean(sharpes) if sharpes else None,
            }
        if link.kind == "package":
            row = connection.execute(
                """SELECT id, content_hash, manifest_hash, status
                   FROM qj_strategy_packages WHERE id = ?""",
                (link.artifact_id,),
            ).fetchone()
            if row is None or row["status"] != "validated":
                raise ProjectGateError("策略包不存在或未通过静态校验")
            return {
                "package_id": row["id"],
                "package_content_hash": row["content_hash"],
                "package_manifest_hash": row["manifest_hash"],
                "strategy_hash": row["content_hash"],
            }
        row = connection.execute(
            "SELECT id FROM qj_reports WHERE id = ?", (link.artifact_id,)
        ).fetchone()
        if row is None:
            raise ProjectGateError("QuantJudge 报告不存在")
        if not project["commitment"]:
            raise ProjectGateError("项目尚未冻结版本，不能绑定公开报告")
        return {"quant_report_id": row["id"]}

    def link_artifact(self, project_id: str, link: ProjectArtifactLink) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            self._assert_revision(row, link.expected_revision)
            changes = self._resolve_artifact(connection, row, link)
            assignments = [f"{key} = ?" for key in changes]
            values = list(changes.values())
            if link.kind != "report":
                assignments.extend(
                    ["version = NULL", "commitment = NULL", "quant_report_id = NULL"]
                )
            if link.kind in {"strategy", "package"}:
                assignments.extend(
                    [
                        "research_job_id = NULL",
                        "research_status = NULL",
                        "research_hash = NULL",
                        "research_robust = 0",
                        "walk_forward_windows = 0",
                        "oos_trade_count = 0",
                        "average_oos_sharpe = NULL",
                    ]
                )
            assignments.extend(["revision = revision + 1", "updated_at = ?"])
            values.extend([utc_now().isoformat(), project_id])
            connection.execute(
                f"UPDATE strategy_projects SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(project_id)

    def freeze(self, project_id: str, request: ProjectFreezeRequest) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise KeyError(project_id)
            self._assert_revision(row, request.expected_revision)
            missing = [
                item["label"]
                for item in self._gate_state(row)
                if item["id"] != "version" and not item["passed"]
            ]
            if missing:
                raise ProjectGateError("版本冻结前仍需完成：" + "、".join(missing))
            fingerprint = {
                "project_id": project_id,
                "version": request.version,
                "strategy_hash": row["strategy_hash"],
                "workflow_hash": row["workflow_hash"],
                "workflow_revision": row["workflow_revision"],
                "research_hash": row["research_hash"],
                "package_content_hash": row["package_content_hash"],
                "asset_symbol": row["asset_symbol"],
                "interval": row["interval"],
                "objective": row["objective"],
            }
            commitment = sha256_hex(canonical_json(fingerprint))
            connection.execute(
                """UPDATE strategy_projects SET version = ?, commitment = ?,
                   revision = revision + 1, updated_at = ? WHERE id = ?""",
                (request.version, commitment, utc_now().isoformat(), project_id),
            )
        return self.get(project_id)
