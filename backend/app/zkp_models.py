from __future__ import annotations

import hashlib
import struct
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX_64 = r"^[0-9a-f]{64}$"


class ZkMetricSet(BaseModel):
    """Public metrics emitted by the guest, encoded without floating point ambiguity."""

    total_return_ppm: int = Field(ge=-1_000_000, le=100_000_000)
    annualized_return_ppm: int = Field(ge=-1_000_000, le=100_000_000)
    max_drawdown_ppm: int = Field(ge=-1_000_000, le=0)
    annualized_volatility_ppm: int = Field(ge=0, le=100_000_000)
    sharpe_milli: int = Field(ge=-100_000, le=100_000)
    win_rate_ppm: int = Field(ge=0, le=1_000_000)
    benchmark_return_ppm: int = Field(ge=-1_000_000, le=100_000_000)
    observation_count: int = Field(ge=2, le=20_000)

    def as_public_metrics(self) -> dict[str, float | int]:
        return {
            "total_return": self.total_return_ppm / 1_000_000,
            "annualized_return": self.annualized_return_ppm / 1_000_000,
            "max_drawdown": self.max_drawdown_ppm / 1_000_000,
            "annualized_volatility": self.annualized_volatility_ppm / 1_000_000,
            "sharpe": self.sharpe_milli / 1_000,
            "win_rate": self.win_rate_ppm / 1_000_000,
            "benchmark_return": self.benchmark_return_ppm / 1_000_000,
            "observation_count": self.observation_count,
            "live_days": 0,
        }


class ZkCurvePoint(BaseModel):
    time: int = Field(gt=0)
    return_ppm: int = Field(ge=-1_000_000, le=100_000_000)
    benchmark_return_ppm: int = Field(ge=-1_000_000, le=100_000_000)

    def as_public_point(self) -> dict[str, float | int]:
        return {
            "time": self.time,
            "return": self.return_ppm / 1_000_000,
            "benchmark_return": self.benchmark_return_ppm / 1_000_000,
        }


class ZkPublicStatement(BaseModel):
    """The exact journal contract committed by the registered zkVM guest."""

    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["atlas.quantjudge.zk.statement.v1"] = Field(alias="schema")
    proof_profile: Literal["atlas_sma_backtest_risc0_v1"]
    agent_id: str = Field(pattern=r"^qja_[a-zA-Z0-9_]{2,64}$")
    strategy_commitment: str = Field(pattern=HEX_64)
    workflow_commitment: str = Field(pattern=HEX_64)
    market_data_hash: str = Field(pattern=HEX_64)
    cost_model_hash: str = Field(pattern=HEX_64)
    report_type: Literal["backtest"]
    period_start: int = Field(gt=0)
    period_end: int = Field(gt=0)
    initial_equity_micros: int = Field(gt=0, le=10**21)
    final_equity_micros: int = Field(gt=0, le=10**23)
    decision_count: int = Field(ge=1, le=20_000)
    decision_merkle_root: str = Field(pattern=HEX_64)
    equity_curve_hash: str = Field(pattern=HEX_64)
    previous_receipt_hash: str | None = Field(default=None, pattern=HEX_64)
    nullifier: str = Field(pattern=HEX_64)
    metrics: ZkMetricSet
    public_curve: list[ZkCurvePoint] = Field(min_length=2, max_length=96)

    @field_validator(
        "strategy_commitment",
        "workflow_commitment",
        "market_data_hash",
        "cost_model_hash",
        "decision_merkle_root",
        "equity_curve_hash",
        "previous_receipt_hash",
        "nullifier",
    )
    @classmethod
    def lowercase_hex(cls, value: str | None) -> str | None:
        if value is not None and value != value.lower():
            raise ValueError("公开承诺必须使用小写十六进制")
        return value

    @model_validator(mode="after")
    def validate_statement(self) -> ZkPublicStatement:
        if self.period_start >= self.period_end:
            raise ValueError("证明周期起点必须早于终点")
        times = [point.time for point in self.public_curve]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("公开净值曲线时间必须严格递增")
        if times[0] < self.period_start or times[-1] > self.period_end:
            raise ValueError("公开净值曲线必须位于证明周期内")
        if self.metrics.observation_count < len(self.public_curve):
            raise ValueError("观测数不能少于公开净值点数")
        return self

    def curve_commitment(self) -> str:
        digest = hashlib.sha256()
        digest.update(b"ATLASCURVE1")
        digest.update(struct.pack(">I", len(self.public_curve)))
        for point in self.public_curve:
            digest.update(
                struct.pack(
                    ">qqq", point.time, point.return_ppm, point.benchmark_return_ppm
                )
            )
        return digest.hexdigest()


class ZkReportPublishCreate(BaseModel):
    proof_id: str = Field(pattern=r"^qzp_[0-9a-f]{18}$")
