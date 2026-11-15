from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import DB_PATH
from app.models import RunSummary


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
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_owner_time ON backtest_runs(owner_id, created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_lab ON backtest_runs(owner_id, lab_strategy_id, created_at DESC)"
            )

    def save(
        self, owner_id: str, mode: str, request: dict[str, Any], result: dict[str, Any],
        *, lab_strategy_id: str | None = None,
    ) -> None:
        symbol = request.get("symbol") or ", ".join(
            asset["symbol"] for asset in request.get("assets", [])
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                    (id, mode, strategy_id, symbol, request_json, result_json, created_at, status, owner_id, lab_strategy_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
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
                """SELECT * FROM backtest_runs WHERE owner_id=? AND lab_strategy_id=?
                   ORDER BY created_at DESC, id DESC LIMIT 50""", (owner_id, strategy_id)
            ).fetchall()
        return [
            {**self._summary(row).model_dump(), **json.loads(row["request_json"])["lab_snapshot"]}
            for row in rows
        ]

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
