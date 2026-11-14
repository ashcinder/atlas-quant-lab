"""Run the operator-installed industry strategies against their frozen market data."""

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.lab_strategies import require_lab_owner
from app.compute_objects import ComputeObjects
from app.config import DB_PATH

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT / ".artifacts/user-strategies/atlas-sector-joint-strategies-20261113"
SNAPSHOT = Path(".artifacts/limit-up-study-20261112/expanded")
INDUSTRIES = {"semiconductor": "半导体", "defense": "军工", "space": "商业航天", "robotics": "机器人"}
Sector = Literal["semiconductor", "defense", "space", "robotics"]
TIMEOUT_SECONDS = 90
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
STARTING_CASH = 1_000_000
SLOTS = BoundedSemaphore(1)
LOGGER = logging.getLogger(__name__)
UNAVAILABLE = "多股回测环境尚未安装。请按项目说明配置四行业策略包和 Python 依赖。"


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    industry: Sector


class ReplayStats(BaseModel):
    net_return: FiniteFloat = Field(alias="return", serialization_alias="net_return")
    equity: FiniteFloat
    max_drawdown: FiniteFloat = Field(ge=0, le=1)
    buys: int = Field(ge=0)
    sells: int = Field(ge=0)
    open: int = Field(ge=0)
    mean_trade_return: FiniteFloat | None
    median_trade_return: FiniteFloat | None
    weighted_trade_return: FiniteFloat | None
    pnl_original: FiniteFloat
    pnl_new: FiniteFloat


class EquityPoint(BaseModel):
    date: date
    equity: FiniteFloat
    cash: FiniteFloat
    positions: int = Field(ge=0)
    buys: int = Field(ge=0)
    sells: int = Field(ge=0)


class TradePolicy(BaseModel):
    mode: str
    alert_fraction: FiniteFloat
    buy_margin: FiniteFloat
    sell_margin: FiniteFloat
    max_days: int
    weight: FiniteFloat
    buy_model: str
    sell_window: int
    buy_quantile: FiniteFloat
    sell_quantile: FiniteFloat


class ReplayTrade(BaseModel):
    date: date
    time: str = Field(pattern=r"^[0-9]{2}:[0-9]{2}$")
    symbol: str = Field(pattern=r"^[0-9]{6}$")
    industry: str
    trigger: str = Field(pattern=r"^[0-9]{6}$")
    signal_date: date
    touch_time: str = Field(pattern=r"^[0-9]{2}:[0-9]{2}$")
    side: Literal["buy", "sell", "adjust"]
    shares: FiniteFloat = Field(gt=0)
    raw_open: FiniteFloat | None
    price: FiniteFloat | None
    fee: FiniteFloat
    commission: FiniteFloat
    tax: FiniteFloat
    slippage: FiniteFloat
    cash_after: FiniteFloat
    entry_date: date
    entry_time: str = Field(pattern=r"^[0-9]{2}:[0-9]{2}$")
    decision_bar_close: str | None
    policy: TradePolicy


class ReplayResult(BaseModel):
    id: str | None = None
    created_at: datetime | None = None
    industry: Sector
    start: date
    end: date
    starting_cash: int
    pool_limit: int
    snapshot_symbols: list[str] = Field(max_length=300)
    traded_symbols: list[str] = Field(max_length=300)
    config_sha256: str
    input_sha256: dict[str, str]
    engine_version: Literal["industry-joint-replay/v1"] = "industry-joint-replay/v1"
    selection_scope: Literal["same_historical_period"] = "same_historical_period"
    proof_status: Literal["unverified"] = "unverified"
    metrics: ReplayStats
    equity: list[EquityPoint] = Field(min_length=1, max_length=1000)
    trades: list[ReplayTrade] = Field(max_length=10_000)


def runtime_root() -> Path:
    return Path(os.environ.get("ATLAS_SECTOR_REPLAY_ROOT") or DEFAULT_ROOT).expanduser().resolve()


def missing_runtime(root: Path, sector: str) -> bool:
    return not (
        (root / ".venv-sector/bin/python").is_file()
        and os.access(root / ".venv-sector/bin/python", os.X_OK)
        and (root / "tools/limit_up_study/train_joint.py").is_file()
        and (root / "tools/limit_up_study/requirements-sector-strategies.txt").is_file()
        and (root / SNAPSHOT / "membership-verified.json").is_file()
        and (root / SNAPSHOT / "market/calendar.json").is_file()
        and (root / SNAPSHOT / "joint-search-fine" / sector / "summary.json").is_file()
    )


def read_output(path: Path, *, lines: bool = False):
    with path.open("rb") as stream:
        raw = stream.read(MAX_OUTPUT_BYTES + 1)
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("oversized replay output")
    if lines:
        return [json.loads(line) for line in raw.splitlines()]
    return json.loads(raw)


