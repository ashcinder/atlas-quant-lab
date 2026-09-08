from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from app.config import DATA_DIR, DB_PATH, ROOT_DIR
from app.quantjudge import canonical_json, sha256_hex
from app.zkp_models import ZkPublicStatement

MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_DATASET_BARS = 20_000
VERIFY_TIMEOUT_SECONDS = 45
PROFILES_PATH = ROOT_DIR.parent / "strategy" / "zkvm" / "profiles.json"
DEFAULT_VERIFIER = (
    ROOT_DIR.parent / "strategy" / "zkvm" / "target" / "release" / "atlas-zkvm"
)


class ZkProofError(ValueError):
    pass


class ZkVerifierUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedReceipt:
    image_id: str
    journal: dict[str, Any]
    receipt_kind: str
    verifier_version: str


class ReceiptVerifier(Protocol):
    def verify(self, receipt_path: Path, expected_image_id: str) -> VerifiedReceipt: ...


class Risc0ReceiptVerifier:
    """Fail-closed adapter around the pinned, local RISC Zero verifier binary."""

    def __init__(self, executable: Path = DEFAULT_VERIFIER):
        self.executable = executable

    def verify(self, receipt_path: Path, expected_image_id: str) -> VerifiedReceipt:
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise ZkVerifierUnavailable(
                "RISC Zero verifier 尚未构建；请运行 strategy/zkvm/scripts/build.sh"
            )
        try:
            completed = subprocess.run(
                [
                    str(self.executable),
                    "verify",
                    "--receipt",
                    str(receipt_path),
                    "--expected-image-id",
                    expected_image_id,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=VERIFY_TIMEOUT_SECONDS,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired as exc:
            raise ZkProofError("证明验证超时") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-800:] or "receipt verification failed"
            raise ZkProofError(f"RISC Zero 证明无效: {detail}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ZkProofError("Verifier 未返回有效 JSON") from exc
        if result.get("valid") is not True:
            raise ZkProofError("Verifier 未确认该证明有效")
        image_id = str(result.get("image_id", ""))
        if not hmac.compare_digest(image_id, expected_image_id):
            raise ZkProofError("证明程序 ID 与登记版本不匹配")
        journal = result.get("journal")
        if not isinstance(journal, dict):
            raise ZkProofError("证明 journal 格式无效")
        return VerifiedReceipt(
            image_id=image_id,
            journal=journal,
            receipt_kind=str(result.get("receipt_kind", "unknown")),
            verifier_version=str(result.get("verifier_version", "unknown")),
        )


def load_profiles(path: Path = PROFILES_PATH) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ZkVerifierUnavailable(f"ZKP profile registry 无法读取: {exc}") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict):
        raise ZkVerifierUnavailable("ZKP profile registry 格式无效")
    return {
        str(profile_id): {str(key): str(value) for key, value in record.items()}
        for profile_id, record in profiles.items()
        if isinstance(record, dict)
    }


def _put_text(digest: Any, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(struct.pack(">I", len(encoded)))
    digest.update(encoded)


def _to_micros(value: Any) -> int:
    scaled = (Decimal(str(value)) * 1_000_000).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    )
    result = int(scaled)
    if not -(2**63) <= result < 2**63:
        raise ZkProofError("市场数据超出 i64 定点数范围")
    return result


def make_market_dataset(
    *,
    source: str,
    symbol: str,
    interval: str,
    adjustment: str,
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    if not 3 <= len(bars) <= MAX_DATASET_BARS:
        raise ZkProofError(f"ZKP 市场数据必须包含 3–{MAX_DATASET_BARS} 根 K 线")
    converted: list[dict[str, int]] = []
    previous_time = 0
    for bar in bars:
        item = {
            "time": int(bar["time"]),
            "open_micros": _to_micros(bar["open"]),
            "high_micros": _to_micros(bar["high"]),
            "low_micros": _to_micros(bar["low"]),
            "close_micros": _to_micros(bar["close"]),
            "volume_micros": _to_micros(bar.get("volume", 0)),
        }
        if item["time"] <= previous_time:
            raise ZkProofError("市场 K 线时间必须严格递增")
        if item["low_micros"] <= 0 or item["volume_micros"] < 0:
            raise ZkProofError("市场 K 线包含无效价格或成交量")
        if item["high_micros"] < max(item["open_micros"], item["close_micros"]):
            raise ZkProofError("市场 K 线最高价无效")
        if item["low_micros"] > min(item["open_micros"], item["close_micros"]):
            raise ZkProofError("市场 K 线最低价无效")
        converted.append(item)
        previous_time = item["time"]
    return {
        "source": source,
        "symbol": symbol,
        "interval": interval,
        "adjustment": adjustment,
        "bars": converted,
    }


def market_commitment(dataset: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(b"ATLASMARKET1")
    for key in ("source", "symbol", "interval", "adjustment"):
        _put_text(digest, str(dataset[key]))
    bars = dataset["bars"]
    digest.update(struct.pack(">I", len(bars)))
    for bar in bars:
        for key in (
            "time",
            "open_micros",
            "high_micros",
            "low_micros",
            "close_micros",
            "volume_micros",
        ):
            digest.update(struct.pack(">q", int(bar[key])))
    return digest.hexdigest()


class ZkProofStore:
    def __init__(
        self,
        path: Path = DB_PATH,
        *,
        receipt_root: Path = DATA_DIR / "zk_receipts",
        market_root: Path = DATA_DIR / "zk_market",
        verifier: ReceiptVerifier | None = None,
        profiles_path: Path = PROFILES_PATH,
    ):
        self.path = path
        self.receipt_root = receipt_root
        self.market_root = market_root
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.market_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.receipt_root, 0o700)
        os.chmod(self.market_root, 0o700)
        self.verifier = verifier or Risc0ReceiptVerifier()
        self.profiles_path = profiles_path
        self._initialize()

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
                CREATE TABLE IF NOT EXISTS qj_zk_proofs (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES qj_agents(id) ON DELETE CASCADE,
                    proof_profile TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    public_statement_json TEXT NOT NULL,
                    public_inputs_hash TEXT NOT NULL,
                    proof_hash TEXT NOT NULL UNIQUE,
                    receipt_path TEXT NOT NULL,
                    receipt_size INTEGER NOT NULL,
                    receipt_kind TEXT NOT NULL,
                    verifier_version TEXT NOT NULL,
                    nullifier TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('verified', 'revoked')),
                    report_id TEXT UNIQUE,
                    verified_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_qj_zk_proofs_agent_created
                    ON qj_zk_proofs(agent_id, created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_qj_zk_proofs_report
                    ON qj_zk_proofs(report_id) WHERE report_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS qj_market_datasets (
                    market_data_hash TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    adjustment TEXT NOT NULL,
                    period_start INTEGER NOT NULL,
                    period_end INTEGER NOT NULL,
                    bar_count INTEGER NOT NULL,
                    dataset_path TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('trusted', 'revoked')),
                    trust_model TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(qj_zk_proofs)")}
            if "report_id" not in columns:
                connection.execute("ALTER TABLE qj_zk_proofs ADD COLUMN report_id TEXT")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_qj_zk_proofs_report "
                    "ON qj_zk_proofs(report_id) WHERE report_id IS NOT NULL"
                )

    def profiles(self) -> list[dict[str, Any]]:
        profiles = load_profiles(self.profiles_path)
        verifier_ready = isinstance(self.verifier, Risc0ReceiptVerifier) and (
            self.verifier.executable.is_file()
            and os.access(self.verifier.executable, os.X_OK)
        )
        return [
            {
                "id": profile_id,
                **record,
                "verifier_ready": verifier_ready,
                "privacy_scope": [
                    "策略参数与 salt 不进入 journal",
                    "逐根 K 线、交易决策与完整净值序列不进入平台数据库",
                    "公开市场数据哈希、策略承诺、聚合指标、抽样曲线和结果根",
                ],
                "unsupported": ["任意 Python", "外部大模型推理", "实盘成交真实性"],
            }
            for profile_id, record in sorted(profiles.items())
        ]

    def register_market_dataset(
        self,
        dataset: dict[str, Any],
        *,
        fetched_at: datetime,
        trust_model: str = "platform_fetched_public_market_data",
    ) -> dict[str, Any]:
        source = str(dataset["source"])
        if source == "demo" or "stale" in source:
            raise ZkProofError("演示或过期缓存数据不能登记为 ZKP 可信市场数据")
        market_hash = market_commitment(dataset)
        payload = {
            "schema": "atlas.quantjudge.market-dataset.v1",
            "market_data_hash": market_hash,
            "dataset": dataset,
        }
        payload_json = canonical_json(payload)
        destination = self.market_root / f"{market_hash}.json"
        if not destination.exists():
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.market_root,
                prefix=".market-",
                suffix=".json",
                delete=False,
            ) as handle:
                handle.write(payload_json)
                handle.write("\n")
                temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, destination)
        bars = dataset["bars"]
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO qj_market_datasets (
                    market_data_hash, source, symbol, interval, adjustment, period_start,
                    period_end, bar_count, dataset_path, status, trust_model, fetched_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'trusted', ?, ?, ?)
                ON CONFLICT(market_data_hash) DO NOTHING
                """,
                (
                    market_hash,
                    source,
                    dataset["symbol"],
                    dataset["interval"],
                    dataset["adjustment"],
                    bars[0]["time"],
                    bars[-1]["time"],
                    len(bars),
                    str(destination),
                    trust_model,
                    fetched_at.astimezone(UTC).isoformat(),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM qj_market_datasets WHERE market_data_hash = ?", (market_hash,)
            ).fetchone()
        return dict(row)

    def market_dataset(self, market_hash: str) -> tuple[dict[str, Any], Path]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM qj_market_datasets
                   WHERE market_data_hash = ? AND status = 'trusted'""",
                (market_hash,),
            ).fetchone()
        if row is None:
            raise KeyError(market_hash)
        path = Path(row["dataset_path"])
        if path.parent.resolve() != self.market_root.resolve() or not path.is_file():
            raise ZkProofError("市场数据文件路径越界或文件丢失")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if market_commitment(payload["dataset"]) != market_hash:
            raise ZkProofError("市场数据内容哈希不匹配")
        return dict(row), path

    def _assert_token(self, agent_id: str, token: str | None) -> sqlite3.Row:
        if not token:
            raise PermissionError("缺少开发者凭证")
        with self._connect() as connection:
            row = connection.execute(
                """SELECT developer_token_hash, is_demo, strategy_commitment
                   FROM qj_agents WHERE id = ?""",
                (agent_id,),
            ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        if row["is_demo"]:
            raise PermissionError("演示 Agent 为只读样本")
        if not secrets.compare_digest(row["developer_token_hash"], sha256_hex(token)):
            raise PermissionError("开发者凭证无效")
        return row

    def _profile(self, profile_id: str) -> dict[str, str]:
        profile = load_profiles(self.profiles_path).get(profile_id)
        if not profile or profile.get("status") != "active":
            raise ZkProofError("证明 profile 未登记或已停用")
        image_id = profile.get("image_id", "")
        if len(image_id) != 64 or any(ch not in "0123456789abcdef" for ch in image_id):
            raise ZkVerifierUnavailable("登记的 zkVM image ID 无效")
        return profile

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        statement = json.loads(row["public_statement_json"])
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "proof_profile": row["proof_profile"],
            "image_id": row["image_id"],
            "public_statement": statement,
            "public_inputs_hash": row["public_inputs_hash"],
            "proof_hash": row["proof_hash"],
            "receipt_size": row["receipt_size"],
            "receipt_kind": row["receipt_kind"],
            "verifier_version": row["verifier_version"],
            "nullifier": row["nullifier"],
            "status": row["status"],
            "verified_at": row["verified_at"],
            "created_at": row["created_at"],
            "private_witness_stored": False,
        }

    def register_receipt(
        self,
        agent_id: str,
        proof_profile: str,
        receipt: bytes,
        developer_token: str | None,
    ) -> dict[str, Any]:
        agent = self._assert_token(agent_id, developer_token)
        if not receipt or len(receipt) > MAX_RECEIPT_BYTES:
            raise ZkProofError("证明回执必须介于 1B–16MB")
        profile = self._profile(proof_profile)
        proof_hash = hashlib.sha256(receipt).hexdigest()
        with tempfile.NamedTemporaryFile(
            dir=self.receipt_root, prefix=".verify-", suffix=".bin", delete=False
        ) as handle:
            handle.write(receipt)
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        try:
            verified = self.verifier.verify(temp_path, profile["image_id"])
            try:
                statement = ZkPublicStatement.model_validate(verified.journal)
            except ValidationError as exc:
                raise ZkProofError(f"证明公开声明不符合协议: {exc}") from exc
            if statement.proof_profile != proof_profile:
                raise ZkProofError("journal 中的 proof profile 与上传参数不一致")
            if statement.agent_id != agent_id:
                raise ZkProofError("证明未绑定当前 Agent")
            if not hmac.compare_digest(statement.strategy_commitment, agent["strategy_commitment"]):
                raise ZkProofError("证明策略承诺与 Agent 登记承诺不一致")
            try:
                market_record, _ = self.market_dataset(statement.market_data_hash)
            except KeyError as exc:
                raise ZkProofError("证明引用的市场数据根未在平台可信数据集登记") from exc
            if (
                market_record["period_start"] != statement.period_start
                or market_record["period_end"] != statement.period_end
                or market_record["bar_count"] != statement.metrics.observation_count
            ):
                raise ZkProofError("证明周期或观测数与登记市场数据集不一致")
            statement_json = canonical_json(statement.model_dump(mode="json", by_alias=True))
            public_inputs_hash = sha256_hex(statement_json)
            proof_id = f"qzp_{uuid4().hex[:18]}"
            now = datetime.now(UTC).isoformat()
            destination = self.receipt_root / f"{proof_hash}.r0"
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    """SELECT receipt_hash FROM qj_reports
                       WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1""",
                    (agent_id,),
                ).fetchone()
                expected_previous = previous["receipt_hash"] if previous else None
                if statement.previous_receipt_hash != expected_previous:
                    raise ZkProofError("证明未绑定 Agent 当前最新回执，可能发生重放或并发冲突")
                existing = connection.execute(
                    "SELECT id FROM qj_zk_proofs WHERE proof_hash = ? OR nullifier = ?",
                    (proof_hash, statement.nullifier),
                ).fetchone()
                if existing:
                    raise ZkProofError("该证明或 nullifier 已登记，禁止重放")
                if destination.exists():
                    raise ZkProofError("证明内容已存在但索引缺失，请人工审计")
                os.replace(temp_path, destination)
                connection.execute(
                    """
                    INSERT INTO qj_zk_proofs (
                        id, agent_id, proof_profile, image_id, public_statement_json,
                        public_inputs_hash, proof_hash, receipt_path, receipt_size, receipt_kind,
                        verifier_version, nullifier, status, verified_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?)
                    """,
                    (
                        proof_id,
                        agent_id,
                        proof_profile,
                        verified.image_id,
                        statement_json,
                        public_inputs_hash,
                        proof_hash,
                        str(destination),
                        len(receipt),
                        verified.receipt_kind,
                        verified.verifier_version,
                        statement.nullifier,
                        now,
                        now,
                    ),
                )
            return self.get(proof_id)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def get(self, proof_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qj_zk_proofs WHERE id = ?", (proof_id,)
            ).fetchone()
        if row is None:
            raise KeyError(proof_id)
        return self._public(row)

    def get_verified_for_agent(self, proof_id: str, agent_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM qj_zk_proofs
                   WHERE id = ? AND agent_id = ? AND status = 'verified'""",
                (proof_id, agent_id),
            ).fetchone()
        if row is None:
            raise ZkProofError("证明不存在、未通过验证或不属于当前 Agent")
        return row

    def reverify(self, proof_id: str) -> VerifiedReceipt:
        """Cryptographically re-verify a persisted receipt and its exact public journal."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qj_zk_proofs WHERE id = ? AND status = 'verified'",
                (proof_id,),
            ).fetchone()
        if row is None:
            raise KeyError(proof_id)
        path = self.receipt_path(proof_id)
        verified = self.verifier.verify(path, row["image_id"])
        try:
            statement = ZkPublicStatement.model_validate(verified.journal)
        except ValidationError as exc:
            raise ZkProofError(f"持久化证明 journal 不符合协议: {exc}") from exc
        statement_json = canonical_json(statement.model_dump(mode="json", by_alias=True))
        if not hmac.compare_digest(statement_json, row["public_statement_json"]):
            raise ZkProofError("receipt journal 与登记公开输入不一致")
        if not hmac.compare_digest(sha256_hex(statement_json), row["public_inputs_hash"]):
            raise ZkProofError("receipt 公开输入哈希不一致")
        return verified

    def receipt_path(self, proof_id: str) -> Path:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT receipt_path, proof_hash FROM qj_zk_proofs
                   WHERE id = ? AND status = 'verified'""",
                (proof_id,),
            ).fetchone()
        if row is None:
            raise KeyError(proof_id)
        path = Path(row["receipt_path"])
        if path.parent.resolve() != self.receipt_root.resolve() or not path.is_file():
            raise ZkProofError("证明文件路径越界或文件丢失")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, row["proof_hash"]):
            raise ZkProofError("证明文件内容哈希不匹配")
        return path
