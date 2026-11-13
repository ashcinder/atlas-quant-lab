import { describe, expect, it } from 'vitest'
import { supportsMinuteBars } from './marketSupport'
import { periodsPerYear } from './compute/metrics'

describe('Chinese equity minute support', () => {
  it('offers minute bars for Chinese equities and crypto, without exposing unsupported US stocks', () => {
    expect(supportsMinuteBars({asset_class:'equity',exchange:'SSE'})).toBe(true)
    expect(supportsMinuteBars({asset_class:'equity',exchange:'SZSE'})).toBe(true)
    expect(supportsMinuteBars({asset_class:'crypto',exchange:'CRYPTO'})).toBe(true)
    expect(supportsMinuteBars({asset_class:'equity',exchange:'NASDAQ'})).toBe(false)
    expect(supportsMinuteBars(null)).toBe(false)
  })
  it('annualizes using four Chinese trading hours while preserving US and crypto factors', () => {
    expect(periodsPerYear('1m','equity','SSE')).toBe(252*240)
    expect(periodsPerYear('5m','equity','SZSE')).toBe(252*48)
    expect(periodsPerYear('15m','equity','SSE')).toBe(252*16)
    expect(periodsPerYear('1h','equity','NASDAQ')).toBe(252*6.5)
    expect(periodsPerYear('1m','crypto','CRYPTO')).toBe(365*1440)
  })
})
