import { describe, expect, it } from 'vitest'
import { formatNumber, formatPercent } from './format'

describe('financial formatting', () => {
  it('formats positive and negative percentages consistently', () => {
    expect(formatPercent(0.1234)).toBe('+12.34%')
    expect(formatPercent(-0.08)).toBe('-8.00%')
    expect(formatPercent(null)).toBe('—')
  })

  it('does not expose NaN in the interface', () => {
    expect(formatNumber(Number.NaN)).toBe('—')
    expect(formatNumber(1234.567, 2)).toContain('1,234.57')
  })
})
