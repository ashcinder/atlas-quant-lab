"""Account-private code drafts and their backtest history."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import DB_PATH
from app.models import Adjustment, Interval, RunSummary
from app.strategy_code_api import MAX_CODE_CHARS, StrategyLanguage

LAB_OWNER_HEADER = "X-Atlas-Lab-Owner"
LabKind = Literal["single_bounded", "multi_python"]
MAX_LAB_PACKAGE_B64 = 3_000_000


def require_lab_owner(request: Request) -> str:
    owner = request.state.user.id
    if request.headers.get(LAB_OWNER_HEADER) != owner:
        raise HTTPException(403, "当前登录账号已改变。请刷新工作台后重试。")
    return owner


class LabBacktestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    symbol: str | None = Field(default=None, min_length=1, max_length=80)
    asset_class: str | None = Field(default=None, min_length=1, max_length=40)
    data_source: Literal["auto", "yahoo", "binance", "demo"] = "auto"
    interval: Interval = "1d"
    start: datetime | None = None
    end: datetime | None = None
    initial_capital: float = Field(default=100_000, gt=0)
    adjustment: Adjustment = "auto"
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    spread_rate: float = Field(default=0.0005, ge=0, le=0.1)
    max_position: float = Field(default=0.95, gt=0, le=1)
    max_participation_rate: float = Field(default=0.01, gt=0, le=1)

    @field_validator("start", "end")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def validate_window(self):
        if self.start and self.end and self.start >= self.end:
            raise ValueError("结束时间必须晚于开始时间")
        if bool(self.symbol) != bool(self.asset_class):
            raise ValueError("标的代码和资产类别需要同时设置")
        return self


class LabMultiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    engine_id: Literal["atlas_portfolio", "rqalpha"] = "atlas_portfolio"
    symbols: list[str] = Field(default_factory=list, max_length=150)
    interval: Literal["1d", "15m"] = "1d"
    start: datetime | None = None
    end: datetime | None = None
    initial_capital: float = Field(default=1_000_000, gt=0, le=1e12)
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    max_position: float = Field(default=0.95, gt=0, le=1)
    max_participation_rate: float = Field(default=0.01, gt=0, le=1)
    parameters: dict[str, int | float | bool | str] = Field(default_factory=dict, max_length=80)
    universe: Literal["semiconductor", "defense", "space", "robotics"] | None = None
    benchmark: Literal["000300.SS", "000905.SS", "000001.SS"] | None = None

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols):
        import re

        normalized = [symbol.strip().upper() for symbol in symbols]
        if any(not re.fullmatch(r"(?:[036][0-9]{5}\.(?:SS|SZ)|[489][0-9]{5}\.BJ)", symbol)
               for symbol in normalized):
            raise ValueError("请输入带交易所后缀的 A 股代码，例如 600519.SS")
        if len(set(normalized)) != len(normalized):
            raise ValueError("股票池不能包含重复标的")
        return normalized

    @field_validator("start", "end")
    @classmethod
    def normalize_time(cls, value):
        return LabBacktestSettings.normalize_time(value)

    @model_validator(mode="after")
    def validate_window(self):
        if self.start and self.end and self.start >= self.end:
            raise ValueError("结束时间必须晚于开始时间")
        if self.engine_id != "rqalpha" and self.benchmark is not None:
            raise ValueError("基准指数配置仅用于 RQAlpha 历史回测")
        if self.engine_id == "rqalpha" and (
            self.interval != "1d" or self.universe or any(s.endswith(".BJ") for s in self.symbols)
        ):
            raise ValueError("RQAlpha 首期仅支持静态沪深 A 股日线")
        return self


class LabDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    kind: LabKind = "single_bounded"
    language: StrategyLanguage
    source: str = Field(max_length=MAX_CODE_CHARS)
    settings: LabBacktestSettings | LabMultiSettings
    package_b64: str | None = Field(default=None, max_length=MAX_LAB_PACKAGE_B64)

    @model_validator(mode="after")
    def validate_kind(self):
        if self.kind == "multi_python":
            if self.language != "python" or not isinstance(self.settings, LabMultiSettings):
                raise ValueError("多股策略仅支持 Python 和多股回测设置")
            if len(self.source.encode("utf-8")) > MAX_CODE_CHARS:
                raise ValueError("多股源码不能超过 60,000 UTF-8 字节")
            if self.settings.engine_id == "rqalpha" and self.package_b64 is not None:
                raise ValueError("RQAlpha 首期仅支持原生 .py 源码，不支持 Atlas 策略包")
        elif not isinstance(self.settings, LabBacktestSettings) or self.package_b64 is not None:
            raise ValueError("单标的策略不能使用多股设置或策略包")
        return self

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请输入策略名称")
        return value.strip()

    @field_validator("source")
    @classmethod
    def text_source(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("源码必须为文本")
        return value


class LabDraftUpdate(LabDraft):
    expected_revision: int = Field(ge=1)


class LabDraftCreate(LabDraft):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")


class LabStrategySummary(BaseModel):
    id: str
    name: str
    language: StrategyLanguage
    kind: LabKind = "single_bounded"
    revision: int
    updated_at: datetime


class LabStrategy(LabStrategySummary):
    source: str
    settings: LabBacktestSettings | LabMultiSettings
    package_b64: str | None = None


class LabRunSummary(RunSummary):
    source_sha256: str
    settings: LabBacktestSettings


class LabStrategyStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS lab_strategies (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    language TEXT NOT NULL,
                    source TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lab_strategies_owner_time
                    ON lab_strategies(owner_id, updated_at DESC, id);
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(lab_strategies)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE lab_strategies ADD COLUMN kind TEXT NOT NULL DEFAULT 'single_bounded'")
            if "package_b64" not in columns:
                db.execute("ALTER TABLE lab_strategies ADD COLUMN package_b64 TEXT")

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def list(self, owner: str):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT id, name, language, kind, revision, updated_at FROM lab_strategies
                   WHERE owner_id=? ORDER BY updated_at DESC, id""", (owner,)
            )]

    def require_owned(self, owner: str, strategy_id: str) -> None:
        with self._connect() as db:
            if db.execute("SELECT 1 FROM lab_strategies WHERE owner_id=? AND id=?", (owner, strategy_id)).fetchone() is None:
                raise HTTPException(404, "代码策略不存在")

    def get(self, owner: str, strategy_id: str):
        with self._connect() as db:
            row = db.execute(
                """SELECT id, name, language, source, settings, revision, updated_at, kind, package_b64
                   FROM lab_strategies WHERE owner_id=? AND id=?""",
                (owner, strategy_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "代码策略不存在")
        return {**dict(row), "settings": json.loads(row["settings"])}

    def create(self, owner: str, draft: LabDraftCreate):
        with self._connect() as db:
            db.execute(
                """INSERT INTO lab_strategies (id, owner_id, name, language, source, settings, revision,
                                                updated_at, kind, package_b64)
                   VALUES (?,?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO NOTHING""",
                (draft.id, owner, draft.name, draft.language, draft.source,
                 draft.settings.model_dump_json(), datetime.now(UTC).isoformat(), draft.kind, draft.package_b64),
            )
        return self.get(owner, draft.id)

    def update(self, owner: str, strategy_id: str, draft: LabDraftUpdate):
        updated_at = datetime.now(UTC)
        with self._connect() as db:
            changed = db.execute(
                """UPDATE lab_strategies SET name=?, language=?, source=?, settings=?, package_b64=?,
                                               revision=revision+1, updated_at=?
                   WHERE owner_id=? AND id=? AND revision=? AND kind=?""",
                (draft.name, draft.language, draft.source, draft.settings.model_dump_json(),
                 draft.package_b64, updated_at.isoformat(), owner, strategy_id, draft.expected_revision, draft.kind),
            )
            if not changed.rowcount:
                if db.execute("SELECT 1 FROM lab_strategies WHERE owner_id=? AND id=?", (owner, strategy_id)).fetchone() is None:
                    raise HTTPException(404, "代码策略不存在")
                raise HTTPException(409, "策略已在其他窗口更新。可重新加载已保存版本，或先下载当前源码。")
        return {**draft.model_dump(exclude={"expected_revision"}), "id": strategy_id,
                "revision": draft.expected_revision + 1, "updated_at": updated_at}


def lab_strategy_router(store, runs):
    router = APIRouter(prefix="/api/v1/lab-strategies")

    @router.get("", response_model=list[LabStrategySummary])
    def list_strategies(request: Request):
        return store.list(require_lab_owner(request))

    @router.post("", response_model=LabStrategy, status_code=201)
    def create_strategy(draft: LabDraftCreate, request: Request):
        return store.create(require_lab_owner(request), draft)

    @router.get("/{strategy_id}", response_model=LabStrategy)
    def get_strategy(strategy_id: str, request: Request):
        return store.get(require_lab_owner(request), strategy_id)

    @router.patch("/{strategy_id}", response_model=LabStrategy)
    def update_strategy(strategy_id: str, draft: LabDraftUpdate, request: Request):
        return store.update(require_lab_owner(request), strategy_id, draft)

    @router.get("/{strategy_id}/runs", response_model=list[LabRunSummary])
    def list_runs(strategy_id: str, request: Request):
        owner = require_lab_owner(request)
        store.require_owned(owner, strategy_id)
        return runs.list_lab(owner, strategy_id)

    return router
