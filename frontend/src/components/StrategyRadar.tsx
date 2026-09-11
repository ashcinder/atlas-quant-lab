import { useState } from 'react'
import type { QuantAgent } from '../types'
import './strategy-radar.css'
import { strategyScores } from './strategy-scores'

const labels = ['收益能力', '回撤控制', '风险回报', '波动稳健', '收益回撤比', '观察长度']
const rules = ['年化收益 −20% → 0，+40% → 100', '最大回撤 50% → 0，0% → 100', 'Sharpe −1 → 0，3 → 100', '年化波动 80% → 0，0% → 100', '年化收益 / 最大回撤：0 → 0，3 → 100', '报告观察期 0 天 → 0，365 天 → 100']
const point = (i: number, score: number, radius = 88) => {
  const angle = (i * 60 - 90) * Math.PI / 180
  return [150 + Math.cos(angle) * radius * score / 100, 128 + Math.sin(angle) * radius * score / 100]
}

export default function StrategyRadar({ agent, peers }: { agent: QuantAgent; peers: QuantAgent[] }) {
  const [comparison, setComparison] = useState('')
  const other = peers.find((item) => item.id === comparison && item.id !== agent.id)
  const scores = strategyScores(agent.latest_report)
  const otherScores = strategyScores(other?.latest_report ?? null)
  const series = [{ values: scores, name: agent.name, color: '#087e78' }, ...(other ? [{ values: otherScores, name: other.name, color: '#b56528' }] : [])]
  const report = agent.latest_report
  const comparable = !other || (report?.report_type === other.latest_report?.report_type && report?.period_start === other.latest_report?.period_start && report?.period_end === other.latest_report?.period_end)
  return <section className="strategy-radar" aria-label="策略六维评分">
    <header><div><small>STRATEGY PROFILE · V1</small><h3>六维策略画像</h3></div><span>{agent.is_demo ? '演示样本' : '报告指标换算'}</span></header>
    <label className="radar-compare">叠加比较<select aria-label="选择对比策略" value={other?.id ?? ''} onChange={(event) => setComparison(event.target.value)}><option value="">仅查看当前策略</option>{peers.filter((item) => item.id !== agent.id).map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_demo ? ' · 演示' : ''}</option>)}</select></label>
    <svg viewBox="0 0 300 260" role="img" aria-label={`${agent.name}六维评分图，详细分数见下方表格`}>
      {[25, 50, 75, 100].map((score) => <polygon key={score} points={labels.map((_, i) => point(i, score).join(',')).join(' ')} fill="none" stroke="#d6e2e5" />)}
      {labels.map((label, i) => { const [x, y] = point(i, 100, 113); return <g key={label}><line x1="150" y1="128" x2={point(i, 100)[0]} y2={point(i, 100)[1]} stroke="#d6e2e5" /><text x={x} y={y} textAnchor="middle" dominantBaseline="middle">{label}</text></g> })}
      {series.map((item) => <g key={item.name}>{item.values.every((v) => v !== null) ? <polygon points={item.values.map((v, i) => point(i, v!).join(',')).join(' ')} fill={item.color} fillOpacity=".10" stroke={item.color} strokeWidth="2" /> : null}{item.values.map((v, i) => v === null ? null : <circle key={i} cx={point(i, v)[0]} cy={point(i, v)[1]} r="3" fill={item.color} />)}</g>)}
    </svg>
    <div className="radar-legend">{series.map((item) => <span key={item.name}><i style={{ background: item.color }} />{item.name}</span>)}</div>
    <table><thead><tr><th>维度 / 100</th><th>当前策略</th>{other ? <th>对比策略</th> : null}</tr></thead><tbody>{labels.map((label, i) => <tr key={label}><th>{label}</th><td>{scores[i] ?? '待评估'}</td>{other ? <td>{otherScores[i] ?? '待评估'}</td> : null}</tr>)}</tbody></table>
    {!comparable ? <p>两份报告的期间或类型不同，分数仅供并列查看，不代表同条件排名。</p> : null}
    <details><summary>评分口径与数据范围</summary><p>固定线性刻度，超出范围截断至 0–100；缺失指标不补零、不连成完整面积。观察长度只表示时间覆盖，不表示盈利能力。六维分数不是已验证业绩或未来收益承诺。</p><ul>{rules.map((rule, i) => <li key={rule}>{labels[i]}：{rule}</li>)}</ul><p>零回撤时收益回撤比待评估。报告：{report ? `${report.report_type === 'backtest' ? '回测' : '实盘类'} · ${report.period_start} — ${report.period_end}` : '尚未提交'}。证据是否通过验证，请查看下方证据护照。</p></details>
  </section>
}
