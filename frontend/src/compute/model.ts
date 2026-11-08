import type { Asset, Bar, Adjustment, Interval } from '../types'
export interface MarketInput {
  asset: Asset
  bars: Bar[]
  source: string
  source_note?: string | null
  adjustment?: Adjustment | string
  interval?: Interval
  fetched_at?: number
  last_bar_time?: number
  is_stale?: boolean
}
export interface AIStage {
  stage: 'market' | 'entry' | 'buy_size' | 'sell_size' | 'risk' | 'execution'
  enabled: boolean
  authority: 'advisory' | 'veto' | 'reduce_only'
  instructions: string
  timeout_ms: number
  max_reduction: number
}
export interface AIReviewInput {
  stage: AIStage['stage']
  side: 'buy' | 'sell'
  closed_bars: Bar[]
  signal: string
  scale: number
  authority: AIStage['authority']
  instructions: string
  timeout_ms: number
}
export interface ComputeContext {
  progress?: (fraction: number, message: string) => void
  cancelled?: () => boolean
  aiReview?: (input: AIReviewInput) => Promise<{ scale: number; status: string }>
  includeDetails?: boolean
}
export function checkCancelled(context?: ComputeContext): void {
  if (context?.cancelled?.()) throw new Error('计算已取消')
}
export type MetricMap = Record<string, number | null>
export type RegimeMap = Record<string, MetricMap>
