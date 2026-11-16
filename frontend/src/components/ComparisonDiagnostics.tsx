import { useMemo } from 'react'
import { formatDate, formatNumber, formatPercent } from '../format'
import { comparisonLabels, type ComparisonRow } from '../compute/compareBacktests'
import type { EquityPoint } from '../types'

function equityDifferences(reference: EquityPoint[], other: EquityPoint[]) {
  let first: { time: number; reference: number; other: number } | undefined
  let largest: typeof first
  let previous: { reference: number; other: number } | undefined
  let left = 0
  let right = 0
  while (left < reference.length && right < other.length) {
    const base = reference[left]
    const compared = other[right]
    if (base.time < compared.time) { left += 1; previous = undefined; continue }
    if (compared.time < base.time) { right += 1; previous = undefined; continue }
    if (!first && Math.abs(compared.equity - base.equity) >= 0.01) {
      first = { time: base.time, reference: base.equity, other: compared.equity }
    }
    if (previous && previous.reference > 0 && previous.other > 0) {
      const referenceReturn = base.equity / previous.reference - 1
      const otherReturn = compared.equity / previous.other - 1
      if (!largest || Math.abs(otherReturn - referenceReturn) > Math.abs(largest.other - largest.reference)) {
        largest = { time: base.time, reference: referenceReturn, other: otherReturn }
      }
    }
    previous = { reference: base.equity, other: compared.equity }
    left += 1
    right += 1
  }
  return { first, largest }
}

export function ComparisonDiagnostics({ rows }: { rows: ComparisonRow[] }) {
  const diagnostics = useMemo(() => {
    const base = rows.find(row => row.engine === 'atlas')?.result
    return rows.flatMap(({ engine, result }) => {
      if (!result) return []
      const fees = result.metrics.fees_paid ?? result.trades.reduce((sum, trade) => sum + trade.fee, 0)
      const sameCurrency = (result.valuation_currency ?? result.asset?.currency) === (base?.valuation_currency ?? base?.asset?.currency)
      const exact = !result.bar_count || result.equity.length === result.bar_count
      const baseExact = !base?.bar_count || base.equity.length === base.bar_count
      const difference = engine !== 'atlas' && base?.equity?.length && result.equity?.length && sameCurrency && exact && baseExact
        ? equityDifferences(base.equity, result.equity) : undefined
      return [{ engine, firstFill: result.trades[0], fees, difference }]
    })
  }, [rows])

  if (diagnostics.length < 2) return null
  return <details className="engine-comparison-diagnostics">
    <summary>定位成交与净值差异</summary>
    <p>净值按相同 K 线时间对齐。最大差异比较相邻 K 线的净值变化率。</p>
    <dl>{diagnostics.map(({ engine, firstFill, fees, difference }) => <div key={engine}>
      <dt>{comparisonLabels[engine]}</dt>
      <dd>首次成交 {firstFill ? `${formatDate(firstFill.time)} · ${firstFill.side === 'buy' ? '买入' : '卖出'} ${formatNumber(firstFill.quantity)} @ ${formatNumber(firstFill.price)}` : '—'} · 累计报告费用 {formatNumber(fees)}</dd>
      {difference?.first ? <dd>首次净值差异 {formatDate(difference.first.time)} · Trine {formatNumber(difference.first.reference)}，{comparisonLabels[engine]} {formatNumber(difference.first.other)}</dd> : null}
      {difference?.largest && Math.abs(difference.largest.other - difference.largest.reference) > 1e-8
        ? <dd>单根净值变化差异最大 {formatDate(difference.largest.time)} · Trine {formatPercent(difference.largest.reference)}，{comparisonLabels[engine]} {formatPercent(difference.largest.other)}</dd> : null}
    </div>)}</dl>
  </details>
}
