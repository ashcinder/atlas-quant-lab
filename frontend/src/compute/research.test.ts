import { describe, expect, it } from 'vitest'
import fixture from '../tests/fixtures/research-parity.json'
import type { MarketInput } from './model'
import { candidateWarnings, runResearch } from './research'

function parity(actual: unknown, expected: unknown, path = ''): void {
  if (typeof expected === 'number') expect(Math.abs(Number(actual) - expected), path).toBeLessThanOrEqual(1e-8 * Math.max(1, Math.abs(expected)))
  else if (Array.isArray(expected)) {
    expect((actual as unknown[]).length, path).toBe(expected.length)
    expected.forEach((value, i) => parity((actual as unknown[])[i], value, `${path}[${i}]`))
  } else if (expected !== null && typeof expected === 'object') {
    for (const [key, value] of Object.entries(expected)) if (key !== 'created_at') parity((actual as Record<string, unknown>)[key], value, `${path}.${key}`)
  } else expect(actual, path).toEqual(expected)
}
const market = fixture.market as MarketInput

describe('browser research parity against Python fixed fixtures', () => {
  for (const test of fixture.cases) it(test.name, async () => {
    const progress: number[] = []
    const result = await runResearch(test.request, market, { jobId: 'fixture-job', progress: value => progress.push(value) })
    parity(result, test.result)
    expect(result.candidates.filter(candidate => Object.keys(candidate.test_metrics).length)).toHaveLength(2)
    expect(progress.at(-1)).toBe(1)
  })
  it('does not use holdout prices to choose training parameters', async () => {
    const request = { ...fixture.cases[0].request, walk_forward: { enabled: false } }
    const original = await runResearch(request, market)
    const changed = { ...market, bars: market.bars.map((bar, i) => i < 288 ? bar : { ...bar, close: bar.close * (1 + (i - 288) / 10), high: bar.high * 10, open: bar.open * 2 }) }
    const recalculated = await runResearch(request, changed)
    const params = (result: typeof original) => result.candidates.filter(candidate => Object.keys(candidate.test_metrics).length).map(candidate => ({ strategy: candidate.strategy_id, params: candidate.params })).sort((a, b) => a.strategy.localeCompare(b.strategy))
    expect(params(recalculated)).toEqual(params(original))
  })
  it('rejects insufficient data, invalid grid budgets, AI stages and cancellation', async () => {
    const request = fixture.cases[0].request
    await expect(runResearch(request, { ...market, bars: market.bars.slice(0, 159) })).rejects.toThrow('160')
    await expect(runResearch({ ...request, experiments: [{ strategy_id: 'sma_cross', parameter_grid: { fast: [] } }] }, market)).rejects.toThrow('1–20')
    await expect(runResearch({ ...request, execution_pipeline: { ai_stages: [{ enabled: true }] } }, market)).rejects.toThrow('关闭 AI')
    await expect(runResearch(request, market, { cancelled: () => true })).rejects.toThrow('计算已取消')
  })
  it('retains warning and Bonferroni rules', () => {
    const result = candidateWarnings({ sharpe: 4 }, { sharpe: 0.5, round_trip_count: 2, trade_count: 4, return_p_value: 0.04 }, 10, 2)
    expect(result.adjustedP).toBe(0.4)
    expect(result.degradation).toBe(0.875)
    expect(result.warnings).toHaveLength(5)
  })
})
