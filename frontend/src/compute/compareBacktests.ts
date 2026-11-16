import { api } from '../api'
import { comparisonMarket } from './client'
import { MarketUnavailableError } from './market'
import { createPortablePlan, type PortablePlan } from './portablePython'
import type { Bar, BacktestResult } from '../types'
import { researchBars, type DailyActionData } from './dailyActions'
import { ApiError, request as apiRequest } from '../request'

export const comparisonEngines = ['atlas', 'vnpy', 'rqalpha'] as const
export type ComparisonEngine = typeof comparisonEngines[number]
export const comparisonLabels = { atlas: 'Trine', vnpy: 'vn.py', rqalpha: 'RQAlpha' }
export type ComparisonMethod = 'unified' | 'native'

export interface ComparisonRow {
  engine: ComparisonEngine
  status: 'pending' | 'running' | 'completed' | 'error' | 'cancelled' | 'skipped'
  result?: BacktestResult
  error?: string
}
export interface ComparisonEngineCheck {
  engine: ComparisonEngine
  version?: string
  state: 'ready' | 'unavailable' | 'unknown'
  reason?: string
}
export interface PreparedComparison {
  request: Record<string, unknown>
  datasetId: string
  barCount: number
  from: number
  to: number
  method: ComparisonMethod
}
export type PlanFactory = (bars: Bar[], datasetId: string, signal: AbortSignal) => Promise<{ source: string; plan: PortablePlan }>
type EngineAvailability = Awaited<ReturnType<typeof api.backtestEngines>>

function engineRestriction(engine: ComparisonEngine, payload: Record<string, unknown>) {
  if (engine === 'atlas') return
  const { interval, data_source: source } = payload
  const cn = payload.asset_class === 'equity' && /\.(SS|SZ)$/i.test(String(payload.symbol))
  const cnSource = source === 'auto' || source === 'huggingface'
  if (cn && cnSource && (source === 'huggingface' || interval === '1d')) return
  if (engine === 'vnpy' && payload.symbol === 'BTC-USD' && payload.asset_class === 'crypto' && (source === 'auto' || source === 'binance')) return
  if (engine === 'rqalpha') return '支持沪深 A 股历史快照，或自动来源的日线。'
  return '支持 Binance 的 BTC-USD，或沪深 A 股历史快照及自动来源的日线。'
}

export function checkComparisonEngines(payload: Record<string, unknown>, statuses?: EngineAvailability): ComparisonEngineCheck[] {
  return comparisonEngines.map(engine => {
    const status = statuses?.find(item => item.id === engine)
    const reason = engineRestriction(engine, payload) || (status?.available === false && (status.reason || '当前运行环境尚未就绪。'))
    return reason ? { engine, state: 'unavailable', reason }
      : { engine, state: engine === 'atlas' || status?.available ? 'ready' : 'unknown', version: status?.version }
  })
}

export function comparisonError(reason: unknown, fallback: string) {
  if (!(reason instanceof Error)) return fallback
  const error = reason.message.trim()
  if (error.includes('请定义 target(context)')) return '入口需要提供 target(context)，并为当前标的返回 0 到 1 的目标仓位。'
  if (error.startsWith('PythonError: Traceback')) return error.split('\n').at(-1)?.trim() || fallback
  return error || fallback
}

