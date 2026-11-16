import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { comparisonMarket } from './client'
import { createPortablePlan } from './portablePython'
import { compareBacktests, type ComparisonRow } from './compareBacktests'
import type { BacktestResult } from '../types'
import { request } from '../request'

vi.mock('../api', () => ({ api: { runBacktest: vi.fn() } }))
vi.mock('../request', { spy: true })
vi.mock('./client', () => ({ comparisonMarket: vi.fn() }))
vi.mock('./portablePython', () => ({ createPortablePlan: vi.fn() }))
const bars = Array.from({ length: 40 }, (_, i) => ({ time: 1700000000 + i * 60, open: 100, high: 102, low: 99, close: 101, volume: 100000 }))
const plan = { dataset_id: 'frozen', source_sha256: 'source', name: 'strategy', start: bars[0].time, end: bars.at(-1)!.time, targets: bars.map(() => .5) }
const result = { run_id: 'run', metrics: { total_return: .1, max_drawdown: -.02 } } as unknown as BacktestResult

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(comparisonMarket).mockResolvedValue({ bars, datasetId: 'frozen', source: 'fixture' })
  vi.mocked(createPortablePlan).mockResolvedValue(plan)
  vi.mocked(api.runBacktest).mockResolvedValue(result)
})

it('generates one signal plan and passes the same plan and dates to three actual engine APIs', async () => {
  const rows = await compareBacktests({ strategy_id: 'python_portable', portable_python: 'def target(c): return .5', data_source: 'huggingface' }, new AbortController().signal, vi.fn(), 'owner')
  expect(createPortablePlan).toHaveBeenCalledTimes(1)
  expect(rows.map(row => row.status)).toEqual(['completed', 'completed', 'completed'])
  expect(vi.mocked(api.runBacktest).mock.calls.map(([payload]) => payload.backtest_engine)).toEqual(['atlas', 'vnpy', 'rqalpha'])
  for (const [payload, , owner] of vi.mocked(api.runBacktest).mock.calls) {
    expect(payload.portable_plan).toBe(plan)
    expect(payload.start).toBe(new Date(bars[0].time * 1000).toISOString())
    expect(payload.end).toBe(new Date(bars.at(-1)!.time * 1000).toISOString())
    expect(owner).toBe('owner')
  }
})

it('preserves successful reports when another engine fails', async () => {
  vi.mocked(api.runBacktest).mockRejectedValueOnce(new Error('Trine rejected input'))
  const rows = await compareBacktests({ python_source: 'source' }, new AbortController().signal, vi.fn())
  expect(rows.map(row => row.status)).toEqual(['error', 'completed', 'completed'])
  expect(rows[0].error).toBe('Trine rejected input')
})

it('uses one corporate-action version and one adjusted signal plan for automatic A-share daily comparisons', async () => {
  const actions = {
    version: 'a'.repeat(64), base_factor: 1, factors: [{ time: bars[1].time, factor: 2 }], dividends: [], splits: [],
  }
  vi.mocked(comparisonMarket).mockResolvedValue({ bars, datasetId: 'frozen', source: 'rqalpha-sina' })
  vi.mocked(request).mockResolvedValue(actions)
  const rows = await compareBacktests({
    symbol: '600036.SS', asset_class: 'equity', interval: '1d', data_source: 'auto',
    strategy_id: 'python_portable', portable_python: 'def target(c): return .5',
  }, new AbortController().signal, vi.fn())

  expect(rows.map(row => row.status)).toEqual(['completed', 'completed', 'completed'])
  expect(request).toHaveBeenCalledOnce()
  expect(createPortablePlan).toHaveBeenCalledOnce()
  const adjustedBars = vi.mocked(createPortablePlan).mock.calls[0][1]
  expect(adjustedBars.slice(0, 2).map(bar => bar.close)).toEqual([101, 202])
  const calls = vi.mocked(api.runBacktest).mock.calls.map(([payload]) => payload)
  expect(calls.every(payload => payload.portable_plan === plan && payload.daily_action_version === actions.version)).toBe(true)
  expect(calls.map(payload => payload.daily_actions)).toEqual([actions, undefined, undefined])
})

it('runs a ZIP signal generator once before the framework calls', async () => {
  const generator = vi.fn().mockResolvedValue({ source: 'ZIP digest', plan })
  await compareBacktests({}, new AbortController().signal, vi.fn(), 'owner', generator)
  expect(generator).toHaveBeenCalledTimes(1)
  expect(createPortablePlan).not.toHaveBeenCalled()
  expect(api.runBacktest).toHaveBeenCalledTimes(3)
})

it('reports preparation errors for all frameworks without leaving pending rows', async () => {
  vi.mocked(comparisonMarket).mockRejectedValue(new Error('No dataset'))
  const rows = await compareBacktests({}, new AbortController().signal, vi.fn())
  expect(rows.every(row => row.status === 'error' && row.error === 'No dataset')).toBe(true)
  expect(api.runBacktest).not.toHaveBeenCalled()
})

it('cancels pending engines while retaining completed output', async () => {
  const controller = new AbortController()
  const updates: ComparisonRow[][] = []
  vi.mocked(api.runBacktest).mockImplementationOnce(async () => { controller.abort(); return result })
  const rows = await compareBacktests({}, controller.signal, state => updates.push(state))
  expect(rows.map(row => row.status)).toEqual(['completed', 'cancelled', 'cancelled'])
  expect(api.runBacktest).toHaveBeenCalledTimes(1)
})

it('reuses the checked plan in independent matching on the same historical dataset', async () => {
  const { prepareComparison, runPreparedComparison } = await import('./compareBacktests')
  const generator = vi.fn().mockResolvedValue({ source: 'ZIP digest', plan })
  const signal = new AbortController().signal
  const checked = await prepareComparison({ data_source: 'huggingface', execution_model: 'native' }, signal, generator)
  expect(checked).toMatchObject({ datasetId: 'frozen', method: 'native', barCount: 40 })
  expect(api.runBacktest).not.toHaveBeenCalled()
  await runPreparedComparison(checked, signal, vi.fn(), 'owner', [
    { engine: 'atlas', state: 'ready' },
    { engine: 'vnpy', state: 'ready' },
    { engine: 'rqalpha', state: 'unavailable', reason: 'bundle missing' },
  ]).then(rows => expect(rows[2]).toMatchObject({ status: 'skipped', error: 'bundle missing' }))
  expect(generator).toHaveBeenCalledOnce()
  expect(comparisonMarket).toHaveBeenCalledOnce()
  expect(vi.mocked(api.runBacktest).mock.calls.map(([payload]) =>
    [payload.backtest_engine, payload.execution_model, payload.portable_plan])).toEqual([
    ['atlas', 'native', plan], ['vnpy', 'native', plan],
  ])
})

it('checks existing market support before scheduling external engines', async () => {
  const { checkComparisonEngines } = await import('./compareBacktests')
  const checks = checkComparisonEngines({ asset_class: 'crypto', symbol: 'BTC-USD', interval: '1d', data_source: 'binance' })
  expect(checks.map(check => check.state)).toEqual(['ready', 'unknown', 'unavailable'])
  expect(checks[2].reason).toContain('沪深 A 股')
})
