from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.config import DB_PATH
from app.data.service import MarketDataService
from app.indicators import calculate_indicators
from app.models import (
    AlertNotification,
    AlertRule,
    AlertRuleCreate,
    CustomStrategyRecord,
    CustomStrategySpec,
)
from app.strategies.custom import validate_rule_complexity


def _now() -> datetime:
    return datetime.now(UTC)


class WorkspaceStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS custom_strategies (
                    id TEXT PRIMARY KEY,
                    spec_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id TEXT PRIMARY KEY,
                    rule_json TEXT NOT NULL,
                    last_value REAL,
                    last_triggered_at TEXT,
                    last_evaluated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_notifications (
                    id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    value REAL NOT NULL,
                    triggered_at TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(alert_id) REFERENCES alert_rules(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_alert_notifications_time
                    ON alert_notifications(triggered_at DESC);
                """
            )

    def list_custom_strategies(self) -> list[CustomStrategyRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM custom_strategies ORDER BY updated_at DESC"
            ).fetchall()
        return [
            CustomStrategyRecord(
                id=row["id"],
                spec=CustomStrategySpec.model_validate_json(row["spec_json"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save_custom_strategy(self, spec: CustomStrategySpec) -> CustomStrategyRecord:
        validate_rule_complexity(spec.entry)
        validate_rule_complexity(spec.exit)
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM custom_strategies WHERE id=?", (spec.id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now.isoformat()
            connection.execute(
                "INSERT OR REPLACE INTO custom_strategies VALUES (?, ?, ?, ?)",
                (spec.id, spec.model_dump_json(), created_at, now.isoformat()),
            )
        return CustomStrategyRecord(id=spec.id, spec=spec, created_at=created_at, updated_at=now)

    def delete_custom_strategy(self, strategy_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM custom_strategies WHERE id=?", (strategy_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _alert_from_row(row: sqlite3.Row) -> AlertRule:
        payload = json.loads(row["rule_json"])
        return AlertRule(
            **payload,
            id=row["id"],
            last_value=row["last_value"],
            last_triggered_at=row["last_triggered_at"],
            last_evaluated_at=row["last_evaluated_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_alerts(self, enabled_only: bool = False) -> list[AlertRule]:
        query = "SELECT * FROM alert_rules"
        rows: list[sqlite3.Row]
        with self._connect() as connection:
            rows = connection.execute(f"{query} ORDER BY created_at DESC").fetchall()
        alerts = [self._alert_from_row(row) for row in rows]
        return [alert for alert in alerts if alert.enabled] if enabled_only else alerts

    def create_alert(self, rule: AlertRuleCreate) -> AlertRule:
        alert_id = str(uuid4())
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO alert_rules VALUES (?, ?, NULL, NULL, NULL, ?, ?)",
                (alert_id, rule.model_dump_json(), now.isoformat(), now.isoformat()),
            )
        return AlertRule(**rule.model_dump(), id=alert_id, created_at=now, updated_at=now)

    def update_alert(self, alert_id: str, rule: AlertRuleCreate) -> AlertRule | None:
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE alert_rules SET rule_json=?, updated_at=? WHERE id=?",
                (rule.model_dump_json(), now.isoformat(), alert_id),
            )
        if cursor.rowcount == 0:
            return None
        return next((item for item in self.list_alerts() if item.id == alert_id), None)

    def update_alert_state(
        self,
        alert_id: str,
        value: float,
        evaluated_at: datetime,
        triggered_at: datetime | None = None,
    ) -> None:
        with self._connect() as connection:
            if triggered_at is None:
                connection.execute(
                    "UPDATE alert_rules SET last_value=?, last_evaluated_at=?, "
                    "updated_at=? WHERE id=?",
                    (value, evaluated_at.isoformat(), evaluated_at.isoformat(), alert_id),
                )
            else:
                connection.execute(
                    "UPDATE alert_rules SET last_value=?, last_evaluated_at=?, "
                    "last_triggered_at=?, updated_at=? WHERE id=?",
                    (
                        value,
                        evaluated_at.isoformat(),
                        triggered_at.isoformat(),
                        evaluated_at.isoformat(),
                        alert_id,
                    ),
                )

    def delete_alert(self, alert_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM alert_notifications WHERE alert_id=?", (alert_id,))
            cursor = connection.execute("DELETE FROM alert_rules WHERE id=?", (alert_id,))
        return cursor.rowcount > 0

    def add_notification(self, alert: AlertRule, message: str, value: float) -> AlertNotification:
        notification = AlertNotification(
            id=str(uuid4()),
            alert_id=alert.id,
            title=alert.name,
            message=message,
            value=value,
            triggered_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO alert_notifications VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    notification.id,
                    notification.alert_id,
                    notification.title,
                    notification.message,
                    notification.value,
                    notification.triggered_at.isoformat(),
                ),
            )
        return notification

    def list_notifications(self, limit: int = 100) -> list[AlertNotification]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_notifications ORDER BY triggered_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AlertNotification(
                id=row["id"],
                alert_id=row["alert_id"],
                title=row["title"],
                message=row["message"],
                value=row["value"],
                triggered_at=row["triggered_at"],
                read=bool(row["is_read"]),
            )
            for row in rows
        ]

    def mark_notifications_read(self) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE alert_notifications SET is_read=1 WHERE is_read=0")


class AlertMonitor:
    def __init__(
        self,
        store: WorkspaceStore,
        data_service: MarketDataService,
        interval_seconds: int = 30,
    ) -> None:
        self.store = store
        self.data_service = data_service
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.run_lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="alert-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self.evaluate_all()
            except Exception:
                # Individual evaluations are best-effort; the next cycle retries.
                continue

    @staticmethod
    def _crossed(previous: float | None, current: float, threshold: float, above: bool) -> bool:
        if previous is None:
            return current > threshold if above else current < threshold
        return previous <= threshold < current if above else previous >= threshold > current

    def _evaluate_rule(self, alert: AlertRule, frame, indicators) -> tuple[bool, float, str]:
        latest = float(frame["close"].iloc[-1])
        previous_close = float(frame["close"].iloc[-2])
        threshold = float(alert.threshold or 0)
        kind = alert.kind
        if kind.startswith("price_"):
            value = latest
            above = kind in {"price_above", "price_crosses_above"}
            triggered = self._crossed(alert.last_value, value, threshold, above)
            return (
                triggered,
                value,
                f"{alert.symbol} 价格 {value:.6g} 已{'上穿' if above else '下穿'} {threshold:.6g}",
            )
        if kind == "change_pct_above":
            value = latest / previous_close - 1
            triggered = value >= threshold and (
                alert.last_value is None or alert.last_value < threshold
            )
            return (
                triggered,
                value,
                f"{alert.symbol} 单根K线涨幅 {value:.2%} 已超过 {threshold:.2%}",
            )
        if kind.startswith("rsi_"):
            series = indicators["rsi14"].dropna()
            value = float(series.iloc[-1])
            above = kind == "rsi_above"
            triggered = self._crossed(alert.last_value, value, threshold, above)
            return (
                triggered,
                value,
                f"{alert.symbol} RSI14 {value:.2f} 已{'上穿' if above else '下穿'} {threshold:.2f}",
            )
        macd = indicators["macd"].dropna()
        signal = indicators["macd_signal"].dropna()
        aligned = macd.to_frame("macd").join(signal.to_frame("signal"), how="inner")
        value = float(aligned["macd"].iloc[-1] - aligned["signal"].iloc[-1])
        above = kind == "macd_crosses_above"
        triggered = self._crossed(alert.last_value, value, 0.0, above)
        return triggered, value, f"{alert.symbol} MACD已{'金叉' if above else '死叉'}"

    def evaluate_all(self) -> list[AlertNotification]:
        if not self.run_lock.acquire(blocking=False):
            return []
        notifications: list[AlertNotification] = []
        try:
            alerts = self.store.list_alerts(enabled_only=True)
            grouped: dict[tuple[str, str, str, str], list[AlertRule]] = {}
            for alert in alerts:
                grouped.setdefault(
                    (alert.symbol, alert.asset_class, alert.interval, alert.data_source), []
                ).append(alert)
            for (symbol, asset_class, interval, source), rules in grouped.items():
                try:
                    bundle = self.data_service.fetch(
                        symbol, asset_class, interval, None, None, "auto", source
                    )
                    if len(bundle.frame) < 30:
                        continue
                    indicators = calculate_indicators(bundle.frame)
                    for alert in rules:
                        triggered, value, message = self._evaluate_rule(
                            alert, bundle.frame, indicators
                        )
                        now = _now()
                        cooldown_ok = (
                            alert.last_triggered_at is None
                            or now - alert.last_triggered_at
                            >= timedelta(minutes=alert.cooldown_minutes)
                        )
                        if triggered and cooldown_ok:
                            notifications.append(self.store.add_notification(alert, message, value))
                            self.store.update_alert_state(alert.id, value, now, now)
                        else:
                            self.store.update_alert_state(alert.id, value, now)
                except Exception:
                    continue
            return notifications
        finally:
            self.run_lock.release()
