from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean, stdev
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.config import DATA_DIR, DB_PATH
from app.quantjudge_models import PerformanceReportCreate, QuantAgentCreate, SubscriptionCreate
from app.supervisor_client import SupervisorClient, SupervisorRPCError
from app.zkp_models import ZkPublicStatement

if TYPE_CHECKING:
    from app.zkp import ZkProofStore


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def json_list(value: str) -> list[Any]:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def merkle_root(commitments: list[str]) -> str:
    if not commitments:
        raise ValueError("决策承诺不能为空")
    level = [bytes.fromhex(item) for item in commitments]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[index] + level[index + 1]).digest() for index in range(0, len(level), 2)]
    return level[0].hex()


def _safe_float(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(value, 8)


def calculate_public_metrics(points: list[dict[str, Any]], report_type: str) -> dict[str, float | int]:
    values = [float(point["equity"]) for point in points]
    timestamps = [int(point["time"]) for point in points]
    returns = [values[index] / values[index - 1] - 1 for index in range(1, len(values))]
    peaks: list[float] = []
    peak = values[0]
    for value in values:
        peak = max(peak, value)
        peaks.append(value / peak - 1)
    elapsed_days = max((timestamps[-1] - timestamps[0]) / 86_400, 1)
    annual_factor = min(365 / elapsed_days, 10)
    total_return = values[-1] / values[0] - 1
    cagr = (values[-1] / values[0]) ** annual_factor - 1 if values[-1] > 0 else -1
    periods_per_year = max((len(returns) / elapsed_days) * 365, 1)
    volatility = stdev(returns) * math.sqrt(periods_per_year) if len(returns) > 1 else 0.0
    sharpe = (fmean(returns) / stdev(returns) * math.sqrt(periods_per_year)) if len(returns) > 1 and stdev(returns) else 0.0
    wins = sum(item > 0 for item in returns)
    benchmark_values = [point.get("benchmark") for point in points]
    valid_benchmark = benchmark_values[0] is not None and benchmark_values[-1] is not None
    benchmark_return = (
        float(benchmark_values[-1]) / float(benchmark_values[0]) - 1 if valid_benchmark else 0.0
    )
    return {
        "total_return": _safe_float(total_return),
        "annualized_return": _safe_float(cagr),
        "max_drawdown": _safe_float(min(peaks)),
        "annualized_volatility": _safe_float(volatility),
        "sharpe": _safe_float(sharpe),
        "win_rate": _safe_float(wins / len(returns)) if returns else 0.0,
        "benchmark_return": _safe_float(benchmark_return),
        "observation_count": len(points),
        "live_days": int(elapsed_days) if report_type == "live" else 0,
    }


def public_curve(points: list[dict[str, Any]], limit: int = 96) -> list[dict[str, float | int]]:
    step = max(1, math.ceil(len(points) / limit))
    selected = points[::step]
    if selected[-1] is not points[-1]:
        selected.append(points[-1])
    initial = float(points[0]["equity"])
    benchmark_initial = float(points[0].get("benchmark") or initial)
    return [
        {
            "time": int(point["time"]),
            "return": _safe_float(float(point["equity"]) / initial - 1),
            "benchmark_return": _safe_float(float(point.get("benchmark") or benchmark_initial) / benchmark_initial - 1),
        }
        for point in selected
    ]


class ReceiptAttestor:
    def __init__(self, key_path: Path = DATA_DIR / "quantjudge_attestation.key"):
        self.key_path = key_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            self._private_key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
        else:
            self._private_key = Ed25519PrivateKey.generate()
            raw = self._private_key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            key_path.write_bytes(raw)
        os.chmod(key_path, 0o600)

    @property
    def public_key(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    @property
    def key_id(self) -> str:
        return f"atlas-ed25519:{sha256_hex(base64.b64decode(self.public_key))[:16]}"

    def sign(self, receipt_hash: str) -> str:
        return base64.b64encode(self._private_key.sign(bytes.fromhex(receipt_hash))).decode("ascii")

    def verify(self, receipt_hash: str, signature: str) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(self.public_key)).verify(
                base64.b64decode(signature), bytes.fromhex(receipt_hash)
            )
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


class QuantJudgeStore:
    def __init__(
        self,
        path: Path = DB_PATH,
        *,
        attestor: ReceiptAttestor | None = None,
        supervisor: SupervisorClient | None = None,
        proof_store: ZkProofStore | None = None,
        seed_demo: bool = True,
    ):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.attestor = attestor or ReceiptAttestor(self.path.parent / "quantjudge_attestation.key")
        self.supervisor = supervisor or SupervisorClient()
        self.proof_store = proof_store
        self._initialize()
        if seed_demo:
            self._seed_demo()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS qj_agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    developer_alias TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    asset_classes_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    monthly_price REAL NOT NULL,
                    price_currency TEXT NOT NULL,
                    strategy_commitment TEXT NOT NULL,
                    developer_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qj_reports (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES qj_agents(id) ON DELETE CASCADE,
                    report_type TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    curve_json TEXT NOT NULL,
                    decision_count INTEGER NOT NULL,
                    decision_merkle_root TEXT NOT NULL,
                    market_data_hash TEXT NOT NULL,
                    previous_receipt_hash TEXT,
                    receipt_payload_json TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    attestation_key_id TEXT NOT NULL,
                    attestation_signature TEXT NOT NULL,
                    external_proof_json TEXT,
                    chain_tx_hash TEXT,
                    chain_status TEXT NOT NULL DEFAULT 'not_anchored',
                    chain_block_number INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_qj_reports_agent_created
                    ON qj_reports(agent_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS qj_subscriptions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES qj_agents(id) ON DELETE CASCADE,
                    investor_alias TEXT NOT NULL,
                    billing_cycle TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payment_mode TEXT NOT NULL,
                    payment_reference TEXT,
                    started_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_qj_subscriptions_investor
                    ON qj_subscriptions(investor_alias, created_at DESC);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(qj_reports)")}
            if "zk_proof_id" not in columns:
                connection.execute("ALTER TABLE qj_reports ADD COLUMN zk_proof_id TEXT")
            if "evidence_level" not in columns:
                connection.execute(
                    "ALTER TABLE qj_reports ADD COLUMN evidence_level TEXT NOT NULL "
                    "DEFAULT 'platform_attested'"
                )

    def bind_proof_store(self, proof_store: ZkProofStore) -> None:
        self.proof_store = proof_store

    @staticmethod
    def _token_hash(token: str) -> str:
        return sha256_hex(token)

    def _assert_token(self, agent_id: str, token: str | None) -> sqlite3.Row:
        if not token:
            raise PermissionError("缺少开发者凭证")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM qj_agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        if row["is_demo"]:
            raise PermissionError("演示 Agent 为只读样本")
        if not hmac.compare_digest(row["developer_token_hash"], self._token_hash(token)):
            raise PermissionError("开发者凭证无效")
        return row

    def create_agent(self, request: QuantAgentCreate) -> dict[str, Any]:
        agent_id = f"qja_{uuid4().hex[:16]}"
        token = f"qjt_{secrets.token_urlsafe(32)}"
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO qj_agents (
                    id, name, developer_alias, agent_type, category, asset_classes_json,
                    description, risk_level, monthly_price, price_currency, strategy_commitment,
                    developer_token_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id, request.name, request.developer_alias, request.agent_type,
                    request.category, canonical_json(request.asset_classes), request.description,
                    request.risk_level, request.monthly_price, request.price_currency,
                    request.strategy_commitment, self._token_hash(token), now, now,
                ),
            )
        return {"agent": self.get_agent(agent_id), "developer_token": token, "token_shown_once": True}

    def _latest_report(self, connection: sqlite3.Connection, agent_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM qj_reports WHERE agent_id = ? ORDER BY period_end DESC, created_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()

    @staticmethod
    def _score(
        metrics: dict[str, Any], report_type: str, chain_status: str, zk_verified: bool
    ) -> float:
        sharpe = max(-1, min(float(metrics.get("sharpe", 0)), 4))
        drawdown = abs(min(float(metrics.get("max_drawdown", 0)), 0))
        annualized = max(-0.5, min(float(metrics.get("annualized_return", 0)), 2))
        evidence = (
            4
            + (7 if report_type == "live" else 0)
            + (8 if chain_status == "confirmed" else 0)
            + (10 if zk_verified else 0)
        )
        return round(max(0, min(100, 48 + sharpe * 10 + annualized * 12 - drawdown * 35 + evidence)), 1)

    def _report_public(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json_object(row["receipt_payload_json"])
        receipt_integrity = all(
            [
                hmac.compare_digest(sha256_hex(row["receipt_payload_json"]), row["receipt_hash"]),
                self.attestor.verify(row["receipt_hash"], row["attestation_signature"]),
                payload.get("report_id") == row["id"],
                payload.get("agent_id") == row["agent_id"],
                isinstance(payload.get("metrics"), dict),
            ]
        )
        curve = json_list(row["curve_json"])
        expected_curve_hash = payload.get("public_curve_hash")
        curve_integrity = (
            hmac.compare_digest(expected_curve_hash, sha256_hex(row["curve_json"]))
            if isinstance(expected_curve_hash, str)
            else None
        )
        metrics = payload.get("metrics", {}) if receipt_integrity else {}
        external = payload.get("external_proof") if receipt_integrity else None
        zk_verified = bool(row["zk_proof_id"]) and row["evidence_level"] == "zk_verified"
        return {
            "id": row["id"],
            "report_type": payload.get("report_type", row["report_type"]),
            "period_start": payload.get("period_start", row["period_start"]),
            "period_end": payload.get("period_end", row["period_end"]),
            "metrics": metrics,
            "public_curve": curve if receipt_integrity and curve_integrity is not False else [],
            "decision_count": payload.get("decision_count", 0),
            "decision_merkle_root": payload.get("decision_merkle_root", ""),
            "market_data_hash": payload.get("market_data_hash", ""),
            "previous_receipt_hash": payload.get("previous_receipt_hash"),
            "receipt_hash": row["receipt_hash"],
            "attestation_key_id": row["attestation_key_id"],
            "attestation_signature": row["attestation_signature"],
            "external_proof": external,
            "zk_proof_id": row["zk_proof_id"],
            "evidence_level": row["evidence_level"],
            "chain_tx_hash": row["chain_tx_hash"],
            "chain_status": row["chain_status"],
            "chain_block_number": row["chain_block_number"],
            "score": self._score(metrics, row["report_type"], row["chain_status"], zk_verified)
            if receipt_integrity
            else 0,
            "created_at": payload.get("created_at", row["created_at"]),
            "receipt_integrity_valid": receipt_integrity,
            "public_curve_integrity_valid": curve_integrity,
            "privacy": {"source_hidden": True, "decisions_hidden": True, "raw_equity_discarded": True},
        }

    def _agent_public(self, row: sqlite3.Row, latest: sqlite3.Row | None, subscribers: int) -> dict[str, Any]:
        report = self._report_public(latest) if latest else None
        return {
            "id": row["id"],
            "name": row["name"],
            "developer_alias": row["developer_alias"],
            "agent_type": row["agent_type"],
            "category": row["category"],
            "asset_classes": json.loads(row["asset_classes_json"]),
            "description": row["description"],
            "risk_level": row["risk_level"],
            "monthly_price": row["monthly_price"],
            "price_currency": row["price_currency"],
            "strategy_commitment": row["strategy_commitment"],
            "status": row["status"],
            "is_demo": bool(row["is_demo"]),
            "subscriber_count": subscribers,
            "latest_report": report,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_agents(
        self, *, category: str | None = None, report_type: str | None = None, query: str = ""
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM qj_agents WHERE status = 'active'"
        params: list[Any] = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if query:
            sql += " AND (name LIKE ? OR developer_alias LIKE ? OR description LIKE ?)"
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            agents = []
            for row in rows:
                latest = self._latest_report(connection, row["id"])
                if report_type and (latest is None or latest["report_type"] != report_type):
                    continue
                subscribers = connection.execute(
                    "SELECT COUNT(*) FROM qj_subscriptions WHERE agent_id = ? AND status = 'active'",
                    (row["id"],),
                ).fetchone()[0]
                agents.append(self._agent_public(row, latest, subscribers))
        agents.sort(key=lambda item: item["latest_report"]["score"] if item["latest_report"] else -1, reverse=True)
        for rank, agent in enumerate(agents, 1):
            agent["rank"] = rank
        return agents

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM qj_agents WHERE id = ?", (agent_id,)).fetchone()
            if row is None:
                raise KeyError(agent_id)
            latest = self._latest_report(connection, agent_id)
            subscribers = connection.execute(
                "SELECT COUNT(*) FROM qj_subscriptions WHERE agent_id = ? AND status = 'active'", (agent_id,)
            ).fetchone()[0]
            reports = connection.execute(
                "SELECT * FROM qj_reports WHERE agent_id = ? ORDER BY period_end DESC", (agent_id,)
            ).fetchall()
        result = self._agent_public(row, latest, subscribers)
        result["reports"] = [self._report_public(report) for report in reports]
        return result

    def publish_report(
        self, agent_id: str, request: PerformanceReportCreate, developer_token: str | None
    ) -> dict[str, Any]:
        agent = self._assert_token(agent_id, developer_token)
        points = [point.model_dump() for point in request.equity_points]
        metrics = calculate_public_metrics(points, request.report_type)
        root = merkle_root(request.decision_commitments)
        curve_json = canonical_json(public_curve(points))
        report_id = f"qjr_{uuid4().hex[:18]}"
        external = request.external_proof.model_dump() if request.external_proof else None
        with self._connect() as connection:
            # Serialize appends per database so two concurrent reports cannot fork the receipt chain.
            connection.execute("BEGIN IMMEDIATE")
            created_at = utc_now().isoformat()
            previous = connection.execute(
                "SELECT receipt_hash FROM qj_reports WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            payload = {
                "schema": "atlas.quantjudge.receipt.v1",
                "report_id": report_id,
                "agent_id": agent_id,
                "strategy_commitment": agent["strategy_commitment"],
                "report_type": request.report_type,
                "period_start": request.period_start.isoformat(),
                "period_end": request.period_end.isoformat(),
                "metrics": metrics,
                "public_curve_hash": sha256_hex(curve_json),
                "decision_count": len(request.decision_commitments),
                "decision_merkle_root": root,
                "market_data_hash": request.market_data_hash,
                "previous_receipt_hash": previous["receipt_hash"] if previous else None,
                "external_proof": external,
                "created_at": created_at,
            }
            payload_json = canonical_json(payload)
            receipt_hash = sha256_hex(payload_json)
            signature = self.attestor.sign(receipt_hash)
            connection.execute(
                """
                INSERT INTO qj_reports (
                    id, agent_id, report_type, period_start, period_end, metrics_json, curve_json,
                    decision_count, decision_merkle_root, market_data_hash, previous_receipt_hash,
                    receipt_payload_json, receipt_hash, attestation_key_id, attestation_signature,
                    external_proof_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id, agent_id, request.report_type, request.period_start.isoformat(),
                    request.period_end.isoformat(), canonical_json(metrics), curve_json,
                    len(request.decision_commitments), root, request.market_data_hash,
                    previous["receipt_hash"] if previous else None, payload_json, receipt_hash,
                    self.attestor.key_id,
                    signature,
                    canonical_json(external) if external else None,
                    created_at,
                ),
            )
            connection.execute(
                "UPDATE qj_agents SET updated_at = ? WHERE id = ?",
                (created_at, agent_id),
            )
        # Full equity values and decisions are intentionally not persisted.
        return self.get_report(report_id)

    def publish_zk_report(
        self, agent_id: str, proof_id: str, developer_token: str | None
    ) -> dict[str, Any]:
        """Publish directly from a verified zkVM journal; no private witness is uploaded."""
        agent = self._assert_token(agent_id, developer_token)
        if self.proof_store is None:
            raise RuntimeError("ZKP proof store 未配置")
        proof = self.proof_store.get_verified_for_agent(proof_id, agent_id)
        statement = ZkPublicStatement.model_validate_json(proof["public_statement_json"])
        metrics = statement.metrics.as_public_metrics()
        curve = [point.as_public_point() for point in statement.public_curve]
        curve_json = canonical_json(curve)
        if not hmac.compare_digest(statement.curve_commitment(), statement.equity_curve_hash):
            raise ValueError("ZKP journal 的公开净值曲线哈希不匹配")
        report_id = f"qjr_{uuid4().hex[:18]}"
        external = {
            "proof_type": "zk_stark",
            "proof_profile": statement.proof_profile,
            "proof_id": proof_id,
            "proof_hash": proof["proof_hash"],
            "public_inputs_hash": proof["public_inputs_hash"],
            "image_id": proof["image_id"],
            "verifier": "risc0-zkvm",
            "verifier_version": proof["verifier_version"],
            "receipt_kind": proof["receipt_kind"],
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """SELECT receipt_hash FROM qj_reports
                   WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1""",
                (agent_id,),
            ).fetchone()
            expected_previous = previous["receipt_hash"] if previous else None
            if statement.previous_receipt_hash != expected_previous:
                raise ValueError("证明已过期：Agent 回执链在证明生成后发生变化，请重新生成证明")
            consumed = connection.execute(
                "SELECT report_id FROM qj_zk_proofs WHERE id = ?", (proof_id,)
            ).fetchone()
            if consumed is None or consumed["report_id"] is not None:
                raise ValueError("证明不存在或已经发布，禁止重复使用")
            created_at = utc_now().isoformat()
            payload = {
                "schema": "atlas.quantjudge.receipt.v2",
                "report_id": report_id,
                "agent_id": agent_id,
                "strategy_commitment": agent["strategy_commitment"],
                "workflow_commitment": statement.workflow_commitment,
                "report_type": statement.report_type,
                "period_start": datetime.fromtimestamp(statement.period_start, UTC).isoformat(),
                "period_end": datetime.fromtimestamp(statement.period_end, UTC).isoformat(),
                "metrics": metrics,
                "public_curve_hash": statement.equity_curve_hash,
                "decision_count": statement.decision_count,
                "decision_merkle_root": statement.decision_merkle_root,
                "market_data_hash": statement.market_data_hash,
                "cost_model_hash": statement.cost_model_hash,
                "previous_receipt_hash": expected_previous,
                "external_proof": external,
                "nullifier": statement.nullifier,
                "created_at": created_at,
            }
            payload_json = canonical_json(payload)
            receipt_hash = sha256_hex(payload_json)
            signature = self.attestor.sign(receipt_hash)
            connection.execute(
                """
                INSERT INTO qj_reports (
                    id, agent_id, report_type, period_start, period_end, metrics_json, curve_json,
                    decision_count, decision_merkle_root, market_data_hash, previous_receipt_hash,
                    receipt_payload_json, receipt_hash, attestation_key_id, attestation_signature,
                    external_proof_json, zk_proof_id, evidence_level, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'zk_verified', ?)
                """,
                (
                    report_id,
                    agent_id,
                    statement.report_type,
                    payload["period_start"],
                    payload["period_end"],
                    canonical_json(metrics),
                    curve_json,
                    statement.decision_count,
                    statement.decision_merkle_root,
                    statement.market_data_hash,
                    expected_previous,
                    payload_json,
                    receipt_hash,
                    self.attestor.key_id,
                    signature,
                    canonical_json(external),
                    proof_id,
                    created_at,
                ),
            )
            connection.execute(
                "UPDATE qj_zk_proofs SET report_id = ? WHERE id = ? AND report_id IS NULL",
                (report_id, proof_id),
            )
            connection.execute(
                "UPDATE qj_agents SET updated_at = ? WHERE id = ?", (created_at, agent_id)
            )
        return self.get_report(report_id)

    @staticmethod
    def _expected_anchor_input(row: sqlite3.Row) -> str:
        if row["zk_proof_id"]:
            external = json_object(row["external_proof_json"])
            fields = [
                row["receipt_hash"],
                str(external.get("proof_hash", "")),
                str(external.get("public_inputs_hash", "")),
                str(json_object(row["receipt_payload_json"]).get("nullifier", "")),
            ]
            if all(len(value) == 64 for value in fields):
                return "0x" + b"ATLASZK2".hex() + "".join(fields)
        return "0x" + b"ATLASQJ1".hex() + row["receipt_hash"]

    def get_report(self, report_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qj_reports WHERE id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        return self._report_public(row)

    def verify_report(self, report_id: str, *, refresh_chain: bool = True) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT r.*, a.strategy_commitment AS current_strategy_commitment
                   FROM qj_reports r JOIN qj_agents a ON a.id = r.agent_id
                   WHERE r.id = ?""",
                (report_id,),
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        payload = json_object(row["receipt_payload_json"])
        payload_hash = sha256_hex(row["receipt_payload_json"])
        hash_valid = hmac.compare_digest(payload_hash, row["receipt_hash"])
        signature_valid = hash_valid and self.attestor.verify(
            row["receipt_hash"], row["attestation_signature"]
        )
        record_integrity_valid = all(
            [
                payload.get("report_id") == row["id"],
                payload.get("agent_id") == row["agent_id"],
                payload.get("strategy_commitment") == row["current_strategy_commitment"],
                payload.get("report_type") == row["report_type"],
                payload.get("period_start") == row["period_start"],
                payload.get("period_end") == row["period_end"],
                canonical_json(payload.get("metrics"))
                == canonical_json(json_object(row["metrics_json"])),
                payload.get("decision_count") == row["decision_count"],
                payload.get("decision_merkle_root") == row["decision_merkle_root"],
                payload.get("market_data_hash") == row["market_data_hash"],
                payload.get("previous_receipt_hash") == row["previous_receipt_hash"],
            ]
        )
        expected_curve_hash = payload.get("public_curve_hash")
        curve_integrity_valid = (
            hmac.compare_digest(expected_curve_hash, sha256_hex(row["curve_json"]))
            if isinstance(expected_curve_hash, str)
            else None
        )
        chain_result: dict[str, Any] = {
            "status": row["chain_status"],
            "transaction_hash": row["chain_tx_hash"],
            "block_number": row["chain_block_number"],
        }
        if refresh_chain and row["chain_tx_hash"]:
            try:
                supervisor_status = self.supervisor.status()
                if not supervisor_status.connected:
                    raise SupervisorRPCError(supervisor_status.error or "Supervisor RPC 不可用")
                if supervisor_status.chain_id != 1051:
                    chain_result.update(
                        status="wrong_chain",
                        observed_chain_id=supervisor_status.chain_id,
                    )
                    raise SupervisorRPCError(
                        f"Supervisor 链 ID 不匹配: {supervisor_status.chain_id}, 期望 1051"
                    )
                receipt = self.supervisor.transaction_receipt(row["chain_tx_hash"])
                transaction = self.supervisor.transaction(row["chain_tx_hash"])
                expected_input = self._expected_anchor_input(row)
                input_matches = (
                    bool(transaction)
                    and str(transaction.get("input", "")).lower() == expected_input
                )
                chain_result["payload_matches"] = input_matches
                chain_result["expected_input"] = expected_input
                if receipt and receipt.get("status") == "0x1" and input_matches:
                    block = int(receipt.get("blockNumber", "0x0"), 16)
                    chain_result.update(status="confirmed", block_number=block)
                    with self._connect() as connection:
                        connection.execute(
                            """UPDATE qj_reports
                               SET chain_status = 'confirmed', chain_block_number = ?
                               WHERE id = ?""",
                            (block, report_id),
                        )
                elif receipt and receipt.get("status") == "0x1":
                    chain_result["status"] = "payload_mismatch"
                elif receipt:
                    chain_result["status"] = "failed"
            except (SupervisorRPCError, ValueError) as exc:
                if chain_result["status"] != "wrong_chain":
                    chain_result["status"] = "unreachable"
                chain_result["error"] = str(exc)
        external = json.loads(row["external_proof_json"]) if row["external_proof_json"] else None
        proof_record_valid = False
        proof_file_valid = False
        proof_cryptographic_valid = False
        if row["zk_proof_id"]:
            with self._connect() as connection:
                proof = connection.execute(
                    "SELECT * FROM qj_zk_proofs WHERE id = ? AND status = 'verified'",
                    (row["zk_proof_id"],),
                ).fetchone()
            if proof is not None and external:
                statement = json_object(proof["public_statement_json"])
                proof_record_valid = all(
                    [
                        hmac.compare_digest(
                            proof["proof_hash"], str(external.get("proof_hash", ""))
                        ),
                        hmac.compare_digest(
                            proof["public_inputs_hash"], str(external.get("public_inputs_hash", ""))
                        ),
                        hmac.compare_digest(
                            proof["public_inputs_hash"], sha256_hex(proof["public_statement_json"])
                        ),
                        statement.get("strategy_commitment") == payload.get("strategy_commitment"),
                        statement.get("market_data_hash") == payload.get("market_data_hash"),
                        statement.get("decision_merkle_root")
                        == payload.get("decision_merkle_root"),
                        statement.get("nullifier") == payload.get("nullifier"),
                    ]
                )
                if self.proof_store is not None:
                    try:
                        self.proof_store.reverify(row["zk_proof_id"])
                        proof_file_valid = True
                        proof_cryptographic_valid = True
                    except (KeyError, ValueError, RuntimeError):
                        proof_file_valid = False
                        proof_cryptographic_valid = False
        external_verified = proof_record_valid and proof_cryptographic_valid
        return {
            "report_id": report_id,
            "receipt_hash": row["receipt_hash"],
            "receipt_hash_valid": hash_valid,
            "attestation_signature_valid": signature_valid,
            "record_integrity_valid": record_integrity_valid,
            "public_curve_integrity_valid": curve_integrity_valid,
            "calculation_verified": signature_valid and record_integrity_valid,
            "decision_merkle_root": row["decision_merkle_root"],
            "strategy_commitment": payload.get("strategy_commitment", ""),
            "external_proof": external,
            "external_proof_verified": external_verified,
            "zk_proof_id": row["zk_proof_id"],
            "evidence_level": row["evidence_level"],
            "proof_file_integrity_valid": proof_file_valid if row["zk_proof_id"] else None,
            "proof_cryptographic_valid": (
                proof_cryptographic_valid if row["zk_proof_id"] else None
            ),
            "chain": chain_result,
            "proof_scope": [
                "ZKP 报告由登记的固定 zkVM 程序执行并验证 receipt；传统报告仍由平台重算",
                "策略源码、Agent 参数、提示词与原始决策未公开且未持久化",
                "决策 Merkle 根可证明后续披露的决策属于当时提交集合",
                "只有 chain.status=confirmed 时才表示回执哈希已在 Supervisor 链确认",
            ],
            "limitations": [
                "只有 evidence_level=zk_verified 且 external_proof_verified=true "
                "才是零知识证明报告",
                "当前 ZKP profile 仅覆盖确定性 SMA 回测；任意 Python、外部 AI "
                "与实盘成交不在证明范围",
                "Supervisor 当前锚定证明/公开输入/回执/nullifier 哈希，"
                "不在链上重新执行 zkVM verifier",
            ],
        }

    def submit_anchor(
        self,
        report_id: str,
        signed_raw_transaction: str,
        developer_token: str | None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            report = connection.execute(
                "SELECT agent_id FROM qj_reports WHERE id = ?", (report_id,)
            ).fetchone()
        if report is None:
            raise KeyError(report_id)
        self._assert_token(report["agent_id"], developer_token)
        status = self.supervisor.status()
        if not status.connected:
            raise SupervisorRPCError(status.error or "Supervisor RPC 不可用")
        if status.chain_id != 1051:
            raise SupervisorRPCError(f"Supervisor 链 ID 不匹配: {status.chain_id}, 期望 1051")
        transaction_hash = self.supervisor.submit_signed_transaction(signed_raw_transaction)
        with self._connect() as connection:
            connection.execute(
                "UPDATE qj_reports SET chain_tx_hash = ?, chain_status = 'submitted' WHERE id = ?",
                (transaction_hash, report_id),
            )
        return self.verify_report(report_id)

    def attach_transaction(self, report_id: str, transaction_hash: str, developer_token: str | None) -> dict[str, Any]:
        with self._connect() as connection:
            report = connection.execute("SELECT agent_id FROM qj_reports WHERE id = ?", (report_id,)).fetchone()
        if report is None:
            raise KeyError(report_id)
        self._assert_token(report["agent_id"], developer_token)
        with self._connect() as connection:
            connection.execute(
                "UPDATE qj_reports SET chain_tx_hash = ?, chain_status = 'submitted' WHERE id = ?",
                (transaction_hash.lower(), report_id),
            )
        return self.verify_report(report_id)

    def subscribe(self, agent_id: str, request: SubscriptionCreate) -> dict[str, Any]:
        with self._connect() as connection:
            agent = connection.execute("SELECT * FROM qj_agents WHERE id = ?", (agent_id,)).fetchone()
        if agent is None:
            raise KeyError(agent_id)
        multiplier = {"monthly": 1, "quarterly": 3, "yearly": 12}[request.billing_cycle]
        amount = float(agent["monthly_price"]) * multiplier
        payment_mode = "external_reference" if request.payment_reference else "sandbox"
        status = "active" if payment_mode == "sandbox" or amount == 0 else "pending_verification"
        started = utc_now()
        expires = started + timedelta(days={"monthly": 30, "quarterly": 90, "yearly": 365}[request.billing_cycle])
        subscription_id = f"qjs_{uuid4().hex[:18]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO qj_subscriptions (
                    id, agent_id, investor_alias, billing_cycle, amount, currency, status,
                    payment_mode, payment_reference, started_at, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id, agent_id, request.investor_alias, request.billing_cycle,
                    amount, agent["price_currency"], status, payment_mode, request.payment_reference,
                    started.isoformat(), expires.isoformat(), started.isoformat(),
                ),
            )
        return self.get_subscription(subscription_id)

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.*, a.name AS agent_name FROM qj_subscriptions s
                   JOIN qj_agents a ON a.id = s.agent_id WHERE s.id = ?""",
                (subscription_id,),
            ).fetchone()
        if row is None:
            raise KeyError(subscription_id)
        return dict(row)

    def list_subscriptions(self, investor_alias: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT s.*, a.name AS agent_name FROM qj_subscriptions s
                   JOIN qj_agents a ON a.id = s.agent_id
                   WHERE s.investor_alias = ? ORDER BY s.created_at DESC""",
                (investor_alias,),
            ).fetchall()
        return [dict(row) for row in rows]

    def overview(self) -> dict[str, Any]:
        agents = self.list_agents()
        with self._connect() as connection:
            reports = connection.execute("SELECT COUNT(*) FROM qj_reports").fetchone()[0]
            live_reports = connection.execute("SELECT COUNT(*) FROM qj_reports WHERE report_type = 'live'").fetchone()[0]
            confirmed = connection.execute("SELECT COUNT(*) FROM qj_reports WHERE chain_status = 'confirmed'").fetchone()[0]
            subscribers = connection.execute("SELECT COUNT(*) FROM qj_subscriptions WHERE status = 'active'").fetchone()[0]
        scores = [agent["latest_report"]["score"] for agent in agents if agent["latest_report"]]
        return {
            "agents": len(agents), "reports": reports, "live_reports": live_reports,
            "chain_confirmed_reports": confirmed, "active_subscriptions": subscribers,
            "median_score": round(sorted(scores)[len(scores) // 2], 1) if scores else 0,
            "attestation": {
                "algorithm": "Ed25519", "key_id": self.attestor.key_id,
                "public_key": self.attestor.public_key,
            },
            "privacy_model": "hide_strategy_and_decisions_publish_verified_performance",
        }

    def chain_status(self) -> dict[str, Any]:
        status = self.supervisor.status()
        return {
            "connected": status.connected,
            "compatible": status.connected and status.chain_id == 1051,
            "rpc_url": status.rpc_url,
            "chain_id": status.chain_id,
            "block_number": status.block_number,
            "error": status.error,
            "expected_chain_id": 1051,
            "read_only_source_policy": True,
            "submission_policy": "external_wallet_signed_raw_transaction_only",
        }

    def _seed_demo(self) -> None:
        with self._connect() as connection:
            if connection.execute("SELECT COUNT(*) FROM qj_agents").fetchone()[0]:
                return
        seeds = [
            ("Aster Multi-Factor", "Aster Lab", "ai_agent", "multi_factor", ["equity", "etf"], "多因子横截面选股与动态风险预算，按日级更新组合。", "medium", 299, 0.42, "live"),
            ("Orion Crypto Timing", "Northstar", "ai_agent", "timing", ["crypto"], "面向主流加密资产的趋势与波动率择时 Agent，严格限制净暴露。", "high", 219, 0.78, "live"),
            ("Harbor Allocation", "Delta Harbor", "traditional", "allocation", ["etf", "bond", "commodity"], "跨资产宏观配置和风险平价，以组合回撤约束优先。", "low", 129, 0.25, "backtest"),
            ("Pulse Reversal", "Lambda Works", "traditional", "timing", ["equity", "crypto"], "短中周期超卖修复与流动性过滤，对单笔损失设置硬限制。", "high", 159, 0.56, "backtest"),
            ("Atlas Quality Select", "Q-Foundry", "ai_agent", "stock_selection", ["equity"], "盈利质量、估值与分析师预期变化组合选股，双周调仓。", "medium", 199, 0.34, "live"),
            ("Neutral Basis", "Quiet Sigma", "traditional", "arbitrage", ["crypto"], "现货与衍生品基差组合，不公开交易所路由与执行参数。", "medium", 399, 0.18, "live"),
        ]
        end = utc_now()
        start = end - timedelta(days=540)
        for index, (name, developer, kind, category, classes, description, risk, price, annual_return, report_type) in enumerate(seeds):
            agent_id = f"qja_demo_{index + 1:02d}"
            token = secrets.token_urlsafe(32)
            now = (end - timedelta(minutes=index)).isoformat()
            commitment = sha256_hex(f"quantjudge-demo-strategy-{index}")
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO qj_agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)""",
                    (agent_id, name, developer, kind, category, canonical_json(classes), description, risk, price, "CNY", commitment, self._token_hash(token), now, now),
                )
            points = []
            value = 100.0
            benchmark = 100.0
            for day in range(0, 541, 6):
                cycle = math.sin((day + index * 17) / 23) * 0.008
                daily = (1 + annual_return) ** (6 / 365) - 1 + cycle
                value *= max(0.94, 1 + daily)
                benchmark *= 1 + 0.0009 * 6 + math.sin(day / 41) * 0.002
                points.append({"time": int((start + timedelta(days=day)).timestamp()), "equity": value, "benchmark": benchmark})
            metrics = calculate_public_metrics(points, report_type)
            curve_json = canonical_json(public_curve(points))
            decisions = [sha256_hex(f"hidden-decision:{index}:{n}") for n in range(52 + index * 7)]
            report_id = f"qjr_demo_{index + 1:02d}"
            created_at = now
            payload = {
                "schema": "atlas.quantjudge.receipt.v1", "report_id": report_id, "agent_id": agent_id,
                "strategy_commitment": commitment, "report_type": report_type,
                "period_start": start.isoformat(), "period_end": end.isoformat(), "metrics": metrics,
                "public_curve_hash": sha256_hex(curve_json),
                "decision_count": len(decisions), "decision_merkle_root": merkle_root(decisions),
                "market_data_hash": sha256_hex(f"demo-market:{index}"), "previous_receipt_hash": None,
                "external_proof": None, "created_at": created_at,
            }
            payload_json = canonical_json(payload)
            receipt_hash = sha256_hex(payload_json)
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO qj_reports (
                        id, agent_id, report_type, period_start, period_end, metrics_json, curve_json,
                        decision_count, decision_merkle_root, market_data_hash, previous_receipt_hash,
                        receipt_payload_json, receipt_hash, attestation_key_id, attestation_signature,
                        external_proof_json, chain_tx_hash, chain_status, chain_block_number, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, 'not_anchored', NULL, ?)""",
                    (
                        report_id, agent_id, report_type, start.isoformat(), end.isoformat(),
                        canonical_json(metrics), curve_json, len(decisions),
                        merkle_root(decisions), payload["market_data_hash"], payload_json, receipt_hash,
                        self.attestor.key_id, self.attestor.sign(receipt_hash), created_at,
                    ),
                )