def execute_replay(root: Path, sector: Sector) -> ReplayResult:
    snapshot = root / SNAPSHOT
    config = snapshot / "joint-search-fine" / sector / "summary.json"
    with TemporaryDirectory(prefix="atlas-sector-replay-") as temporary:
        output = Path(temporary)
        config_bytes = config.read_bytes()
        if len(config_bytes) > MAX_OUTPUT_BYTES:
            raise ValueError("oversized replay config")
        frozen_config = output / "config" / "summary.json"
        frozen_config.parent.mkdir()
        frozen_config.write_bytes(config_bytes)
        command = [
            str(root / ".venv-sector/bin/python"), "-I", "-B",
            str(Path(__file__).with_name("sector_replay_worker.py")),
            str(root / "tools/limit_up_study"), INDUSTRIES[sector], str(frozen_config),
            str(snapshot / "market"), str(snapshot / "membership-verified.json"), temporary,
        ]
        completed = subprocess.run(
            command, cwd=temporary, timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                 "VECLIB_MAXIMUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        )
        if completed.returncode == 2:
            raise HTTPException(503, UNAVAILABLE)
        if completed.returncode:
            LOGGER.warning("Industry replay failed for %s with exit code %s", sector, completed.returncode)
            raise HTTPException(503, "行业回测未能复现。请检查冻结行情、策略配置及依赖版本。")
        saved = json.loads(config_bytes)
        hashes = saved["input_sha256"]
        trades = read_output(output / "trades.jsonl", lines=True)
        curve = read_output(output / "equity.jsonl", lines=True)
        result = ReplayResult(
            industry=sector, start=saved["from"], end=saved["to"], starting_cash=STARTING_CASH,
            pool_limit=saved["winner"]["training"]["pool_size"],
            snapshot_symbols=sorted(Path(name).stem for name in hashes if re.fullmatch(r"[0-9]{6}\.json", name)),
            traded_symbols=sorted({row["symbol"] for row in trades if row["side"] == "buy"}),
            config_sha256=sha256(config_bytes).hexdigest(), input_sha256=hashes,
            metrics=read_output(output / "summary.json"), equity=curve, trades=trades,
        )
        if (
            result.equity[0].date != result.start or result.equity[-1].date != result.end
            or result.equity[-1].equity != result.metrics.equity
            or result.metrics.buys != sum(row.side == "buy" for row in result.trades)
            or result.metrics.sells != sum(row.side == "sell" for row in result.trades)
        ):
            raise ValueError("inconsistent replay output")
        return result


router = APIRouter(prefix="/api/v1/lab-sector-backtests")


def open_history():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS lab_sector_history (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                    summary TEXT NOT NULL, digest TEXT NOT NULL
                 )""")
    return db


@router.get("/history")
def history(request: Request):
    owner = require_lab_owner(request)
    with open_history() as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT summary FROM lab_sector_history WHERE owner=? ORDER BY created_at DESC LIMIT 50", (owner,))]


@router.get("/history/{identifier}")
def historical_result(identifier: str, request: Request):
    owner = require_lab_owner(request)
    with open_history() as db:
        row = db.execute("SELECT digest FROM lab_sector_history WHERE owner=? AND id=?", (owner, identifier)).fetchone()
    if row is None:
        raise HTTPException(404, "行业回放不存在")
    return ComputeObjects().read("private", row[0])


@router.get("")
def catalog(request: Request):
    require_lab_owner(request)
    root = runtime_root()
    return [
        {"id": sector, "name": name, "available": not missing_runtime(root, sector)}
        for sector, name in INDUSTRIES.items()
    ]


@router.post("", response_model=ReplayResult)
def replay(body: ReplayRequest, request: Request):
    owner = require_lab_owner(request)
    root = runtime_root()
    if missing_runtime(root, body.industry):
        raise HTTPException(503, UNAVAILABLE)
    if not SLOTS.acquire(blocking=False):
        raise HTTPException(429, "已有行业回测正在运行，请稍后重试。", headers={"Retry-After": "3"})
    try:
        result = execute_replay(root, body.industry)
        result.id, result.created_at = uuid4().hex, datetime.now(UTC)
        payload = result.model_dump(mode="json", by_alias=True)
        digest = ComputeObjects().put("private", payload)
        summary = {key: payload[key] for key in ("id", "created_at", "industry", "start", "end", "metrics")}
        with open_history() as db:
            db.execute("INSERT INTO lab_sector_history VALUES (?,?,?,?,?)",
                       (result.id, owner, result.created_at.isoformat(), json.dumps(summary), digest))
        return result
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "行业回测超过 90 秒。请稍后重试。") from None
    except (OSError, ValueError, TypeError, KeyError):
        LOGGER.warning("Invalid industry replay output for %s", body.industry, exc_info=True)
        raise HTTPException(503, "行业回测结果不完整。请检查策略包和行情快照。") from None
    finally:
        SLOTS.release()
