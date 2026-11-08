import { describe, expect, it } from 'vitest'
import type { Bar } from '../types'
import type { MarketInput } from './model'
import { runPortfolio } from './portfolio'

const day = 86400
const start = Date.UTC(2024, 9, 1) / 1000
const symbols = ['AAA', 'BBB', 'CCC']
const strategies = ['all_weather', 'risk_parity', 'sixty_forty']
const frequencies = ['monthly', 'quarterly', 'yearly']
const currencies = ['CNY', 'USD', 'USDT']
const costProfiles = [
  { commission_rate: 0, slippage_rate: 0, spread_rate: 0 },
  { commission_rate: 0.006, slippage_rate: 0.003, spread_rate: 0.004 },
]
const limits = [
  { cash_buffer: 0, max_asset_weight: 1, volatility_target: null },
  { cash_buffer: 0.2, max_asset_weight: 0.4, volatility_target: 0.05 },
]
const windows = [{ first: 0, last: 399 }, { first: 46, last: 287 }]
const cases = strategies.flatMap(strategy_id => frequencies.flatMap(rebalance => currencies.flatMap(base_currency =>
  costProfiles.flatMap((cost, c) => limits.flatMap((limit, l) => windows.map((window, w) => ({
    name: [strategy_id, rebalance, base_currency, 'cost'+c, 'risk'+l, 'window'+w].join(' / '),
    request: { strategy_id, rebalance, base_currency, ...cost, ...limit }, window,
  })))))))

function input(currency: string): MarketInput[] {
  const scale = currency === 'CNY' ? 7 : 1
  return symbols.map((symbol, index) => ({
    asset: { symbol, name: symbol, asset_class: index === 2 ? 'crypto' : 'equity', exchange: 'TEST', currency, timezone: 'UTC', tags: [] },
    source: 'synthetic',
    source_note: '历史汇率换算 · deterministic sample',
    bars: Array.from({ length: 400 }, (_, i) => {
      const open = scale * (100 + i * (index + 1) / 25 + 12 * Math.sin(i / (7 + index * 4)))
      const close = open * (1 + 0.015 * Math.sin(i + index))
      return { time: start + day * i, open, close, high: Math.max(open, close), low: Math.min(open, close), volume: 10000 }
    }).filter((_, i) => index === 2 || i % (index === 0 ? 11 : 13) !== 0),
  }))
}
const assets = symbols.map((symbol, i) => ({ symbol, weight: [0.6, 0.3, 0.1][i] }))
const iso = (time: number) => new Date(time * 1000).toISOString()
const closeEnough = (actual: number, expected: number) => {
  expect(Math.abs(actual - expected)).toBeLessThanOrEqual(1e-8 * Math.max(1, Math.abs(expected)))
}

describe('joint portfolio boundary matrix with independent trade accounting', () => {
  it.each(cases)('$name', ({ request, window }) => {
    const markets = input(request.base_currency)
    const bySymbol = new Map(markets.map(market => [market.asset.symbol, new Map(market.bars.map(bar => [bar.time, bar]))]))
    const capital = 100000
    const result = runPortfolio({
      ...request, assets, interval: '1d', initial_capital: capital,
      start: iso(start + day * window.first), end: iso(start + day * window.last),
    }, markets)
    const days = Array.from({ length: window.last - window.first + 1 }, (_, i) => start + day * (window.first + i))
      .filter(time => symbols.every(symbol => bySymbol.get(symbol)!.has(time)))
    expect(result.equity.map(point => point.time)).toEqual(days)
    expect(result.valuation_currency).toBe(request.base_currency)
    const periods = new Map<string, number>()
    for (const time of days) {
      const date = new Date(time * 1000)
      const month = date.getUTCMonth()
      const key = String(date.getUTCFullYear()) + (request.rebalance === 'yearly' ? '' :
        request.rebalance === 'monthly' ? '-' + month : '-' + Math.floor(month / 3))
      if (!periods.has(key)) periods.set(key, time)
    }
    expect(result.weight_history.map(point => point.time)).toEqual([...periods.values()])
    const permitted = new Set(periods.values())
    const quantities = new Map(symbols.map(symbol => [symbol, 0]))
    let cash = capital
    let fees = 0
    let offset = 0
    for (const point of result.equity) {
      let hadBuy = false
      while (result.trades[offset]?.time === point.time) {
        const trade = result.trades[offset++]
        const symbol = trade.reason.split(' ')[0]
        const mid = bySymbol.get(symbol)!.get(trade.time)!.open
        const sign = trade.side === 'buy' ? 1 : -1
        expect(permitted.has(trade.time)).toBe(true)
        expect(hadBuy && sign < 0).toBe(false)
        if (sign > 0) hadBuy = true
        const price = mid * (1 + sign * (request.slippage_rate + request.spread_rate / 2))
        const fee = trade.quantity * price * request.commission_rate
        fees += fee
        closeEnough(trade.slippage_cost, trade.quantity * Math.abs(price - mid))
        cash -= sign * trade.quantity * price + fee
        quantities.set(symbol, quantities.get(symbol)! + sign * trade.quantity)
        closeEnough(trade.price, price)
        closeEnough(trade.fee, fee)
        closeEnough(trade.cash_after, cash)
        closeEnough(trade.position_after, quantities.get(symbol)!)
        expect(cash).toBeGreaterThanOrEqual(-1e-8)
        expect(quantities.get(symbol)!).toBeGreaterThanOrEqual(-1e-8)
      }
      const held = symbols.reduce((sum, symbol) => sum + quantities.get(symbol)! * bySymbol.get(symbol)!.get(point.time)!.close, 0)
      closeEnough(point.equity, held + cash)
    }
    expect(offset).toBe(result.trades.length)
    expect(offset).toBeGreaterThan(0)
    expect(result.metrics.fees_paid).not.toBeNull()
    closeEnough(result.metrics.fees_paid!, fees)
  })

  it('rejects 59 common sessions and accepts exactly 60', () => {
    const markets = input('USD')
    const present = markets[0].bars.filter(bar => markets.slice(1).every(m => m.bars.some(other => other.time === bar.time)))
    const restricted = (count: number) => {
      const times = new Set(present.slice(0, count).map((bar: Bar) => bar.time))
      return markets.map(m => ({ ...m, bars: m.bars.filter(bar => times.has(bar.time)) }))
    }
    const request = { assets, base_currency: 'USD', interval: '1d' }
    expect(() => runPortfolio(request, restricted(59))).toThrow(/59.*60/)
    expect(runPortfolio(request, restricted(60)).equity).toHaveLength(60)
  })

  it('rejects a reversed time range and infeasible cash and position settings', () => {
    const markets = input('USD')
    const request = { assets, base_currency: 'USD', interval: '1d' }
    expect(() => runPortfolio({ ...request, start: iso(start + day), end: iso(start) }, markets)).toThrow(/start/)
    expect(() => runPortfolio({ ...request, cash_buffer: 0.5 }, markets)).toThrow(/现金缓冲/)
    expect(() => runPortfolio({ ...request, cash_buffer: 0.1, max_asset_weight: 0.29 }, markets)).toThrow(/max_asset_weight/)
  })
})
