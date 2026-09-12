import type { StrategyRun } from '../../types'

export function RuntimeCurveCard({ run }: { run: StrategyRun }) {
  const points = run.curve ?? []
  if (!points.length) return null
  const values = points.map(p => Number(p.equity))
  const low = Math.min(...values); const high = Math.max(...values)
  const span = high - low || 1
  const coords = values.map((v, i) => `${12 + i * 456 / Math.max(1, values.length - 1)},${130 - (v - low) / span * 108}`)
  const format = (n: number) => n.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
  return <article className="runtime-curve-card">
    <header><div><a href={`#/trading?run=${run.id}`}>{run.strategy_name}</a><small>{run.environment === 'platform_sim' ? '平台模拟' : '交易账户'} · {points.length} 个净值快照</small></div><strong>{format(Number(run.equity))} {run.currency}</strong></header>
    <svg viewBox="0 0 480 148" role="img" aria-label={`${run.strategy_name} 实际运行净值曲线`}>
      <line x1="12" y1="130" x2="468" y2="130" stroke="var(--border)" />
      <polygon points={`12,140 ${coords.join(' ')} ${12 + (values.length - 1) * 456 / Math.max(1, values.length - 1)},140`} fill="var(--accent)" opacity=".08" />
      <polyline points={coords.join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <circle cx={coords.at(-1)?.split(',')[0]} cy={coords.at(-1)?.split(',')[1]} r="3" fill="var(--accent)" />
    </svg>
    <footer><span>{new Date(points[0].bar_time * 1000).toLocaleTimeString('zh-CN')}</span><span>区间 {format(low)} – {format(high)}</span><span>{new Date(points.at(-1)!.bar_time * 1000).toLocaleTimeString('zh-CN')}</span></footer>
  </article>
}
