import type { QuantReport } from '../types'

const scale = (value: number | undefined, low: number, high: number) => value === undefined || !Number.isFinite(value) ? null : Math.round(Math.max(0, Math.min(100, (value - low) / (high - low) * 100)))

export function strategyScores(report: QuantReport | null): Array<number | null> {
  if (!report) return Array.from({ length: 6 }, () => null)
  const m = report.metrics
  const drawdown = Number.isFinite(m.max_drawdown) ? Math.abs(m.max_drawdown) : undefined
  const days = (Date.parse(report.period_end) - Date.parse(report.period_start)) / 86400000
  return [scale(m.annualized_return, -.2, .4), scale(drawdown, .5, 0), scale(m.sharpe, -1, 3),
    scale(m.annualized_volatility, .8, 0), scale(drawdown && Number.isFinite(m.annualized_return) ? m.annualized_return / drawdown : undefined, 0, 3),
    days > 0 ? scale(days, 0, 365) : null]
}
