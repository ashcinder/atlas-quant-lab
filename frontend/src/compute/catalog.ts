// Snapshot of the published Python catalog; keep parity tests when changing.
import type {Strategy} from "../types"
export const STRATEGIES:Strategy[] = [
  {
    "mode": "single",
    "id": "scheduled_dca",
    "name": "定期定额（固定金额）",
    "category": "资金计划",
    "description": "按日历间隔买入固定金额，使用账户可用资金；不按仓位百分比逐步加仓。",
    "suitable_for": "固定金额定投；资金不足时跳过，不虚构入金",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 1,
        "maximum": 10000000,
        "step": 100,
        "options": null,
        "help": null,
        "key": "amount",
        "label": "每次定投金额（标的报价币种，含手续费）",
        "kind": "number",
        "default": 1000
      },
      {
        "minimum": 1,
        "maximum": 365,
        "step": 1,
        "options": null,
        "help": null,
        "key": "every",
        "label": "间隔数量",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": null,
        "maximum": null,
        "step": null,
        "options": [
          {
            "value": "hours",
            "label": "小时"
          },
          {
            "value": "days",
            "label": "天"
          },
          {
            "value": "weeks",
            "label": "周"
          },
          {
            "value": "months",
            "label": "月"
          }
        ],
        "help": null,
        "key": "unit",
        "label": "间隔单位",
        "kind": "select",
        "default": "weeks"
      },
      {
        "minimum": 0,
        "maximum": 10000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "start_delay",
        "label": "开始延迟（K线）",
        "kind": "integer",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "dca",
    "name": "分期建仓（旧版）",
    "category": "资金计划",
    "description": "按固定K线间隔逐步投入未使用资金。",
    "suitable_for": "长期积累、弱择时",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 1,
        "maximum": 260,
        "step": 1,
        "options": null,
        "help": null,
        "key": "every_bars",
        "label": "投入间隔（K线）",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 0.005,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": null,
        "key": "amount_pct",
        "label": "每次增加目标仓位（0.05=5个百分点）",
        "kind": "number",
        "default": 0.05
      },
      {
        "minimum": 0,
        "maximum": 500,
        "step": 1,
        "options": null,
        "help": "跳过开头指定数量的K线",
        "key": "start_delay",
        "label": "首次投入延迟",
        "kind": "integer",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 500,
        "step": 1,
        "options": null,
        "help": null,
        "key": "max_contributions",
        "label": "最多投入次数（0=不限）",
        "kind": "integer",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "dip_dca",
    "name": "逢跌加仓定投",
    "category": "资金计划",
    "description": "基础定投之外，在阶段回撤达到阈值时增加投入。",
    "suitable_for": "震荡或长期上行资产",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 1,
        "maximum": 260,
        "step": 1,
        "options": null,
        "help": null,
        "key": "every_bars",
        "label": "基础间隔",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 0.005,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": null,
        "key": "amount_pct",
        "label": "基础投入比例",
        "kind": "number",
        "default": 0.04
      },
      {
        "minimum": 0.01,
        "maximum": 0.5,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "dip_threshold",
        "label": "加仓回撤阈值",
        "kind": "number",
        "default": 0.08
      },
      {
        "minimum": 1,
        "maximum": 5,
        "step": 0.25,
        "options": null,
        "help": null,
        "key": "dip_multiplier",
        "label": "加仓倍数",
        "kind": "number",
        "default": 2
      },
      {
        "minimum": 10,
        "maximum": 1000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "drawdown_lookback",
        "label": "回撤高点回看",
        "kind": "integer",
        "default": 120
      }
    ]
  },
  {
    "mode": "single",
    "id": "arithmetic_grid",
    "name": "算术网格",
    "category": "执行策略",
    "description": "在等价差网格间按价格位置调整目标仓位。",
    "suitable_for": "有明确区间的震荡市场",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 0.0001,
        "maximum": 1000000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "lower",
        "label": "网格下限",
        "kind": "number",
        "default": 70
      },
      {
        "minimum": 0.0001,
        "maximum": 1000000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "upper",
        "label": "网格上限",
        "kind": "number",
        "default": 130
      },
      {
        "minimum": 3,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "levels",
        "label": "网格数量",
        "kind": "integer",
        "default": 12
      },
      {
        "minimum": 0,
        "maximum": 0.8,
        "step": 0.05,
        "options": null,
        "help": null,
        "key": "base_position",
        "label": "网格基础仓位",
        "kind": "number",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "geometric_grid",
    "name": "几何网格",
    "category": "执行策略",
    "description": "在等比例网格间按价格位置调整目标仓位。",
    "suitable_for": "波动较大的加密货币或商品",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 0.0001,
        "maximum": 1000000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "lower",
        "label": "网格下限",
        "kind": "number",
        "default": 70
      },
      {
        "minimum": 0.0001,
        "maximum": 1000000,
        "step": 1,
        "options": null,
        "help": null,
        "key": "upper",
        "label": "网格上限",
        "kind": "number",
        "default": 130
      },
      {
        "minimum": 3,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "levels",
        "label": "网格数量",
        "kind": "integer",
        "default": 12
      },
      {
        "minimum": 0,
        "maximum": 0.8,
        "step": 0.05,
        "options": null,
        "help": null,
        "key": "base_position",
        "label": "网格基础仓位",
        "kind": "number",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "martingale",
    "name": "马丁仓位",
    "category": "仓位策略",
    "description": "出现阶段亏损时提高目标仓位，严格受最大仓位限制。",
    "suitable_for": "仅用于理解尾部风险",
    "risk_level": "极高",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "rsi_period",
        "label": "RSI周期",
        "kind": "integer",
        "default": 14
      },
      {
        "minimum": 5,
        "maximum": 50,
        "step": 1,
        "options": null,
        "help": null,
        "key": "entry_rsi",
        "label": "入场RSI",
        "kind": "number",
        "default": 35
      },
      {
        "minimum": 0.01,
        "maximum": 0.5,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "base_position",
        "label": "基础仓位",
        "kind": "number",
        "default": 0.1
      },
      {
        "minimum": 1,
        "maximum": 4,
        "step": 0.25,
        "options": null,
        "help": null,
        "key": "multiplier",
        "label": "加仓倍数",
        "kind": "number",
        "default": 2
      },
      {
        "minimum": 0.01,
        "maximum": 0.3,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "drawdown_step",
        "label": "每级回撤幅度",
        "kind": "number",
        "default": 0.05
      }
    ]
  },
  {
    "mode": "single",
    "id": "anti_martingale",
    "name": "反马丁仓位",
    "category": "仓位策略",
    "description": "趋势延续和盈利时逐步增加目标仓位。",
    "suitable_for": "趋势市场",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 250,
        "step": 1,
        "options": null,
        "help": null,
        "key": "lookback",
        "label": "动量周期",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 0.01,
        "maximum": 0.5,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "base_position",
        "label": "基础仓位",
        "kind": "number",
        "default": 0.15
      },
      {
        "minimum": 1,
        "maximum": 3,
        "step": 0.1,
        "options": null,
        "help": null,
        "key": "multiplier",
        "label": "盈利加仓倍数",
        "kind": "number",
        "default": 1.5
      },
      {
        "minimum": 0.01,
        "maximum": 0.3,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "level_step",
        "label": "每级动量幅度",
        "kind": "number",
        "default": 0.05
      },
      {
        "minimum": 1,
        "maximum": 8,
        "step": 1,
        "options": null,
        "help": null,
        "key": "max_levels",
        "label": "最多加仓层级",
        "kind": "integer",
        "default": 4
      }
    ]
  },
  {
    "mode": "single",
    "id": "sma_cross",
    "name": "SMA均线交叉",
    "category": "趋势",
    "description": "快速简单均线上穿慢线持有，下穿离场。",
    "suitable_for": "中长期趋势",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 200,
        "step": 1,
        "options": null,
        "help": null,
        "key": "fast",
        "label": "快速周期",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 5,
        "maximum": 400,
        "step": 1,
        "options": null,
        "help": null,
        "key": "slow",
        "label": "慢速周期",
        "kind": "integer",
        "default": 60
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "confirm_bars",
        "label": "交叉确认K线数",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": 0,
        "maximum": 0.1,
        "step": 0.001,
        "options": null,
        "help": "以慢线比例计算，用于过滤粘合假突破",
        "key": "min_gap",
        "label": "最小均线差距",
        "kind": "number",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 500,
        "step": 1,
        "options": null,
        "help": "仅当收盘价高于该周期均线时入场",
        "key": "trend_filter",
        "label": "长期趋势过滤（0=关闭）",
        "kind": "integer",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "ema_cross",
    "name": "EMA均线交叉",
    "category": "趋势",
    "description": "使用指数均线更快响应价格变化。",
    "suitable_for": "趋势和波段",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 200,
        "step": 1,
        "options": null,
        "help": null,
        "key": "fast",
        "label": "快速周期",
        "kind": "integer",
        "default": 12
      },
      {
        "minimum": 5,
        "maximum": 400,
        "step": 1,
        "options": null,
        "help": null,
        "key": "slow",
        "label": "慢速周期",
        "kind": "integer",
        "default": 26
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "confirm_bars",
        "label": "交叉确认K线数",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": 0,
        "maximum": 0.1,
        "step": 0.001,
        "options": null,
        "help": null,
        "key": "min_gap",
        "label": "最小均线差距",
        "kind": "number",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 500,
        "step": 1,
        "options": null,
        "help": null,
        "key": "trend_filter",
        "label": "长期趋势过滤（0=关闭）",
        "kind": "integer",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "macd",
    "name": "MACD交叉",
    "category": "趋势",
    "description": "MACD线上穿信号线持有，下穿离场。",
    "suitable_for": "趋势确认",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "fast",
        "label": "快速周期",
        "kind": "integer",
        "default": 12
      },
      {
        "minimum": 5,
        "maximum": 200,
        "step": 1,
        "options": null,
        "help": null,
        "key": "slow",
        "label": "慢速周期",
        "kind": "integer",
        "default": 26
      },
      {
        "minimum": 2,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "signal",
        "label": "信号周期",
        "kind": "integer",
        "default": 9
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "confirm_bars",
        "label": "信号确认K线数",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": null,
        "maximum": null,
        "step": null,
        "options": null,
        "help": null,
        "key": "zero_line_filter",
        "label": "仅在零轴上方做多",
        "kind": "boolean",
        "default": false
      }
    ]
  },
  {
    "mode": "single",
    "id": "rsi_reversal",
    "name": "RSI反转",
    "category": "均值回归",
    "description": "超卖进入、恢复至退出阈值后离场。",
    "suitable_for": "区间震荡",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 100,
        "step": 1,
        "options": null,
        "help": null,
        "key": "period",
        "label": "RSI周期",
        "kind": "integer",
        "default": 14
      },
      {
        "minimum": 5,
        "maximum": 50,
        "step": 1,
        "options": null,
        "help": null,
        "key": "entry",
        "label": "入场阈值",
        "kind": "number",
        "default": 30
      },
      {
        "minimum": 40,
        "maximum": 95,
        "step": 1,
        "options": null,
        "help": null,
        "key": "exit",
        "label": "退出阈值",
        "kind": "number",
        "default": 55
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "entry_confirm",
        "label": "超卖确认K线数",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "exit_confirm",
        "label": "退出确认K线数",
        "kind": "integer",
        "default": 1
      }
    ]
  },
  {
    "mode": "single",
    "id": "bollinger",
    "name": "布林带回归",
    "category": "均值回归",
    "description": "跌破下轨后进入，回到中轨离场。",
    "suitable_for": "波动稳定的震荡市场",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 5,
        "maximum": 200,
        "step": 1,
        "options": null,
        "help": null,
        "key": "period",
        "label": "均线周期",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 0.5,
        "maximum": 4,
        "step": 0.1,
        "options": null,
        "help": null,
        "key": "std_dev",
        "label": "标准差倍数",
        "kind": "number",
        "default": 2
      },
      {
        "minimum": 0,
        "maximum": 1,
        "step": 0.1,
        "options": null,
        "help": null,
        "key": "exit_ratio",
        "label": "退出位置（下轨→中轨）",
        "kind": "number",
        "default": 1
      },
      {
        "minimum": 0,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": null,
        "key": "min_bandwidth",
        "label": "最小带宽",
        "kind": "number",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "breakout",
    "name": "唐奇安突破",
    "category": "突破",
    "description": "突破历史高点进入，跌破退出通道离场。",
    "suitable_for": "趋势启动",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 5,
        "maximum": 300,
        "step": 1,
        "options": null,
        "help": null,
        "key": "entry_lookback",
        "label": "突破周期",
        "kind": "integer",
        "default": 55
      },
      {
        "minimum": 2,
        "maximum": 200,
        "step": 1,
        "options": null,
        "help": null,
        "key": "exit_lookback",
        "label": "退出周期",
        "kind": "integer",
        "default": 20
      },
      {
        "minimum": 1,
        "maximum": 10,
        "step": 1,
        "options": null,
        "help": null,
        "key": "confirm_bars",
        "label": "突破确认K线数",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": 0,
        "maximum": 0.1,
        "step": 0.001,
        "options": null,
        "help": null,
        "key": "breakout_buffer",
        "label": "突破缓冲比例",
        "kind": "number",
        "default": 0
      }
    ]
  },
  {
    "mode": "single",
    "id": "momentum",
    "name": "动量策略",
    "category": "趋势",
    "description": "过去一段时间收益为正且超过阈值时持有。",
    "suitable_for": "持续趋势",
    "risk_level": "高",
    "parameters": [
      {
        "minimum": 2,
        "maximum": 300,
        "step": 1,
        "options": null,
        "help": null,
        "key": "lookback",
        "label": "动量周期",
        "kind": "integer",
        "default": 60
      },
      {
        "minimum": -0.5,
        "maximum": 1,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "threshold",
        "label": "动量阈值",
        "kind": "number",
        "default": 0.03
      },
      {
        "minimum": 1,
        "maximum": 30,
        "step": 1,
        "options": null,
        "help": null,
        "key": "smoothing",
        "label": "动量平滑周期",
        "kind": "integer",
        "default": 1
      },
      {
        "minimum": -0.5,
        "maximum": 1,
        "step": 0.01,
        "options": null,
        "help": null,
        "key": "exit_threshold",
        "label": "退出动量阈值",
        "kind": "number",
        "default": 0
      }
    ]
  },
  {
    "mode": "portfolio",
    "id": "all_weather",
    "name": "全天候组合",
    "category": "组合配置",
    "description": "以股票、长债、中债、黄金和商品构建固定风险来源组合。",
    "suitable_for": "长期多资产配置",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 0,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": "0 表示每个计划日都再平衡；大于 0 时只在偏离超限后调仓",
        "key": "rebalance_band",
        "label": "再平衡偏离阈值",
        "kind": "number",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 0.05,
        "step": 0.0005,
        "options": null,
        "help": "小于组合净值该比例的调仓交易会被忽略",
        "key": "min_trade_rate",
        "label": "最小调仓比例",
        "kind": "number",
        "default": 0.001
      }
    ]
  },
  {
    "mode": "portfolio",
    "id": "risk_parity",
    "name": "风险平价",
    "category": "组合配置",
    "description": "按协方差估计使各资产风险贡献尽量接近。",
    "suitable_for": "多资产分散",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 40,
        "maximum": 756,
        "step": 1,
        "options": null,
        "help": null,
        "key": "lookback",
        "label": "协方差回看",
        "kind": "integer",
        "default": 126
      },
      {
        "minimum": 0,
        "maximum": 1,
        "step": 0.05,
        "options": null,
        "help": "向对角阵收缩，降低小样本协方差噪声",
        "key": "covariance_shrinkage",
        "label": "协方差收缩",
        "kind": "number",
        "default": 0.1
      },
      {
        "minimum": 0,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": null,
        "key": "rebalance_band",
        "label": "再平衡偏离阈值",
        "kind": "number",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 0.05,
        "step": 0.0005,
        "options": null,
        "help": null,
        "key": "min_trade_rate",
        "label": "最小调仓比例",
        "kind": "number",
        "default": 0.001
      }
    ]
  },
  {
    "mode": "portfolio",
    "id": "sixty_forty",
    "name": "60/40再平衡",
    "category": "组合配置",
    "description": "股票60%、债券40%的经典再平衡基准。",
    "suitable_for": "长期基准比较",
    "risk_level": "中",
    "parameters": [
      {
        "minimum": 0.1,
        "maximum": 0.9,
        "step": 0.05,
        "options": null,
        "help": "第一项权益资产的目标权重，余下权重由其他资产分配",
        "key": "equity_target",
        "label": "权益资产目标",
        "kind": "number",
        "default": 0.6
      },
      {
        "minimum": 0,
        "maximum": 0.5,
        "step": 0.005,
        "options": null,
        "help": null,
        "key": "rebalance_band",
        "label": "再平衡偏离阈值",
        "kind": "number",
        "default": 0
      },
      {
        "minimum": 0,
        "maximum": 0.05,
        "step": 0.0005,
        "options": null,
        "help": null,
        "key": "min_trade_rate",
        "label": "最小调仓比例",
        "kind": "number",
        "default": 0.001
      }
    ]
  }
]
