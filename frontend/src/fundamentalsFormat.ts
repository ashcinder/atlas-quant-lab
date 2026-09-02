import type { FundamentalMetric } from './types'

const compactNumber = new Intl.NumberFormat('zh-CN', {
  notation: 'compact',
  maximumFractionDigits: 2,
})

const decimalNumber = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 2,
})

export function formatFundamentalMetric(metric: FundamentalMetric): string {
  if (metric.value === null || !Number.isFinite(metric.value)) return '—'
  if (metric.unit === 'percent') return `${(metric.value * 100).toFixed(2)}%`
  if (metric.unit === 'ratio') return `${decimalNumber.format(metric.value)}×`
  const formatted = Math.abs(metric.value) >= 100_000
    ? compactNumber.format(metric.value)
    : decimalNumber.format(metric.value)
  if (metric.unit === 'currency' && metric.currency) return `${metric.currency} ${formatted}`
  return formatted
}
