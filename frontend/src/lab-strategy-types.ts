import type { StrategyLanguage } from './components/strategy-languages'
import type { Adjustment, DataSource, Interval, RunSummary } from './types'

export const labOwnerHeaders = (owner: string) => ({ 'X-Atlas-Lab-Owner': owner })

export interface LabBacktestSettings {
  symbol: string | null
  asset_class: string | null
  data_source: DataSource
  interval: Interval
  start: string | null
  end: string | null
  initial_capital: number
  adjustment: Adjustment
  commission_rate: number
  slippage_rate: number
  spread_rate: number
  max_position: number
  max_participation_rate: number
}

export type LabMultiEngine = 'atlas_portfolio' | 'rqalpha'

export const labMultiEngineLabels: Record<LabMultiEngine, string> = {
  atlas_portfolio: 'Atlas 自研引擎', rqalpha: 'RQAlpha 公开版',
}

export interface LabMultiSettings {
  engine_id?: LabMultiEngine
  symbols: string[]
  interval: '1d' | '15m'
  start: string | null
  end: string | null
  initial_capital: number
  commission_rate: number
  slippage_rate: number
  max_position: number
  max_participation_rate: number
  parameters?: Record<string, string | number | boolean>
  universe?: string | null
  benchmark?: '000300.SS' | '000905.SS' | '000001.SS' | null
}

export type LabStrategyKind = 'single_bounded' | 'multi_python'

interface LabDraftSource {
  name: string
  source: string
}

export interface LabSingleDraft extends LabDraftSource {
  kind?: 'single_bounded'
  language: StrategyLanguage
  settings: LabBacktestSettings
}

export interface LabMultiDraft extends LabDraftSource {
  kind: 'multi_python'
  language: 'python'
  settings: LabMultiSettings
  package_b64?: string | null
}

export type LabDraft = LabSingleDraft | LabMultiDraft

export interface LabStrategySummary {
  kind?: LabStrategyKind
  id: string
  name: string
  language: StrategyLanguage
  revision: number
  updated_at: string
}

export type LabStrategy = LabDraft & LabStrategySummary

export interface LabRunSummary extends RunSummary {
  source_sha256: string
  settings: LabBacktestSettings
}

export interface LabMultiTrade {
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  fee: number
  time: number
  reason?: string
  name?: string | null
  position_effect?: string | null
  commission?: number
  tax?: number
  order_id?: string
  exec_id?: string
}

export type LabReportTable = 'trades' | 'positions' | 'accounts' | 'logs'
export type LabReportExport = LabReportTable | 'annual' | 'snapshot'
export type LabReportRow = Record<string, string | number | null>

export interface LabReportMetric {
  key: string
  label: string
  value: number | null
  format: 'percent' | 'number'
  precision: number
  definition: string
  source: string
  reason: string | null
}

export interface LabReportPoint {
  time: number
  equity: number
  net_value: number
  strategy_return: number
  benchmark_return: number | null
  excess_return: number | null
  daily_pnl: number
  buy_amount: number
  sell_amount: number
}

export interface LabAnnualReturn {
  year: number
  start: number
  end: number
  partial: boolean
  strategy: number | null
  benchmark: number | null
}

export interface LabBacktestReport {
  schema_version: 'atlas.rqalpha.report/v1'
  benchmark: { symbol: string; name: string } | null
  conventions: Record<string, string | number | null>
  metrics: LabReportMetric[]
  series: LabReportPoint[]
  annual_returns: LabAnnualReturn[]
  drawdown: { start: number; end: number; value: number } | null
  tables: Record<LabReportTable, { count: number; recorded: boolean }>
  logs_truncated: boolean
  performance: { enabled: boolean }
}

export interface LabReportQuery {
  offset?: number
  limit?: number
  start?: string
  end?: string
  symbol?: string
  side?: 'buy' | 'sell' | ''
  levels?: string
  descending?: boolean
  sort?: string
}

export interface LabReportPage {
  rows: LabReportRow[]
  total: number
  unfiltered_total: number
  offset: number
  limit: number
  recorded: boolean
  logs_truncated: boolean
}

export interface LabMultiResult {
  equity: Array<{ time: number; equity: number; cash: number; market_value?: number; net_value?: number;
    frozen_cash?: number; dividend_receivable?: number; cash_liabilities?: number;
    cash_liabilities_interest?: number; pending_cash_flow?: number }>
  trades: LabMultiTrade[]
  trades_complete?: boolean
  report?: LabBacktestReport
  initial_capital: number
  final_equity: number
  total_return: number
  max_drawdown?: number
  positions?: LabMultiPosition[]
  engine_version?: string
  matching_type?: string
  native_metrics?: Record<string, unknown>
}

export interface LabMultiJob {
  id: string
  strategy_id: string
  revision: number
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: number | null
  error: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  elapsed_seconds?: number | null
  name?: string
  settings: LabMultiSettings
  source_sha256: string
  dataset_sha256?: string
  engine_id?: LabMultiEngine
  engine_version?: string
  matching_type?: string
  result?: LabMultiResult | null
  report?: LabBacktestReport | null
}

export interface LabMultiCoverage {
  available: boolean
  reason: string | null
  start: number | null
  end: number | null
  dataset_sha256?: string
}

export interface LabMultiPosition {
  symbol: string
  dividend_receivable?: number | null
  quantity: number
  sellable: number | null
  mark_price: number | null
  market_value: number | null
  weight: number | null
}

export interface LabMultiSimulation {
  id: string
  release_id: string
  name: string
  account_id: string
  valuation_complete: boolean
  status: 'active' | 'paused' | 'stopped' | 'waiting'
  settings: LabMultiSettings
  updated_at: string
  error: string | null
  latest: {
    time: number
    equity: number
    cash: number
    positions: LabMultiPosition[]
    trades: LabMultiTrade[]
  } | null
}

export const defaultMultiSettings: LabMultiSettings = {
  symbols: [], interval: '1d', start: null, end: null, initial_capital: 1_000_000,
  commission_rate: 0.001, slippage_rate: 0.0005, max_position: 0.95, max_participation_rate: 0.01,
}

export const multiJobStatus: Record<LabMultiJob['status'], string> = {
  queued: '排队中', running: '运行中', succeeded: '已完成', failed: '失败', cancelled: '已取消',
}
export const multiJobActive = (job: LabMultiJob | null | undefined) => job?.status === 'queued' || job?.status === 'running'
export const multiJobEngine = (job: LabMultiJob): LabMultiEngine => job.engine_id ?? job.settings.engine_id ?? 'atlas_portfolio'
