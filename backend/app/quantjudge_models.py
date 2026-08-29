from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HEX_64 = r"^[0-9a-f]{64}$"


class QuantAgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    developer_alias: str = Field(min_length=2, max_length=40)
    agent_type: Literal["ai_agent", "traditional"] = "ai_agent"
    category: Literal["stock_selection", "timing", "allocation", "multi_factor", "arbitrage"]
    asset_classes: list[str] = Field(min_length=1, max_length=8)
    description: str = Field(min_length=12, max_length=600)
    risk_level: Literal["low", "medium", "high", "extreme"] = "medium"
    monthly_price: float = Field(default=0, ge=0, le=1_000_000)
    price_currency: Literal["CNY", "USDT"] = "CNY"
    strategy_commitment: str = Field(pattern=HEX_64)

    @field_validator("asset_classes")
    @classmethod
    def unique_asset_classes(cls, value: list[str]) -> list[str]:
        clean = [item.strip().lower() for item in value if item.strip()]
        if len(clean) != len(set(clean)):
            raise ValueError("资产类别不能重复")
        return clean


class PrivateEquityPoint(BaseModel):
    time: int = Field(gt=0)
    equity: float = Field(gt=0)
    benchmark: float | None = Field(default=None, gt=0)


class ExternalProof(BaseModel):
    proof_type: Literal["zk_snark", "tee_attestation"]
    proof_hash: str = Field(pattern=HEX_64)
    verifier: str = Field(min_length=3, max_length=160)
    verifier_reference: str | None = Field(default=None, max_length=300)


class PerformanceReportCreate(BaseModel):
    report_type: Literal["backtest", "live"]
    period_start: datetime
    period_end: datetime
    equity_points: list[PrivateEquityPoint] = Field(min_length=2, max_length=20_000)
    decision_commitments: list[str] = Field(min_length=1, max_length=20_000)
    market_data_hash: str = Field(pattern=HEX_64)
    external_proof: ExternalProof | None = None

    @field_validator("decision_commitments")
    @classmethod
    def validate_commitments(cls, value: list[str]) -> list[str]:
        if any(len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item) for item in value):
            raise ValueError("决策承诺必须是小写 SHA-256 十六进制字符串")
        return value

    @model_validator(mode="after")
    def validate_period_and_points(self) -> "PerformanceReportCreate":
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("统计周期必须带时区")
        if self.period_start >= self.period_end:
            raise ValueError("统计周期起点必须早于终点")
        times = [point.time for point in self.equity_points]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("净值点必须按时间严格递增")
        return self


class SubscriptionCreate(BaseModel):
    investor_alias: str = Field(min_length=2, max_length=60)
    billing_cycle: Literal["monthly", "quarterly", "yearly"] = "monthly"
    payment_reference: str | None = Field(default=None, max_length=180)


class AnchorRequest(BaseModel):
    signed_raw_transaction: str = Field(min_length=4, max_length=500_000)

    @field_validator("signed_raw_transaction")
    @classmethod
    def validate_raw_transaction(cls, value: str) -> str:
        if not value.startswith("0x") or any(ch not in "0123456789abcdefABCDEF" for ch in value[2:]):
            raise ValueError("必须提供外部钱包签名的 0x 原始交易")
        return value


class ChainTransactionAttach(BaseModel):
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
