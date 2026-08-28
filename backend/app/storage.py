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

    def save(self, mode: str, request: dict[str, Any], result: dict[str, Any]) -> None:
        symbol = request.get("symbol") or ", ".join(
            asset["symbol"] for asset in request.get("assets", [])
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                    (id, mode, strategy_id, symbol, request_json, result_json, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')
                """,
                (
                    result["run_id"],
                    mode,
                    request["strategy_id"],
                    symbol,
                    json.dumps(request, ensure_ascii=False, default=str),
                    json.dumps(result, ensure_ascii=False, default=str),
                    result["created_at"],
                ),
            )

    def list(self, limit: int = 50) -> list[RunSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", (limit,)
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

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM backtest_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def delete(self, run_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM backtest_runs WHERE id = ?", (run_id,))
        return cursor.rowcount > 0
