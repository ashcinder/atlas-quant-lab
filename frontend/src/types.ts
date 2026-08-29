export type Interval = '15m' | '1h' | '4h' | '1d' | '1wk'
export type DataSource = 'auto' | 'yahoo' | 'binance' | 'demo'
export type Adjustment = 'auto' | 'raw' | 'forward' | 'backward'
export type BaseCurrency = 'CNY' | 'USD' | 'USDT'

export interface Asset {
  symbol: string
  name: string
  asset_class: string
  exchange: string
  currency: string
  timezone: string
  tags: string[]
}

export interface Bar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface IndicatorPoint {
  time: number
  value: number | null
}

export interface MarketData {
  asset: Asset
  interval: Interval
  adjustment: string
  source: string
  source_note: string | null
  fetched_at: number
  last_bar_time: number
  cache_hit: boolean
  is_stale: boolean
  bars: Bar[]
  indicators: Record<string, IndicatorPoint[]>
}

export interface StrategyParameter {
  key: string
  label: string
  kind: 'number' | 'integer' | 'select' | 'boolean'
  default: number | string | boolean
  minimum: number | null
  maximum: number | null
  step: number | null
  options: Array<{ label: string; value: string }> | null
  help: string | null
}

export interface Strategy {
  id: string
  name: string
  category: string
  description: string
  suitable_for: string
  risk_level: '低' | '中' | '高' | '极高'
  mode: 'single' | 'portfolio'
  parameters: StrategyParameter[]
}

export interface Trade {
  id: number
  time: number
  side: 'buy' | 'sell'
  reason: string
  price: number
  quantity: number
  notional: number
  fee: number
  slippage_cost: number
  position_after: number
  cash_after: number
  realized_pnl: number | null
}

export interface EquityPoint {
  time: number
  equity: number
  benchmark: number
  drawdown: number
  exposure: number
}

export interface BacktestResult {
  run_id: string
  created_at: string
  asset: Asset
  interval: Interval
  strategy: Strategy
  data_source: string
  source_note: string | null
  bars: Bar[]
  indicators: Record<string, IndicatorPoint[]>
  trades: Trade[]
  equity: EquityPoint[]
  metrics: Record<string, number | null>
  regime_metrics: Record<string, Record<string, number | null>>
  warnings: string[]
}

export interface PortfolioResult {
  run_id: string
  created_at: string
  strategy: Strategy
  assets: Asset[]
  data_source: string
  weights: Record<string, number>
  weight_history: Array<{ time: number; weights: Record<string, number> }>
  equity: EquityPoint[]
  trades: Trade[]
  metrics: Record<string, number | null>
  risk_contribution: Record<string, number>
  correlation: Record<string, Record<string, number>>
  warnings: string[]
}

export interface RunSummary {
  id: string
  mode: 'single' | 'portfolio'
  strategy_id: string
  symbol: string
  created_at: string
  total_return: number | null
  max_drawdown: number | null
  status: string
}

export interface IndicatorSpec {
  field: 'open' | 'high' | 'low' | 'close' | 'volume' | 'sma' | 'ema' | 'rsi' | 'macd' | 'macd_signal' | 'boll_upper' | 'boll_lower' | 'roc'
  period?: number | null
}

export interface RuleNode {
  kind: 'condition' | 'group'
  combinator?: 'all' | 'any' | null
  children?: RuleNode[]
  left?: IndicatorSpec | null
  operator?: 'gt' | 'gte' | 'lt' | 'lte' | 'crosses_above' | 'crosses_below' | null
  right_indicator?: IndicatorSpec | null
  right_value?: number | null
}

export interface CustomStrategySpec {
  id: string
  name: string
  description: string
  entry: RuleNode
  exit: RuleNode
  target_position: number
}

export interface CustomStrategyRecord {
  id: string
  spec: CustomStrategySpec
  created_at: string
  updated_at: string
}

export interface ResearchExperiment {
  strategy_id: string
  base_params: Record<string, number | string | boolean>
  parameter_grid: Record<string, Array<number | boolean>>
}

export interface ResearchCandidate {
  strategy_id: string
  params: Record<string, number | string | boolean>
  train_metrics: Record<string, number | null>
  test_metrics: Record<string, number | null>
  objective_train: number | null
  objective_test: number | null
  sharpe_degradation: number | null
  adjusted_p_value: number | null
  robustness_score: number
  rank: number
  warnings: string[]
}

