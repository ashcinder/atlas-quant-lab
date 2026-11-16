import { describe, expect, it } from 'vitest'
import { dailyActionLedger, researchBars, type DailyActionData } from './dailyActions'

const data: DailyActionData = {
  version: 'test',
  base_factor: 1,
  factors: [{ time: 2, factor: 100 / 49 }],
  dividends: [{ time: 2, payable: 4, per_share: 2 }],
  splits: [{ time: 2, ratio: 2 }],
}

describe('daily corporate actions', () => {
  it('adjusts signals from the ex date while preserving the raw tape', () => {
    const bars = [100, 49, 49].map((close, index) => ({
      time: index + 1, open: close, high: close, low: close, close, volume: 100,
    }))
    expect(researchBars(bars, data).map(bar => bar.close)).toEqual([100, 100, 100])
    expect(bars[1].close).toBe(49)
  })

  it('credits dividends on pay date even if the holding was sold, and applies the split once', () => {
    const apply = dailyActionLedger(data)
    const ex = apply(2, 800, 100)
    expect(ex).toEqual({ quantity: 1600, cost: 49, paid: 0, outstanding: 1600 })
    expect(ex.quantity * 49 + ex.outstanding).toBe(800 * 100)
    expect(apply(3, 0, 0)).toEqual({ quantity: 0, cost: 0, paid: 0, outstanding: 1600 })
    expect(apply(4, 0, 0)).toEqual({ quantity: 0, cost: 0, paid: 1600, outstanding: 0 })
    expect(apply(5, 0, 0).paid).toBe(0)
  })
})
