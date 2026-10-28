import type { StrategyRun } from '../types'

const labels = { not_enabled: '未启用', normal: '已记录期间未发现超限', deviation: '发现仓位偏离', insufficient_data: '不可评估' }
export default function BehaviorMonitor({ run }: { run: StrategyRun }) {
  const check = run.behavior_check
  if (!check) return <section className="behavior-monitor"><h5>策略行为偏离监测</h5><p>未启用。创建平台模拟运行时可声明监测仓位上限。</p></section>
  const points = check.points ?? [], limit = (check.limit_bps ?? 0) / 10000
  const max = Math.max(1, limit, ...points.map(p => Number(p.ratio)))
  const start = points[0]?.time ?? 0, end = points.at(-1)?.time ?? start
  const x = (time: number) => 45 + (time - start) / Math.max(1, end - start) * 680
  const y = (ratio: number) => 165 - ratio / max * 130
  return <section className="behavior-monitor" aria-label="策略行为偏离监测"><h5>策略行为偏离监测 · 仓位约束</h5><p role="status"><strong>{labels[check.status]}</strong>{check.limit_bps != null && ` · 声明上限 ${check.limit_bps / 100}%`}</p><p>{check.reason}</p>{check.latest_ratio != null && <p>最近仓位 {(Number(check.latest_ratio) * 100).toFixed(2)}% · 最高 {(Number(check.peak_ratio) * 100).toFixed(2)}% · 超限 {check.deviation_count} 个估值点</p>}{check.first_deviation_at != null && <p>首次偏离：{new Date(check.first_deviation_at * 1000).toLocaleString('zh-CN')}</p>}{points.length > 0 && <svg viewBox="0 0 780 205" role="img" aria-label="实际仓位与声明上限曲线"><line className="behavior-limit" x1="45" x2="725" y1={y(limit)} y2={y(limit)} /><text x="45" y={Math.max(16, y(limit) - 8)} fill="currentColor" fontSize="12">上限 {limit * 100}%</text><path className="behavior-series" d={points.map((p, i) => `${i ? 'L' : 'M'}${x(p.time)},${y(Number(p.ratio))}`).join(' ')} />{points.map(p => <circle key={p.time} cx={x(p.time)} cy={y(Number(p.ratio))} r="3" className={Number(p.ratio) > limit ? 'behavior-breach' : undefined} fill="#087e78"><title>{new Date(p.time * 1000).toLocaleString('zh-CN')} · {(Number(p.ratio) * 100).toFixed(2)}%</title></circle>)}<text x="45" y="195" fill="currentColor" fontSize="12">{new Date(start * 1000).toLocaleDateString('zh-CN')}</text><text x="725" y="195" textAnchor="end" fill="currentColor" fontSize="12">{new Date(end * 1000).toLocaleDateString('zh-CN')}</text></svg>}<p>覆盖 {check.snapshot_count} 个已记录估值点。仅为普通规则计算，不代表完整账户、基金风格漂移或 ZKP 证明；不自动暂停或下单。</p></section>
}