export async function prepareComparison(payload: Record<string, unknown>, signal: AbortSignal, projectPlan?: PlanFactory): Promise<PreparedComparison> {
  const market = await comparisonMarket(payload, signal)
  if (market.bars.length < 40) throw new MarketUnavailableError('引擎对比至少需要 40 根已发布 K 线，请延长回测区间或更换行情设置。')
  const from = market.bars[0].time
  const to = market.bars.at(-1)!.time
  const method = payload.data_source === 'huggingface' && payload.execution_model !== 'native' ? 'unified' : 'native'
  const request: Record<string, unknown> = { ...payload, start: new Date(from * 1000).toISOString(),
    end: new Date(to * 1000).toISOString(), execution_model: method }
  let signalBars = market.bars
  if (method === 'native' && request.interval === '1d' && market.source === 'rqalpha-sina'
    && request.data_source === 'auto' && (projectPlan || request.strategy_id === 'python_portable')) {
    const query = new URLSearchParams({ symbol: String(request.symbol), start: String(from), end: String(to) })
    try {
      const actions = await apiRequest<DailyActionData>(`/backtests/daily-actions?${query}`, { signal })
      request.daily_action_version = actions.version
      request.daily_actions = actions
      signalBars = researchBars(market.bars, actions)
    } catch (error) {
      if (!(error instanceof ApiError && (
        (error.status === 422 && error.message.includes('未覆盖'))
        || (error.status === 503 && error.message.includes('分红送转数据不可用'))
      ))) throw error
    }
  }
  if (projectPlan) {
    const generated = await projectPlan(signalBars, market.datasetId, signal)
    Object.assign(request, { strategy_id: 'python_portable', python_source: undefined, portable_python: generated.source, portable_plan: generated.plan })
  } else if (request.strategy_id === 'python_portable') {
    request.portable_plan = await createPortablePlan(String(request.portable_python), signalBars, market.datasetId,
      String(request.strategy_name ?? 'Python策略'), (request.params ?? {}) as Record<string, unknown>, signal)
  }
  signal.throwIfAborted()
  return { request, datasetId: market.datasetId, barCount: market.bars.length, from, to, method }
}

export async function runPreparedComparison(
  prepared: PreparedComparison, signal: AbortSignal, update: (rows: ComparisonRow[]) => void,
  owner?: string, checks?: ComparisonEngineCheck[],
): Promise<ComparisonRow[]> {
  const rows: ComparisonRow[] = comparisonEngines.map(engine => {
    const check = checks?.find(item => item.engine === engine)
    return check?.state === 'unavailable' ? { engine, status: 'skipped', error: check.reason } : { engine, status: 'pending' }
  })
  const publish = () => update(rows.map(row => ({ ...row })))
  const { daily_actions, daily_action_version, ...request } = prepared.request
  const useActions = prepared.method === 'native' && daily_action_version
  publish()
  for (const row of rows) {
    if (signal.aborted) break
    if (row.status === 'skipped') continue
    row.status = 'running'
    publish()
    try {
      row.result = await api.runBacktest({ ...request, backtest_engine: row.engine,
        ...(useActions ? { daily_action_version } : {}),
        ...(useActions && row.engine === 'atlas' ? { daily_actions } : {}) }, signal, owner)
      row.status = 'completed'
    } catch (error) {
      row.status = signal.aborted ? 'cancelled' : 'error'
      row.error = signal.aborted ? undefined : comparisonError(error, '回测失败。')
    }
    if (!signal.aborted) publish()
  }
  for (const row of rows) if (row.status === 'pending') row.status = 'cancelled'
  publish()
  return rows
}

export async function compareBacktests(
  payload: Record<string, unknown>, signal: AbortSignal,
  update: (rows: ComparisonRow[]) => void, owner?: string, projectPlan?: PlanFactory, checks?: ComparisonEngineCheck[],
  onPrepared?: (prepared: PreparedComparison) => void,
): Promise<ComparisonRow[]> {
  const unavailable = new Map(checks?.filter(check => check.state === 'unavailable').map(check => [check.engine, check.reason]))
  update(comparisonEngines.map(engine => unavailable.has(engine) ? { engine, status: 'skipped', error: unavailable.get(engine) } : { engine, status: 'pending' }))
  let prepared
  try {
    prepared = await prepareComparison(payload, signal, projectPlan)
  } catch (error) {
    if (!signal.aborted && error instanceof MarketUnavailableError) throw error
    const rows: ComparisonRow[] = comparisonEngines.map(engine => unavailable.has(engine)
      ? { engine, status: 'skipped', error: unavailable.get(engine) }
      : { engine, status: signal.aborted ? 'cancelled' : 'error', error: signal.aborted ? undefined : comparisonError(error, '策略准备失败。') })
    update(rows)
    return rows
  }
  onPrepared?.(prepared)
  return runPreparedComparison(prepared, signal, update, owner, checks)
}
