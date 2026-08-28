from app.models import StrategyDefinition, StrategyParameter


def number(
    key: str,
    label: str,
    default: float,
    minimum: float,
    maximum: float,
    step: float,
    help: str | None = None,
) -> StrategyParameter:
    return StrategyParameter(
        key=key,
        label=label,
        kind="number",
        default=default,
        minimum=minimum,
        maximum=maximum,
        step=step,
        help=help,
    )


def integer(
    key: str,
    label: str,
    default: int,
    minimum: int,
    maximum: int,
    step: int = 1,
    help: str | None = None,
) -> StrategyParameter:
    return StrategyParameter(
        key=key,
        label=label,
        kind="integer",
        default=default,
        minimum=minimum,
        maximum=maximum,
        step=step,
        help=help,
    )


def boolean(key: str, label: str, default: bool, help: str | None = None) -> StrategyParameter:
    return StrategyParameter(
        key=key,
        label=label,
        kind="boolean",
        default=default,
        help=help,
    )


STRATEGIES = [
    StrategyDefinition(
        id="dca",
        name="定期定额",
        category="资金计划",
        description="按固定K线间隔逐步投入未使用资金。",
        suitable_for="长期积累、弱择时",
        risk_level="中",
        parameters=[
            integer("every_bars", "投入间隔（K线）", 20, 1, 260),
            number("amount_pct", "每次投入占初始资金", 0.05, 0.005, 0.5, 0.005),
            integer("start_delay", "首次投入延迟", 0, 0, 500, help="跳过开头指定数量的K线"),
            integer("max_contributions", "最多投入次数（0=不限）", 0, 0, 500),
        ],
    ),
    StrategyDefinition(
        id="dip_dca",
        name="逢跌加仓定投",
        category="资金计划",
        description="基础定投之外，在阶段回撤达到阈值时增加投入。",
        suitable_for="震荡或长期上行资产",
        risk_level="高",
        parameters=[
            integer("every_bars", "基础间隔", 20, 1, 260),
            number("amount_pct", "基础投入比例", 0.04, 0.005, 0.5, 0.005),
            number("dip_threshold", "加仓回撤阈值", 0.08, 0.01, 0.5, 0.01),
            number("dip_multiplier", "加仓倍数", 2, 1, 5, 0.25),
            integer("drawdown_lookback", "回撤高点回看", 120, 10, 1000),
        ],
    ),
    StrategyDefinition(
        id="arithmetic_grid",
        name="算术网格",
        category="执行策略",
        description="在等价差网格间按价格位置调整目标仓位。",
        suitable_for="有明确区间的震荡市场",
        risk_level="高",
        parameters=[
            number("lower", "网格下限", 70, 0.0001, 1_000_000, 1),
            number("upper", "网格上限", 130, 0.0001, 1_000_000, 1),
            integer("levels", "网格数量", 12, 3, 100),
            number("base_position", "网格基础仓位", 0, 0, 0.8, 0.05),
        ],
    ),
    StrategyDefinition(
        id="geometric_grid",
        name="几何网格",
        category="执行策略",
        description="在等比例网格间按价格位置调整目标仓位。",
        suitable_for="波动较大的加密货币或商品",
        risk_level="高",
        parameters=[
            number("lower", "网格下限", 70, 0.0001, 1_000_000, 1),
            number("upper", "网格上限", 130, 0.0001, 1_000_000, 1),
            integer("levels", "网格数量", 12, 3, 100),
            number("base_position", "网格基础仓位", 0, 0, 0.8, 0.05),
        ],
    ),
    StrategyDefinition(
        id="martingale",
        name="马丁仓位",
        category="仓位策略",
        description="出现阶段亏损时提高目标仓位，严格受最大仓位限制。",
        suitable_for="仅用于理解尾部风险",
        risk_level="极高",
        parameters=[
            integer("rsi_period", "RSI周期", 14, 2, 100),
            number("entry_rsi", "入场RSI", 35, 5, 50, 1),
            number("base_position", "基础仓位", 0.1, 0.01, 0.5, 0.01),
            number("multiplier", "加仓倍数", 2, 1, 4, 0.25),
            number("drawdown_step", "每级回撤幅度", 0.05, 0.01, 0.3, 0.01),
        ],
    ),
    StrategyDefinition(
        id="anti_martingale",
        name="反马丁仓位",
        category="仓位策略",
        description="趋势延续和盈利时逐步增加目标仓位。",
        suitable_for="趋势市场",
        risk_level="高",
        parameters=[
            integer("lookback", "动量周期", 20, 2, 250),
            number("base_position", "基础仓位", 0.15, 0.01, 0.5, 0.01),
            number("multiplier", "盈利加仓倍数", 1.5, 1, 3, 0.1),
            number("level_step", "每级动量幅度", 0.05, 0.01, 0.3, 0.01),
            integer("max_levels", "最多加仓层级", 4, 1, 8),
        ],
    ),
    StrategyDefinition(
        id="sma_cross",
        name="SMA均线交叉",
        category="趋势",
        description="快速简单均线上穿慢线持有，下穿离场。",
        suitable_for="中长期趋势",
        risk_level="中",
        parameters=[
            integer("fast", "快速周期", 20, 2, 200),
            integer("slow", "慢速周期", 60, 5, 400),
            integer("confirm_bars", "交叉确认K线数", 1, 1, 10),
            number(
                "min_gap",
                "最小均线差距",
                0,
                0,
                0.1,
                0.001,
                "以慢线比例计算，用于过滤粘合假突破",
            ),
            integer(
                "trend_filter",
                "长期趋势过滤（0=关闭）",
                0,
                0,
                500,
                help="仅当收盘价高于该周期均线时入场",
            ),
        ],
    ),
    StrategyDefinition(
        id="ema_cross",
        name="EMA均线交叉",
        category="趋势",
        description="使用指数均线更快响应价格变化。",
        suitable_for="趋势和波段",
        risk_level="中",
        parameters=[
            integer("fast", "快速周期", 12, 2, 200),
            integer("slow", "慢速周期", 26, 5, 400),
            integer("confirm_bars", "交叉确认K线数", 1, 1, 10),
            number("min_gap", "最小均线差距", 0, 0, 0.1, 0.001),
            integer("trend_filter", "长期趋势过滤（0=关闭）", 0, 0, 500),
        ],
    ),
    StrategyDefinition(
        id="macd",
        name="MACD交叉",
        category="趋势",
        description="MACD线上穿信号线持有，下穿离场。",
        suitable_for="趋势确认",
        risk_level="中",
        parameters=[
            integer("fast", "快速周期", 12, 2, 100),
            integer("slow", "慢速周期", 26, 5, 200),
            integer("signal", "信号周期", 9, 2, 100),
            integer("confirm_bars", "信号确认K线数", 1, 1, 10),
            boolean("zero_line_filter", "仅在零轴上方做多", False),
        ],
    ),
    StrategyDefinition(
        id="rsi_reversal",
        name="RSI反转",
        category="均值回归",
        description="超卖进入、恢复至退出阈值后离场。",
        suitable_for="区间震荡",
        risk_level="中",
        parameters=[
            integer("period", "RSI周期", 14, 2, 100),
            number("entry", "入场阈值", 30, 5, 50, 1),
            number("exit", "退出阈值", 55, 40, 95, 1),
            integer("entry_confirm", "超卖确认K线数", 1, 1, 10),
            integer("exit_confirm", "退出确认K线数", 1, 1, 10),
        ],
    ),
    StrategyDefinition(
        id="bollinger",
        name="布林带回归",
        category="均值回归",
        description="跌破下轨后进入，回到中轨离场。",
        suitable_for="波动稳定的震荡市场",
        risk_level="中",
        parameters=[
            integer("period", "均线周期", 20, 5, 200),
            number("std_dev", "标准差倍数", 2, 0.5, 4, 0.1),
            number("exit_ratio", "退出位置（下轨→中轨）", 1, 0, 1, 0.1),
            number("min_bandwidth", "最小带宽", 0, 0, 0.5, 0.005),
        ],
    ),
    StrategyDefinition(
        id="breakout",
        name="唐奇安突破",
        category="突破",
        description="突破历史高点进入，跌破退出通道离场。",
        suitable_for="趋势启动",
        risk_level="高",
        parameters=[
            integer("entry_lookback", "突破周期", 55, 5, 300),
            integer("exit_lookback", "退出周期", 20, 2, 200),
            integer("confirm_bars", "突破确认K线数", 1, 1, 10),
            number("breakout_buffer", "突破缓冲比例", 0, 0, 0.1, 0.001),
        ],
    ),
    StrategyDefinition(
        id="momentum",
        name="动量策略",
        category="趋势",
        description="过去一段时间收益为正且超过阈值时持有。",
        suitable_for="持续趋势",
        risk_level="高",
        parameters=[
            integer("lookback", "动量周期", 60, 2, 300),
            number("threshold", "动量阈值", 0.03, -0.5, 1, 0.01),
            integer("smoothing", "动量平滑周期", 1, 1, 30),
            number("exit_threshold", "退出动量阈值", 0, -0.5, 1, 0.01),
        ],
    ),
    StrategyDefinition(
        id="all_weather",
        name="全天候组合",
        category="组合配置",
        description="以股票、长债、中债、黄金和商品构建固定风险来源组合。",
        suitable_for="长期多资产配置",
        risk_level="中",
        mode="portfolio",
        parameters=[],
    ),
    StrategyDefinition(
        id="risk_parity",
        name="风险平价",
        category="组合配置",
        description="按协方差估计使各资产风险贡献尽量接近。",
        suitable_for="多资产分散",
        risk_level="中",
        mode="portfolio",
        parameters=[integer("lookback", "协方差回看", 126, 40, 756)],
    ),
    StrategyDefinition(
        id="sixty_forty",
        name="60/40再平衡",
        category="组合配置",
        description="股票60%、债券40%的经典再平衡基准。",
        suitable_for="长期基准比较",
        risk_level="中",
        mode="portfolio",
        parameters=[],
    ),
]

_BY_ID = {strategy.id: strategy for strategy in STRATEGIES}


def list_strategies(mode: str | None = None) -> list[StrategyDefinition]:
    if mode:
        return [strategy for strategy in STRATEGIES if strategy.mode == mode]
    return STRATEGIES


def get_strategy(strategy_id: str) -> StrategyDefinition:
    try:
        return _BY_ID[strategy_id]
    except KeyError as exc:
        raise ValueError(f"未知策略: {strategy_id}") from exc


def default_params(strategy_id: str) -> dict[str, float | int | str | bool]:
    return {parameter.key: parameter.default for parameter in get_strategy(strategy_id).parameters}
