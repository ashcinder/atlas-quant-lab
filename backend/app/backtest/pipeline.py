"""Explicit execution settings shared by visual and template strategies."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AIStage(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    stage: Literal["market", "entry", "buy_size", "sell_size", "risk", "execution"]
    enabled: bool = False
    authority: Literal["advisory", "veto", "reduce_only"] = "advisory"
    instructions: str = Field(default="", max_length=4000)
    timeout_ms: int = Field(default=2500, ge=100, le=30000)
    max_reduction: float = Field(default=0.25, ge=0, le=1)


class ExecutionPipeline(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_position: float = Field(default=0.5, gt=0, le=1)
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    max_participation_rate: float = Field(default=0.01, gt=0, le=1)
    ai_stages: list[AIStage] = Field(default_factory=list, max_length=6)
