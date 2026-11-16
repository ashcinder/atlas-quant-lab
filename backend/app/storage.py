from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import DB_PATH
from app.models import RunSummary


class DeletedLabComparison(ValueError):
    pass


class RunStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'completed'
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(backtest_runs)")
            }
            if "owner_id" not in columns:
                connection.execute(
                    "ALTER TABLE backtest_runs ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local'"
                )
            if "lab_strategy_id" not in columns:
                connection.execute("ALTER TABLE backtest_runs ADD COLUMN lab_strategy_id TEXT")
            if "lab_comparison_id" not in columns:
                connection.execute("ALTER TABLE backtest_runs ADD COLUMN lab_comparison_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_owner_time ON backtest_runs(owner_id, created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_lab ON backtest_runs(owner_id, lab_strategy_id, created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_lab_comparison ON backtest_runs(owner_id, lab_strategy_id, lab_comparison_id)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS deleted_lab_comparisons (
                    owner_id TEXT NOT NULL, strategy_id TEXT NOT NULL, comparison_id TEXT NOT NULL,
                    PRIMARY KEY (owner_id, strategy_id, comparison_id)
                )"""
            )

    def save(
        self, owner_id: str, mode: str, request: dict[str, Any], result: dict[str, Any],
        *, lab_strategy_id: str | None = None,
    ) -> None:
        symbol = request.get("symbol") or ", ".join(
            asset["symbol"] for asset in request.get("assets", [])
        )
        comparison_id = request.get("lab_snapshot", {}).get("comparison_id") if lab_strategy_id else None
        with self._connect() as connection:
            if comparison_id is not None:
                connection.execute("BEGIN IMMEDIATE")
                deleted = connection.execute(
                    "SELECT 1 FROM deleted_lab_comparisons WHERE owner_id=? AND strategy_id=? AND comparison_id=?",
                    (owner_id, lab_strategy_id, comparison_id),
                ).fetchone()
                if deleted:
                    raise DeletedLabComparison("这次回测已删除，报告不能重新写入")
            connection.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                    (id, mode, strategy_id, symbol, request_json, result_json, created_at, status, owner_id, lab_strategy_id, lab_comparison_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
                """,
                (
                    result["run_id"],
                    mode,
                    request["strategy_id"],
                    symbol,
                    json.dumps(request, ensure_ascii=False, default=str),
                    json.dumps(result, ensure_ascii=False, default=str),
                    result["created_at"],
                    owner_id,
                    lab_strategy_id,
                    comparison_id,
                ),
            )

    def save_computed(self, owner_id: str, mode: str, request: dict, result: dict, objects,
                      *, lab_strategy_id: str | None = None) -> None:
        digest = objects.put("private", result)
        # Keep only small searchable fields in SQLite. History and anchor callers
        # still use the same owner-checked store; large payloads live separately.
        index = {key: result[key] for key in ("run_id", "created_at", "metrics", "compute") if key in result}
        index["_object_sha256"] = digest
        normalized = {**request, "strategy_id": request.get("strategy_id", "research")}
        self.save(owner_id, mode, normalized, index, lab_strategy_id=lab_strategy_id)

    @staticmethod
    def _summary(row: sqlite3.Row) -> RunSummary:
        result = json.loads(row["result_json"])
        metrics = result.get("metrics", {})
        return RunSummary(
            id=row["id"], mode=row["mode"], strategy_id=row["strategy_id"],
            symbol=row["symbol"], created_at=row["created_at"], status=row["status"],
            total_return=metrics.get("total_return"), max_drawdown=metrics.get("max_drawdown"),
            compute=result.get("compute"),
        )

    def list(self, owner_id: str, limit: int = 50) -> list[RunSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM backtest_runs WHERE owner_id=? AND mode IN ('single','portfolio') ORDER BY created_at DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def list_lab(self, owner_id: str, strategy_id: str):
        with self._connect() as connection:
            rows = connection.execute(
                """WITH recent AS (
                    SELECT COALESCE(lab_comparison_id, id) AS batch
                    FROM backtest_runs WHERE owner_id=? AND lab_strategy_id=?
                    GROUP BY batch ORDER BY MAX(created_at) DESC, batch DESC LIMIT 50
                )
                SELECT r.* FROM backtest_runs r
                JOIN recent ON COALESCE(r.lab_comparison_id, r.id)=recent.batch
                WHERE r.owner_id=? AND r.lab_strategy_id=? ORDER BY r.created_at DESC, r.id DESC""",
                (owner_id, strategy_id, owner_id, strategy_id),
            ).fetchall()
        return [
            {**self._summary(row).model_dump(), **json.loads(row["request_json"])["lab_snapshot"]}
            for row in rows
        ]

    def delete_lab_run(self, owner_id: str, strategy_id: str, run_id: str) -> bool:
        scope = (owner_id, strategy_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT lab_comparison_id FROM backtest_runs WHERE owner_id=? AND lab_strategy_id=? AND id=?",
                (*scope, run_id),
            ).fetchone()
            if row is None:
                return False
            if row["lab_comparison_id"] is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO deleted_lab_comparisons VALUES (?, ?, ?)",
                    (*scope, row["lab_comparison_id"]),
                )
                connection.execute(
                    "DELETE FROM backtest_runs WHERE owner_id=? AND lab_strategy_id=? AND lab_comparison_id=?",
                    (*scope, row["lab_comparison_id"]),
                )
            else:
                connection.execute("DELETE FROM backtest_runs WHERE id=?", (run_id,))
        return True

    def get(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM backtest_runs WHERE id = ? AND owner_id = ?",
                (run_id, owner_id),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        if "_object_sha256" in result:
            from app.compute_objects import ComputeObjects
            return ComputeObjects().read("private", result["_object_sha256"])
        return result

    def delete(self, owner_id: str, run_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM backtest_runs WHERE id = ? AND owner_id = ?", (run_id, owner_id)
            )
        return cursor.rowcount > 0
