import { useId, useState } from 'react'
import type { StrategyRun } from '../types'

export default function TradingEquityChart({ run }: { run: StrategyRun }) {
  const gradient = useId().replace(/:/g, '')
  const [cursor, setCursor] = useState<number | null>(null)
  const points = run.curve ?? []
  if (!points.length) return <div className="trade-chart-empty"><strong>等待第一个净值快照</strong><span>收到有效信号并完成估值后，曲线将在这里更新。</span></div>
  const values = points.map(point => Number(point.equity))
  const low = Math.min(...values); const high = Math.max(...values)
  const padding = Math.max((high - low) * .18, Math.abs(high) * .00002, .000001)
  const bottom = low - padding; const top = high + padding
  const start = points[0].bar_time; const end = points.at(-1)!.bar_time
  const x = (index: number) => end === start ? 360 : 22 + (points[index].bar_time - start) / (end - start) * 662
  const y = (value: number) => 210 - (value - bottom) / (top - bottom) * 182
  const selected = Math.min(cursor ?? points.length - 1, points.length - 1)
  const path = values.map((value, index) => `${index ? 'L' : 'M'}${x(index)},${y(value)}`).join(' ')
  const amount = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
  const date = (index: number) => new Date(points[index].bar_time * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const change = Number(points[selected].return_rate) * 100
  return <div className="trade-chart-card">
    <div className="trade-chart-readout"><div><span>{cursor === null ? '最新策略净值' : '历史策略净值'}</span><strong>{amount(values[selected])}<small>{run.currency ?? 'USDT'}</small></strong></div><div><b className={change >= 0 ? 'positive' : 'negative'}>{change >= 0 ? '+' : ''}{change.toFixed(2)}%</b><time>{date(selected)}</time></div></div>
    <svg viewBox="0 0 780 248" role="img" aria-label={`${run.strategy_name} 净值曲线，共 ${points.length} 个快照`} aria-description="使用左右键查看历史" tabIndex={0}
      onPointerLeave={() => setCursor(null)} onBlur={() => setCursor(null)}
      onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); setCursor(Math.max(0, Math.min(points.length - 1, selected + (event.key === 'ArrowLeft' ? -1 : 1)))) } }}
      onPointerMove={event => { const rect = event.currentTarget.getBoundingClientRect(); const scale = Math.min(rect.width / 780, rect.height / 248); const offset = (rect.width - 780 * scale) / 2; const target = Math.max(0, Math.min(1, ((event.clientX - rect.left - offset) / scale - 22) / 662)); const stamp = start + target * (end - start); let nearest = 0; points.forEach((point, index) => { if (Math.abs(point.bar_time - stamp) < Math.abs(points[nearest].bar_time - stamp)) nearest = index }); setCursor(nearest) }}>
      <defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity=".17" /><stop offset="100%" stopColor="currentColor" stopOpacity=".01" /></linearGradient></defs>
      {[0, 1, 2, 3].map(tick => { const value = bottom + (top - bottom) * tick / 3; return <g key={tick}><line x1="22" x2="684" y1={y(value)} y2={y(value)} className="trade-chart-grid" /><text x="700" y={y(value) + 4}>{amount(value)}</text></g> })}
      {points.length > 1 && <path d={`${path} L${x(points.length - 1)},210 L${x(0)},210 Z`} fill={`url(#${gradient})`} />}
      <path d={path} className="trade-chart-line" />
      <line x1={x(selected)} x2={x(selected)} y1="22" y2="210" className="trade-chart-crosshair" />
      <circle cx={x(selected)} cy={y(values[selected])} r="4" fill="currentColor" stroke="var(--panel)" strokeWidth="2" />
      <text x="22" y="239">{date(0)}</text><text x="684" y="239" textAnchor="end">{date(points.length - 1)}</text>
    </svg>
    <div className="trade-chart-caption"><span><i />策略净值 · {points.length} 个快照</span><span>已计入成交费用 · 非连续行情</span></div>
  </div>
}
