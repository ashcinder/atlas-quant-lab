import { describe, expect, it } from 'vitest'
import { normalizeWeightValues } from './portfolio'

describe('normalizeWeightValues', () => {
  it('preserves proportions and makes displayed tenths sum to exactly 100%', () => {
    const normalized = normalizeWeightValues([0.30, 0.40, 0.15, 0.075, 0.075, 0.10])
    expect(normalized).toEqual([0.273, 0.364, 0.136, 0.068, 0.068, 0.091])
    expect(normalized.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 10)
  })

  it('uses equal weights when all inputs are zero', () => {
    const normalized = normalizeWeightValues([0, 0, 0])
    expect(normalized).toEqual([0.334, 0.333, 0.333])
    expect(normalized.reduce((sum, value) => sum + value, 0)).toBe(1)
  })
})
