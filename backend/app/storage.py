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
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_runs_owner_time ON backtest_runs(owner_id, created_at DESC)"
            )

    def save(
        self, owner_id: str, mode: str, request: dict[str, Any], result: dict[str, Any]
    ) -> None:
        symbol = request.get("symbol") or ", ".join(
            asset["symbol"] for asset in request.get("assets", [])
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                    (id, mode, strategy_id, symbol, request_json, result_json, created_at, status, owner_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?)
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
                ),
            )

    def list(self, owner_id: str, limit: int = 50) -> list[RunSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM backtest_runs WHERE owner_id=? ORDER BY created_at DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        output = []
        for row in rows:
            result = json.loads(row["result_json"])
            metrics = result.get("metrics", {})
            output.append(
                RunSummary(
                    id=row["id"],
                    mode=row["mode"],
                    strategy_id=row["strategy_id"],
                    symbol=row["symbol"],
                    created_at=row["created_at"],
                    total_return=metrics.get("total_return"),
                    max_drawdown=metrics.get("max_drawdown"),
                    status=row["status"],
                )
            )
        return output

    def get(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM backtest_runs WHERE id = ? AND owner_id = ?",
                (run_id, owner_id),
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def delete(self, owner_id: str, run_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM backtest_runs WHERE id = ? AND owner_id = ?", (run_id, owner_id)
            )
        return cursor.rowcount > 0
