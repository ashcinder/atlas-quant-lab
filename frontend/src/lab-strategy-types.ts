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

export interface LabDraft {
  name: string
  language: StrategyLanguage
  source: string
  settings: LabBacktestSettings
}

export interface LabStrategySummary {
  id: string
  name: string
  language: StrategyLanguage
  revision: number
  updated_at: string
}

export interface LabStrategy extends LabDraft, LabStrategySummary {}

export interface LabRunSummary extends RunSummary {
  source_sha256: string
  settings: LabBacktestSettings
}
