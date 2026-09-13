import { describe, expect, it } from 'vitest'
import type { QuantReport } from '../types'
import { strategyScores } from './strategy-scores'

const report = (metrics: Record<string, number>) => ({ metrics, period_start: '2025-01-01', period_end: '2026-01-01' }) as QuantReport

describe('six dimensional score calibration', () => {
  it('does not fabricate scores for missing reports or metrics', () => {
    expect(strategyScores(null)).toEqual([null, null, null, null, null, null])
    expect(strategyScores(report({}))).toEqual([null, null, null, null, null, 100])
  })
  it('uses consistent scales and caps outliers', () => {
    expect(strategyScores(report({ annualized_return: .1, max_drawdown: -.1, sharpe: 1, annualized_volatility: .2 }))).toEqual([50, 80, 50, 75, 33, 100])
    expect(strategyScores(report({ annualized_return: 10, max_drawdown: 0, sharpe: 100, annualized_volatility: 2 }))).toEqual([100, 100, 100, 0, null, 100])
  })
  it('does not award a full observation score for invalid dates', () => {
    const value = report({ annualized_return: Number.NaN })
    value.period_end = 'invalid'
    expect(strategyScores(value)[0]).toBeNull()
    expect(strategyScores(value)[5]).toBeNull()
  })
})
