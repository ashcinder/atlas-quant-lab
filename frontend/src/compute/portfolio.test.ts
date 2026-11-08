import { describe, expect, it } from 'vitest'
import portfolioFixture from '../tests/fixtures/portfolio-parity.json'
import sessionFixture from '../tests/fixtures/portfolio-session-parity.json'
import riskFixture from '../tests/fixtures/risk-parity-optimizer.json'
import type { MarketInput } from './model'
import { constrainedWeights, riskParityWeights, runPortfolio } from './portfolio'

// Tolerances are fixed independently of computed output. Trade sequencing, timestamps,
// side and counts remain exact. Fixed weights use 1e-8 scaled error; SQP risk portfolios
// additionally allow 1e-8 of initial capital (0.001 currency) and 1e-8 of
// initial unit scale (0.00001 units) for finite-difference optimizer propagation.
function parity(actual: unknown, expected: unknown, path = '', riskOptimizer = false): void {
  if (typeof expected === 'number') {
    expect(typeof actual, path).toBe('number')
    const money = /\.(equity|benchmark|notional|cash_after|fees_paid|slippage_cost|fee|expectancy)$/.test(path)
    const quantity = /\.(quantity|position_after)$/.test(path)
    const tolerance = riskOptimizer && money ? 1e-3 : riskOptimizer && quantity ? 1e-5 : 1e-8 * Math.max(1, Math.abs(expected))
    expect(Math.abs(Number(actual) - expected), path).toBeLessThanOrEqual(tolerance)
  } else if (Array.isArray(expected)) {
    expect(Array.isArray(actual), path).toBe(true)
    expect((actual as unknown[]).length, path).toBe(expected.length)
    expected.forEach((value, i) => parity((actual as unknown[])[i], value, `${path}[${i}]`, riskOptimizer))
  } else if (expected !== null && typeof expected === 'object') {
    for (const [key, value] of Object.entries(expected)) {
      if (key === 'created_at' || key === 'run_id') continue
      parity((actual as Record<string, unknown>)[key], value, `${path}.${key}`, riskOptimizer)
    }
  } else expect(actual, path).toEqual(expected)
}
const markets = portfolioFixture.markets as MarketInput[]

describe('browser portfolio parity against Python fixed fixtures', () => {
  for (const fixture of portfolioFixture.cases) it(fixture.name, () => {
    parity(runPortfolio(fixture.request, markets), fixture.result, '', fixture.name === 'risk_parity-2')
  })
  it('aligns provider session dates without aggregating weekly bars again', () => {
    parity(runPortfolio(sessionFixture.request, sessionFixture.markets as MarketInput[]), sessionFixture.result)
  })
  it('matches the SciPy risk-contribution objective optimizer', () => {
    for (const fixture of riskFixture) parity(riskParityWeights(fixture.rows, fixture.symbols, fixture.shrinkage), fixture.expected, `risk[${fixture.shrinkage}]`)
  })
  it('sells before pro-rata buys and is independent of asset input order', () => {
    const fixture = portfolioFixture.cases[0]
    const assets = fixture.request.assets.map((asset, i) => ({ ...asset, weight: [0.3, 0.4, 0.15, 0.075, 0.075][i] }))
    const forward = runPortfolio({ ...fixture.request, assets }, markets)
    const reverse = runPortfolio({ ...fixture.request, assets: [...assets].reverse() }, [...markets].reverse())
    parity(reverse.equity, forward.equity)
    parity(reverse.weights, forward.weights)
    expect(forward.trades.every(trade => trade.cash_after >= -1e-8)).toBe(true)
  })
  it('preserves undefined correlation and fails closed for missing/mixed data', () => {
    const fixture = sessionFixture
    const flat = (fixture.markets as MarketInput[]).map(market => ({ ...market, bars: market.bars.map(bar => ({ ...bar, open: 100, high: 100, low: 100, close: 100 })) }))
    const result = runPortfolio(fixture.request, flat)
    expect(result.correlation.SPY.TLT).toBeNull()
    expect(() => runPortfolio(fixture.request, flat.slice(0, 1))).toThrow('缺少行情')
    expect(() => runPortfolio({ ...fixture.request, base_currency: 'CNY' }, flat)).toThrow('历史汇率')
  })
  it('enforces caps, valid parameters and cancellation without a server fallback', () => {
    expect(constrainedWeights({ A: 0.9, B: 0.1 }, 0.1, 0.6)).toEqual({ A: 0.6, B: 0.30000000000000004 })
    const fixture = portfolioFixture.cases[0]
    expect(() => runPortfolio({ ...fixture.request, params: { unsupported: 1 } }, markets)).toThrow('未知参数')
    expect(() => runPortfolio(fixture.request, markets, { cancelled: () => true })).toThrow('计算已取消')
    expect(() => runPortfolio({ ...fixture.request, assets: [{ symbol: 'SPY' }, { symbol: ' spy ' }] }, markets)).toThrow('重复')
  })
})