export interface WalkForwardWindow {
  strategy_id: string
  train_start: number
  train_end: number
  test_start: number
  test_end: number
  params: Record<string, number | string | boolean>
  train_sharpe: number | null
  test_sharpe: number | null
  test_return: number | null
  trades: number
}

export interface ResearchResult {
  job_id: string
  symbol: string
  interval: Interval
  objective: string
  data_source: string
  tested_combinations: number
  candidates: ResearchCandidate[]
  walk_forward: WalkForwardWindow[]
  summary: Record<string, number | boolean | null>
  warnings: string[]
  created_at: string
}

export interface ResearchJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  message: string
  result: ResearchResult | null
  error: string | null
  created_at: string
  updated_at: string
}

export type AlertKind = 'price_above' | 'price_below' | 'price_crosses_above' | 'price_crosses_below' | 'change_pct_above' | 'rsi_below' | 'rsi_above' | 'macd_crosses_above' | 'macd_crosses_below'

export interface AlertRuleInput {
  name: string
  symbol: string
  asset_class: string
  interval: Interval
  data_source: DataSource
  kind: AlertKind
  threshold: number | null
  cooldown_minutes: number
  enabled: boolean
}

export interface AlertRule extends AlertRuleInput {
  id: string
  last_value: number | null
  last_triggered_at: string | null
  last_evaluated_at: string | null
  created_at: string
  updated_at: string
}

export interface AlertNotification {
  id: string
  alert_id: string
  title: string
  message: string
  triggered_at: string
  value: number
  read: boolean
}

export type QuantAgentType = 'ai_agent' | 'traditional'
export type QuantCategory = 'stock_selection' | 'timing' | 'allocation' | 'multi_factor' | 'arbitrage'
export type QuantRisk = 'low' | 'medium' | 'high' | 'extreme'
export type QuantReportType = 'backtest' | 'live'

export interface QuantCurvePoint {
  time: number
  return: number
  benchmark_return: number
}

export interface QuantReport {
  id: string
  report_type: QuantReportType
  period_start: string
  period_end: string
  metrics: Record<string, number>
  public_curve: QuantCurvePoint[]
  decision_count: number
  decision_merkle_root: string
  market_data_hash: string
  previous_receipt_hash: string | null
  receipt_hash: string
  attestation_key_id: string
  attestation_signature: string
  external_proof: { proof_type: string; proof_hash: string; verifier: string; verifier_reference?: string | null } | null
  chain_tx_hash: string | null
  chain_status: 'not_anchored' | 'submitted' | 'confirmed' | 'failed' | 'unreachable'
  chain_block_number: number | null
  score: number
  created_at: string
  receipt_integrity_valid: boolean
  public_curve_integrity_valid: boolean | null
  privacy: { source_hidden: boolean; decisions_hidden: boolean; raw_equity_discarded: boolean }
}

export interface QuantAgent {
  id: string
  rank: number
  name: string
  developer_alias: string
  agent_type: QuantAgentType
  category: QuantCategory
  asset_classes: string[]
  description: string
  risk_level: QuantRisk
  monthly_price: number
  price_currency: 'CNY' | 'USDT'
  strategy_commitment: string
  status: string
  is_demo: boolean
  subscriber_count: number
  latest_report: QuantReport | null
  reports?: QuantReport[]
  created_at: string
  updated_at: string
}

export interface QuantJudgeOverview {
  agents: number
  reports: number
  live_reports: number
  chain_confirmed_reports: number
  active_subscriptions: number
  median_score: number
  attestation: { algorithm: string; key_id: string; public_key: string }
  privacy_model: string
}

export interface QuantChainStatus {
  connected: boolean
  compatible: boolean
  rpc_url: string
  chain_id: number | null
  block_number: number | null
  error: string | null
  expected_chain_id: number
  read_only_source_policy: boolean
  submission_policy: string
}

export interface QuantVerification {
  report_id: string
  receipt_hash: string
  receipt_hash_valid: boolean
  attestation_signature_valid: boolean
  record_integrity_valid: boolean
  public_curve_integrity_valid: boolean | null
  calculation_verified: boolean
  decision_merkle_root: string
  strategy_commitment: string
  external_proof_verified: boolean
  chain: { status: string; transaction_hash: string | null; block_number: number | null; error?: string; payload_matches?: boolean }
  proof_scope: string[]
  limitations: string[]
}

export interface QuantSubscription {
  id: string
  agent_id: string
  agent_name: string
  investor_alias: string
  billing_cycle: 'monthly' | 'quarterly' | 'yearly'
  amount: number
  currency: string
  status: string
  payment_mode: string
  started_at: string
  expires_at: string
}
