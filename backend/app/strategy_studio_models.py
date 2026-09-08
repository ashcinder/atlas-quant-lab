from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

StrategyLanguage = Literal["python", "json_dsl", "remote_runner"]
NodeType = Literal[
    "market_data",
    "universe",
    "feature_engine",
    "strategy",
    "ai_guard",
    "position_sizer",
    "risk_gate",
    "execution_review",
    "execution",
    "audit",
    "output",
]
AIRole = Literal[
    "regime_detection",
    "signal_review",
    "risk_control",
    "position_management",
    "execution_review",
]
AIAuthority = Literal["advisory", "veto", "bounded_adjustment"]

ALLOWED_AI_AUTHORITY: dict[str, set[str]] = {
    "regime_detection": {"advisory", "veto"},
    "signal_review": {"advisory", "veto", "bounded_adjustment"},
    "position_management": {"advisory", "bounded_adjustment"},
    "risk_control": {"advisory", "veto", "bounded_adjustment"},
    "execution_review": {"advisory", "veto"},
}
PROVIDER_REF_PATTERN = re.compile(r"^(?:server|local|vault):[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$")
SECRET_KEY_PARTS = {"api_key", "apikey", "token", "password", "secret", "private_key"}


def _secret_config_paths(value: Any, prefix: str = "config") -> set[str]:
    matches: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            normalized = str(key).lower()
            if any(part in normalized for part in SECRET_KEY_PARTS):
                matches.add(path)
            matches.update(_secret_config_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            matches.update(_secret_config_paths(nested, f"{prefix}[{index}]"))
    return matches


class ManifestParameter(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["integer", "number", "boolean", "string", "select"]
    default: int | float | bool | str
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_parameter(self) -> "ManifestParameter":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("参数下限不能高于上限")
        if self.kind == "select" and not self.options:
            raise ValueError("select 参数必须声明 options")
        return self


class ResearchProtocol(BaseModel):
    holdout_ratio: float = Field(default=0.2, ge=0.1, le=0.5)
    walk_forward_required: bool = True
    transaction_costs_required: bool = True
    minimum_trades: int = Field(default=30, ge=10, le=10_000)
    regime_tests: list[Literal["bull", "bear", "sideways", "high_volatility"]] = Field(
        default_factory=lambda: ["bull", "bear", "sideways"], min_length=2
    )


class StrategyManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    api_version: Literal["atlas.strategy/v1"] = "atlas.strategy/v1"
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=2, max_length=100)
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
    language: StrategyLanguage
    entrypoint: str | None = Field(default=None, max_length=180)
    description: str = Field(min_length=12, max_length=800)
    asset_classes: list[str] = Field(min_length=1, max_length=12)
    intervals: list[str] = Field(min_length=1, max_length=12)
    capabilities: list[
        Literal[
            "market_data.read",
            "fundamentals.read",
            "alternative_data.read",
            "portfolio.read",
            "signals.write",
            "orders.propose",
            "ai.request",
        ]
    ] = Field(default_factory=lambda: ["market_data.read", "signals.write"])
    parameters: list[ManifestParameter] = Field(default_factory=list, max_length=80)
    ai_injection_points: list[AIRole] = Field(default_factory=list)
    research: ResearchProtocol = Field(default_factory=ResearchProtocol)

    @field_validator("asset_classes", "intervals", "capabilities", "ai_injection_points")
    @classmethod
    def unique_values(cls, value: list[Any]) -> list[Any]:
        if len(value) != len(set(value)):
            raise ValueError("列表不能包含重复值")
        return value

    @model_validator(mode="after")
    def validate_entrypoint(self) -> "StrategyManifest":
        if self.language == "python":
            if not self.entrypoint or not re.fullmatch(
                r"[a-zA-Z_][a-zA-Z0-9_./]*\.py:[A-Za-z_][A-Za-z0-9_]*", self.entrypoint
            ):
                raise ValueError("Python 策略 entrypoint 必须为 path/to/file.py:ClassName")
            entry_file = self.entrypoint.split(":", 1)[0]
            if entry_file.startswith("/") or ".." in entry_file.split("/"):
                raise ValueError("Python 策略 entrypoint 必须是包内安全相对路径")
        elif self.language == "json_dsl" and self.entrypoint not in (None, "strategy.json"):
            raise ValueError("JSON DSL 策略 entrypoint 必须为 strategy.json 或留空")
        elif self.language == "remote_runner" and self.entrypoint:
            raise ValueError("远程 Runner 不允许在包内声明可执行入口")
        return self


class WorkflowNode(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    type: NodeType
    label: str = Field(min_length=1, max_length=80)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_config(self) -> "WorkflowNode":
        if self.type == "ai_guard":
            role = self.config.get("role")
            authority = self.config.get("authority")
            if role not in AIRole.__args__:
                raise ValueError("AI 节点必须声明有效 role")
            if authority not in AIAuthority.__args__:
                raise ValueError("AI 节点必须声明权限 authority")
            provider_ref = str(self.config.get("provider_ref", "")).strip()
            if not PROVIDER_REF_PATTERN.fullmatch(provider_ref):
                raise ValueError("AI provider_ref 必须是 server:/local:/vault: 开头的服务端引用")
            if authority not in ALLOWED_AI_AUTHORITY[str(role)]:
                raise ValueError(f"{role} 不允许使用 {authority} 权限")
            secret_paths = _secret_config_paths(self.config)
            if secret_paths:
                raise ValueError(f"工作流不允许存放密钥或令牌: {', '.join(sorted(secret_paths))}")
            timeout_ms = self.config.get("timeout_ms")
            if not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= 60_000:
                raise ValueError("AI timeout_ms 必须介于 100–60000")
            if self.config.get("on_error") not in {"deny", "use_baseline", "skip"}:
                raise ValueError("AI 节点必须声明 on_error 失败回退")
            if authority == "bounded_adjustment":
                adjustment = self.config.get("max_adjustment_bps")
                if not isinstance(adjustment, (int, float)) or not 0 < adjustment <= 2_000:
                    raise ValueError("有限调整权限必须将 max_adjustment_bps 限制在 1–2000")
        if self.type == "risk_gate":
            required = {
                "max_gross_exposure",
                "max_single_position",
                "max_daily_loss",
                "max_drawdown",
                "max_participation_rate",
            }
            missing = required.difference(self.config)
            if missing:
                raise ValueError(f"硬风控缺少参数: {', '.join(sorted(missing))}")
            for key in required:
                value = self.config[key]
                if not isinstance(value, (int, float)) or not 0 < value <= 1:
                    raise ValueError(f"{key} 必须介于 0–1")
        return self


class WorkflowEdge(BaseModel):
    source: str
    target: str
    condition: str | None = Field(default=None, max_length=240)


class StrategyWorkflow(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=2, max_length=100)
    package_id: str | None = Field(default=None, max_length=80)
    nodes: list[WorkflowNode] = Field(min_length=5, max_length=60)
    edges: list[WorkflowEdge] = Field(min_length=4, max_length=120)
    description: str = Field(default="", max_length=500)


class WorkflowSaveRequest(BaseModel):
    workflow: StrategyWorkflow
    change_note: str = Field(default="", max_length=240)
