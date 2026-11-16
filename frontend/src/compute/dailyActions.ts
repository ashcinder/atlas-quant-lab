import type { Bar } from '../types'

export interface DailyActionData {
  version: string
  base_factor: number
  factors: { time: number; factor: number }[]
  dividends: { time: number; payable: number; per_share: number }[]
  splits: { time: number; ratio: number }[]
}

export function researchBars(bars: Bar[], data: DailyActionData): Bar[] {
  let factor = data.base_factor
  let index = 0
  return bars.map(bar => {
    while (data.factors[index]?.time <= bar.time) factor = data.factors[index++].factor
    const scale = factor / data.base_factor
    return { ...bar, open: bar.open * scale, high: bar.high * scale, low: bar.low * scale, close: bar.close * scale }
  })
}

export function dailyActionLedger(data: DailyActionData) {
  const events = [
    ...data.dividends.map(row => ({ ...row, kind: 'dividend' as const })),
    ...data.splits.map(row => ({ ...row, kind: 'split' as const })),
  ].sort((a, b) => a.time - b.time || a.kind.localeCompare(b.kind))
  let index = 0
  let receivables: { due: number; amount: number }[] = []
  return (time: number, quantity: number, cost: number) => {
    while (events[index]?.time <= time) {
      const event = events[index++]
      if (event.kind === 'dividend') {
        receivables.push({ due: event.payable, amount: quantity * event.per_share })
        cost = Math.max(cost - event.per_share, 0)
      } else {
        quantity *= event.ratio
        cost /= event.ratio
      }
    }
    let paid = 0
    let outstanding = 0
    receivables = receivables.filter(({ due, amount }) => {
      if (due <= time) {
        paid += amount
        return false
      }
      outstanding += amount
      return true
    })
    return { quantity, cost, paid, outstanding }
  }
}
