from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Interval = Literal["15m", "1h", "4h", "1d", "1wk"]
Adjustment = Literal["auto", "raw", "forward", "backward"]


class Asset(BaseModel):
    symbol: str
    name: str
    asset_class: str
    exchange: str
    currency: str
    timezone: str = "UTC"
    provider_symbol: str | None = None
    tags: list[str] = Field(default_factory=list)


class Bar(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0


class MarketDataResponse(BaseModel):
    asset: Asset
    interval: Interval
    adjustment: Adjustment
    source: str
    source_note: str | None = None
    fetched_at: int
    last_bar_time: int
    cache_hit: bool = False
    is_stale: bool = False
    bars: list[Bar]
    indicators: dict[str, list[dict[str, float | int | None]]]


class StrategyParameter(BaseModel):
    key: str
    label: str
    kind: Literal["number", "integer", "select", "boolean"]
    default: float | int | str | bool
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[dict[str, str]] | None = None
    help: str | None = None


class StrategyDefinition(BaseModel):
    id: str
    name: str
    category: str
    description: str
    suitable_for: str
    risk_level: Literal["低", "中", "高", "极高"]
    mode: Literal["single", "portfolio"] = "single"
    parameters: list[StrategyParameter]


class BacktestRequest(BaseModel):
    symbol: str = "BTC-USD"
    asset_class: str = "crypto"
    interval: Interval = "1d"
    start: datetime | None = None
    end: datetime | None = None
    adjustment: Adjustment = "auto"
    base_currency: Literal["CNY", "USD", "USDT"] = "CNY"
    data_source: Literal["auto", "yahoo", "binance", "demo"] = "auto"
    strategy_id: str = "sma_cross"
    custom_strategy: "CustomStrategySpec | None" = None
    params: dict[str, Any] = Field(default_factory=dict)
    initial_capital: float = Field(default=100_000, gt=0)
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    spread_rate: float = Field(default=0.0005, ge=0, le=0.1)
    max_position: float = Field(default=0.95, gt=0, le=1)
    max_participation_rate: float = Field(default=0.01, gt=0, le=1)
    stop_loss: float | None = Field(default=None, gt=0, lt=1)
    take_profit: float | None = Field(default=None, gt=0)
    persist: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestRequest":
        if self.start and self.end and self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class Trade(BaseModel):
    id: int
    time: int
    side: Literal["buy", "sell"]
    reason: str
    price: float
    quantity: float
    notional: float
    fee: float
    slippage_cost: float
    position_after: float
    cash_after: float
    realized_pnl: float | None = None


class EquityPoint(BaseModel):
    time: int
    equity: float
    benchmark: float
    drawdown: float
    exposure: float


class BacktestResult(BaseModel):
    run_id: str
    created_at: datetime
    asset: Asset
    interval: Interval
    strategy: StrategyDefinition
    data_source: str
    source_note: str | None = None
    bars: list[Bar]
    indicators: dict[str, list[dict[str, float | int | None]]]
    trades: list[Trade]
    equity: list[EquityPoint]
    metrics: dict[str, float | int | None]
    regime_metrics: dict[str, dict[str, float | int | None]]
    warnings: list[str]


class PortfolioAssetInput(BaseModel):
    symbol: str
    asset_class: str = "equity"
    weight: float | None = Field(default=None, ge=0, le=1)


class PortfolioBacktestRequest(BaseModel):
    assets: list[PortfolioAssetInput] = Field(min_length=2, max_length=12)
    strategy_id: Literal["all_weather", "risk_parity", "sixty_forty"] = "all_weather"
    interval: Interval = "1d"
    start: datetime | None = None
    end: datetime | None = None
    initial_capital: float = Field(default=100_000, gt=0)
    rebalance: Literal["monthly", "quarterly", "yearly"] = "quarterly"
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    data_source: Literal["auto", "yahoo", "demo"] = "auto"
    base_currency: Literal["CNY", "USD", "USDT"] = "CNY"
    persist: bool = True


class PortfolioResult(BaseModel):
    run_id: str
    created_at: datetime
    strategy: StrategyDefinition
    assets: list[Asset]
    data_source: str
    weights: dict[str, float]
    weight_history: list[dict[str, Any]]
    equity: list[EquityPoint]
    trades: list[Trade]
    metrics: dict[str, float | int | None]
    risk_contribution: dict[str, float]
    correlation: dict[str, dict[str, float]]
    warnings: list[str]


class RunSummary(BaseModel):
    id: str
    mode: str
    strategy_id: str
    symbol: str
    created_at: datetime
    total_return: float | None = None
    max_drawdown: float | None = None
    status: str


class IndicatorSpec(BaseModel):
    field: Literal[
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma",
        "ema",
        "rsi",
        "macd",
        "macd_signal",
        "boll_upper",
        "boll_lower",
        "roc",
    ]
    period: int | None = Field(default=None, ge=2, le=500)


class RuleNode(BaseModel):
    kind: Literal["condition", "group"]
    combinator: Literal["all", "any"] | None = None
    children: list["RuleNode"] = Field(default_factory=list, max_length=20)
    left: IndicatorSpec | None = None
    operator: Literal["gt", "gte", "lt", "lte", "crosses_above", "crosses_below"] | None = None
    right_indicator: IndicatorSpec | None = None
    right_value: float | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "RuleNode":
        if self.kind == "group":
            if self.combinator is None or not self.children:
                raise ValueError("条件组必须包含逻辑关系和子条件")
            if self.left or self.operator or self.right_indicator or self.right_value is not None:
                raise ValueError("条件组不能同时包含比较表达式")
        else:
            if self.left is None or self.operator is None:
                raise ValueError("比较条件必须包含左值和操作符")
            if (self.right_indicator is None) == (self.right_value is None):
                raise ValueError("比较条件必须且只能设置一种右值")
            if self.children:
                raise ValueError("比较条件不能包含子条件")
        return self


class CustomStrategySpec(BaseModel):
    id: str = Field(default="custom", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="个人自定义策略", max_length=300)
    entry: RuleNode
    exit: RuleNode
    target_position: float = Field(default=0.95, gt=0, le=1)


class CustomStrategyRecord(BaseModel):
    id: str
    spec: CustomStrategySpec
    created_at: datetime
    updated_at: datetime


class ResearchExperiment(BaseModel):
    strategy_id: str
    base_params: dict[str, Any] = Field(default_factory=dict)
    parameter_grid: dict[str, list[float | int | bool]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_grid(self) -> "ResearchExperiment":
        combinations = 1
        for key, values in self.parameter_grid.items():
            if not key or not values or len(values) > 20:
                raise ValueError("每个参数网格必须包含1–20个值")
            combinations *= len(values)
        if combinations > 200:
            raise ValueError("单个策略的参数组合不能超过200组")
        return self


class WalkForwardConfig(BaseModel):
    enabled: bool = True
    train_bars: int = Field(default=500, ge=80, le=10_000)
    test_bars: int = Field(default=120, ge=40, le=2_000)
    step_bars: int = Field(default=120, ge=20, le=2_000)
    max_windows: int = Field(default=8, ge=1, le=20)


class ResearchRequest(BaseModel):
    symbol: str
    asset_class: str
    interval: Interval = "1d"
    adjustment: Adjustment = "auto"
    data_source: Literal["auto", "yahoo", "binance", "demo"] = "auto"
    experiments: list[ResearchExperiment] = Field(min_length=1, max_length=8)
    objective: Literal["sharpe", "calmar", "cagr", "total_return"] = "sharpe"
    holdout_ratio: float = Field(default=0.2, ge=0.1, le=0.4)
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    initial_capital: float = Field(default=100_000, gt=0)
    commission_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    spread_rate: float = Field(default=0.0005, ge=0, le=0.1)
    max_position: float = Field(default=0.95, gt=0, le=1)
    max_participation_rate: float = Field(default=0.01, gt=0, le=1)

    @model_validator(mode="after")
    def validate_budget(self) -> "ResearchRequest":
        total = 0
        for experiment in self.experiments:
            combinations = 1
            for values in experiment.parameter_grid.values():
                combinations *= len(values)
            total += combinations
        if total > 500:
            raise ValueError("单次研究任务最多评估500组参数")
        projected = total * (
            1 + (self.walk_forward.max_windows if self.walk_forward.enabled else 0)
        )
        if projected > 2_500:
            raise ValueError("网格与Walk-forward窗口的总评估量不能超过2500次")
        return self


class ResearchCandidate(BaseModel):
    strategy_id: str
    params: dict[str, Any]
    train_metrics: dict[str, float | int | None]
    test_metrics: dict[str, float | int | None]
    objective_train: float | None
    objective_test: float | None
    sharpe_degradation: float | None
    adjusted_p_value: float | None
    robustness_score: float
    rank: int = 0
    warnings: list[str] = Field(default_factory=list)


class WalkForwardWindow(BaseModel):
    strategy_id: str
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    params: dict[str, Any]
    train_sharpe: float | None
    test_sharpe: float | None
    test_return: float | None
    trades: int


class ResearchResult(BaseModel):
    job_id: str
    symbol: str
    interval: Interval
    objective: str
    data_source: str
    tested_combinations: int
    candidates: list[ResearchCandidate]
    walk_forward: list[WalkForwardWindow]
    summary: dict[str, float | int | bool | None]
    warnings: list[str]
    created_at: datetime


class ResearchJob(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: float = Field(ge=0, le=1)
    message: str
    result: ResearchResult | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    symbol: str
    asset_class: str
    interval: Interval = "1d"
    data_source: Literal["auto", "yahoo", "binance", "demo"] = "auto"
    kind: Literal[
        "price_above",
        "price_below",
        "price_crosses_above",
        "price_crosses_below",
        "change_pct_above",
        "rsi_below",
        "rsi_above",
        "macd_crosses_above",
        "macd_crosses_below",
    ]
    threshold: float | None = None
    cooldown_minutes: int = Field(default=60, ge=1, le=43_200)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_threshold(self) -> "AlertRuleCreate":
        if self.kind not in {"macd_crosses_above", "macd_crosses_below"}:
            if self.threshold is None:
                raise ValueError("该提醒类型必须设置阈值")
        return self


class AlertRule(AlertRuleCreate):
    id: str
    last_value: float | None = None
    last_triggered_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AlertNotification(BaseModel):
    id: str
    alert_id: str
    title: str
    message: str
    triggered_at: datetime
    value: float
    read: bool = False


BacktestRequest.model_rebuild()
