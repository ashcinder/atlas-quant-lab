"""Private research execution contracts; none of these is a proof claim."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    market_data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, int | float | bool | str] = Field(default_factory=dict, max_length=80)
    initial_capital: float = Field(default=100_000, gt=0, le=1e9)
    commission_bps: int = Field(default=10, ge=0, le=1000)
    slippage_bps: int = Field(default=5, ge=0, le=1000)
    max_position: float = Field(default=0.95, gt=0, le=0.95)
    max_drawdown: float = Field(default=0.25, gt=0, le=1)
    max_participation: float = Field(default=0.01, gt=0, le=0.1)
    max_bars: int = Field(default=256, ge=3, le=1024)
    ai_provider: Literal["local"] | None = None
    ai_authority: Literal["advisory", "veto", "reduce_only"] = "veto"
    # Consent is explicit: encrypted-at-rest uploads are visible to this host.
    acknowledge_host_visibility: bool = False


class TargetProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbol: str = Field(min_length=1, max_length=48)
    target_weight: float = Field(ge=0, le=1)


class AIJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    request_id: str
    action: Literal["approve", "deny", "reduce"]
    scale: float = Field(ge=0, le=1)
