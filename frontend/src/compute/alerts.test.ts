import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AlertKind, AlertNotification, AlertRule, MarketData } from '../types'
import parityFixture from '../tests/fixtures/alerts-parity.json'
import { evaluateAlertObservation, evaluateBrowserAlerts } from './alerts'
import { request } from '../request'
import { assertComputeIdentity, getComputeIdentity, getMarket } from './client'

vi.mock('../request', () => ({ request: vi.fn() }))
vi.mock('./client', () => ({ getMarket: vi.fn(), getComputeIdentity: vi.fn(), assertComputeIdentity: vi.fn() }))
const rule = (values: Partial<AlertRule> = {}): AlertRule => ({ id: 'alert-a', name: 'price', symbol: 'SPY', asset_class: 'etf', interval: '1d', data_source: 'auto', kind: 'price_crosses_above', threshold: 100, cooldown_minutes: 60, enabled: true, last_value: null, last_evaluated_at: null, last_triggered_at: null, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z', ...values })
function market(close = 110): MarketData {
  const bars = Array.from({ length: 30 }, (_, i) => ({ time: 1704067200 + i * 86400, open: 100, high: Math.max(110, close), low: 80, close: i === 29 ? close : 100, volume: 1000 }))
  return { asset: { symbol: 'SPY', name: 'SPY', asset_class: 'etf', currency: 'USD', exchange: 'NYSE', timezone: 'UTC', tags: [] }, interval: '1d', adjustment: 'auto', source: 'fixture', source_note: null, bars, indicators: { rsi14: [{ time: bars[28].time, value: 55 }, { time: bars[29].time, value: null }], macd: [{ time: bars[28].time, value: 3 }, { time: bars[29].time, value: 9 }], macd_signal: [{ time: bars[28].time, value: 2 }, { time: bars[29].time, value: null }] }, fetched_at: bars[29].time, last_bar_time: bars[29].time, cache_hit: true, is_stale: false }
}
const notification: AlertNotification = { id: 'notice-1', alert_id: 'alert-a', title: 'price', message: 'server message', triggered_at: '2026-11-05T00:00:00Z', value: 110, read: false }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(getComputeIdentity).mockResolvedValue({ owner_id: 'owner-a', session_scope: 'session-a' })
  vi.mocked(assertComputeIdentity).mockResolvedValue()
  vi.mocked(getMarket).mockResolvedValue(market())
})

describe('browser alert observation rules', () => {
  it('matches 108 Python AlertMonitor observations at crossing boundaries and initial states', () => {
    for (const fixture of parityFixture) {
      const data = market(fixture.kind.startsWith('price') ? fixture.target : fixture.kind === 'change_pct_above' ? 100 * (1 + fixture.target) : 110)
      data.indicators = { rsi14: [{ time: 1, value: fixture.target }], macd: [{ time: 1, value: fixture.target }], macd_signal: [{ time: 1, value: 0 }] }
      const actual = evaluateAlertObservation(rule({ kind: fixture.kind as AlertKind, threshold: fixture.threshold, last_value: fixture.last_value }), data)
      expect(actual?.triggered, JSON.stringify(fixture)).toBe(fixture.expected.triggered)
      expect(actual?.value, JSON.stringify(fixture)).toBeCloseTo(fixture.expected.value, 12)
    }
  })
  for (const kind of ['price_above', 'price_crosses_above'] as const) it(`${kind} matches first observation and strict upward crossing`, () => {
    expect(evaluateAlertObservation(rule({ kind }), market())).toEqual({ value: 110, triggered: true })
    expect(evaluateAlertObservation(rule({ kind, last_value: 110 }), market())).toEqual({ value: 110, triggered: false })
    expect(evaluateAlertObservation(rule({ kind, last_value: 100 }), market())).toEqual({ value: 110, triggered: true })
    expect(evaluateAlertObservation(rule({ kind }), market(100))).toEqual({ value: 100, triggered: false })
  })
  for (const kind of ['price_below', 'price_crosses_below'] as const) it(`${kind} matches first observation and strict downward crossing`, () => {
    expect(evaluateAlertObservation(rule({ kind }), market(90))).toEqual({ value: 90, triggered: true })
    expect(evaluateAlertObservation(rule({ kind, last_value: 90 }), market(90))).toEqual({ value: 90, triggered: false })
    expect(evaluateAlertObservation(rule({ kind, last_value: 100 }), market(90))).toEqual({ value: 90, triggered: true })
    expect(evaluateAlertObservation(rule({ kind }), market(100))).toEqual({ value: 100, triggered: false })
  })
  it('uses inclusive change threshold and strict previous-threshold transition', () => {
    const data = market(110)
    const threshold = data.bars.at(-1)!.close / data.bars.at(-2)!.close - 1
    expect(evaluateAlertObservation(rule({ kind: 'change_pct_above', threshold }), data)?.triggered).toBe(true)
    expect(evaluateAlertObservation(rule({ kind: 'change_pct_above', threshold, last_value: threshold }), data)?.triggered).toBe(false)
  })
  it('drops null RSI values and aligns MACD and signal on their latest common timestamp', () => {
    expect(evaluateAlertObservation(rule({ kind: 'rsi_above', threshold: 50 }), market())).toEqual({ value: 55, triggered: true })
    expect(evaluateAlertObservation(rule({ kind: 'rsi_below', threshold: 60, last_value: 65 }), market())).toEqual({ value: 55, triggered: true })
    expect(evaluateAlertObservation(rule({ kind: 'macd_crosses_above' }), market())).toEqual({ value: 1, triggered: true })
    expect(evaluateAlertObservation(rule({ kind: 'macd_crosses_below', last_value: 0 }), { ...market(), indicators: { macd: [{ time: 1, value: -2 }], macd_signal: [{ time: 1, value: 0 }] } })).toEqual({ value: -2, triggered: true })
  })
  it('does not invent observations for empty indicators, missing prices, insufficient bars or disabled rules', () => {
    expect(evaluateAlertObservation(rule({ kind: 'rsi_above' }), { ...market(), indicators: { rsi14: [{ time: 1, value: null }] } })).toBeNull()
    expect(evaluateAlertObservation(rule({ kind: 'macd_crosses_above' }), { ...market(), indicators: { macd: [{ time: 1, value: 2 }], macd_signal: [{ time: 2, value: 1 }] } })).toBeNull()
    expect(evaluateAlertObservation(rule(), { ...market(), bars: market().bars.slice(0, 29) })).toBeNull()
    expect(evaluateAlertObservation(rule({ enabled: false }), market())).toBeNull()
  })
})

describe('browser alert evaluation persistence', () => {
  it('fetches one market per group and leaves cooldown decision and messages to the server', async () => {
    const active = rule({ last_triggered_at: new Date().toISOString(), cooldown_minutes: 1440 })
    vi.mocked(request).mockImplementation(async path => {
      if (path === '/alerts') return [active, rule({ id: 'alert-b', threshold: 120 }), rule({ id: 'disabled', enabled: false })] as never
      return { notification: path.includes('alert-a') ? notification : null } as never
    })
    expect(await evaluateBrowserAlerts()).toEqual([notification])
    expect(getMarket).toHaveBeenCalledTimes(1)
    expect(getMarket).toHaveBeenCalledWith('SPY', 'etf', '1d', 'auto', 'auto')
    expect(request).toHaveBeenCalledWith('/compute/alerts/alert-a/observations', { method: 'POST', body: JSON.stringify({ value: 110, triggered: true }) })
    expect(request).toHaveBeenCalledWith('/compute/alerts/alert-b/observations', { method: 'POST', body: JSON.stringify({ value: 110, triggered: false }) })
    expect(vi.mocked(request).mock.calls.some(([path]) => path === '/alerts/evaluate')).toBe(false)
  })
  it('submits no observation for unavailable/short data and never calls server evaluation', async () => {
    vi.mocked(request).mockResolvedValue([rule()])
    vi.mocked(getMarket).mockResolvedValue({ ...market(), bars: market().bars.slice(0, 29) })
    expect(await evaluateBrowserAlerts()).toEqual([])
    expect(request).toHaveBeenCalledTimes(1)
    vi.mocked(getMarket).mockRejectedValue(new Error('Dataset preparing'))
    expect(await evaluateBrowserAlerts()).toEqual([])
    expect(request).toHaveBeenCalledTimes(2)
  })
  it('stops when identity changes while market data is loading', async () => {
    vi.mocked(request).mockResolvedValue([rule()])
    vi.mocked(getMarket).mockImplementation(async () => {
      vi.mocked(assertComputeIdentity).mockRejectedValue(new Error('登录身份已变化'))
      return market()
    })
    await expect(evaluateBrowserAlerts()).rejects.toThrow('登录身份已变化')
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('does not manufacture a notification when the server suppresses it', async () => {
    vi.mocked(request).mockImplementation(async path => path === '/alerts' ? [rule()] as never : { notification: null } as never)
    expect(await evaluateBrowserAlerts()).toEqual([])
  })
  it('does not run simultaneous evaluations and clears its lock after errors', async () => {
    let resolve!: (rules: AlertRule[]) => void
    vi.mocked(request).mockImplementationOnce(() => new Promise<AlertRule[]>(done => { resolve = done }) as never)
    const first = evaluateBrowserAlerts()
    await Promise.resolve()
    expect(await evaluateBrowserAlerts()).toEqual([])
    resolve([])
    expect(await first).toEqual([])
    vi.mocked(request).mockRejectedValueOnce(new Error('unavailable'))
    await expect(evaluateBrowserAlerts()).rejects.toThrow('unavailable')
    vi.mocked(request).mockResolvedValueOnce([])
    expect(await evaluateBrowserAlerts()).toEqual([])
  })
})
