import { useState } from 'react'
import type { QuantAgent } from '../types'
import './strategy-radar.css'
import { strategyDimensions, strategyScores } from './strategy-scores'

const labels = ['收益能力', '风险收益效率', '风险控制与稳定性', '市场适应性', '回测实盘一致性', '策略纯度']
const radarLabels = ['收益能力', '风险收益', '风险控制', '市场适应', '回测实盘', '策略纯度']
const rules = ['年化收益 −20% → 0，+40% → 100', 'Sharpe −1 → 0，3 → 100', '最大回撤 50% → 0，0% → 100', '牛、熊、震荡阶段年化超额收益等权平均，−20% → 0，+20% → 100', '需要同策略、同口径和重叠区间的回测与实盘数据', '需要风格声明、基线和可核对的持仓观测']
const point = (i: number, score: number, radius = 88) => {
  const angle = (i * 60 - 90) * Math.PI / 180
  return [150 + Math.cos(angle) * radius * score / 100, 128 + Math.sin(angle) * radius * score / 100]
}

export default function StrategyRadar({ agent, peers }: { agent: QuantAgent; peers: QuantAgent[] }) {
  const [comparison, setComparison] = useState('')
  const other = peers.find((item) => item.id === comparison && item.id !== agent.id)
  const scores = strategyScores(agent.latest_report)
  const dimensions = strategyDimensions(agent.latest_report)
  const otherScores = strategyScores(other?.latest_report ?? null)
  const series = [{ values: scores, name: agent.name, color: '#087e78' }, ...(other ? [{ values: otherScores, name: other.name, color: '#b56528' }] : [])]
  const report = agent.latest_report
  const comparable = !other || (report?.report_type === other.latest_report?.report_type && report?.period_start === other.latest_report?.period_start && report?.period_end === other.latest_report?.period_end)
  return <section className="strategy-radar" aria-label="策略六维评价">
    <header><div><small>STRATEGY EVALUATION · V1</small><h3>六维评价</h3></div><span>{agent.is_demo ? '演示样本' : '后端规则计算'}</span></header>
    <label className="radar-compare">叠加比较<select aria-label="选择对比策略" value={other?.id ?? ''} onChange={(event) => setComparison(event.target.value)}><option value="">仅查看当前策略</option>{peers.filter((item) => item.id !== agent.id).map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_demo ? ' · 演示' : ''}</option>)}</select></label>
    <svg viewBox="0 0 300 260" role="img" aria-label={`${agent.name}六维评价图，详细状态见下方表格`}>
      {[25, 50, 75, 100].map((score) => <polygon key={score} points={labels.map((_, i) => point(i, score).join(',')).join(' ')} fill="none" stroke="#d6e2e5" />)}
      {radarLabels.map((label, i) => { const [x, y] = point(i, 100, 113); return <g key={label}><line x1="150" y1="128" x2={point(i, 100)[0]} y2={point(i, 100)[1]} stroke="#d6e2e5" /><text x={x} y={y} textAnchor="middle" dominantBaseline="middle">{label}</text></g> })}
      {series.map((item) => <g key={item.name}>{item.values.every((v) => v !== null) ? <polygon points={item.values.map((v, i) => point(i, v!).join(',')).join(' ')} fill={item.color} fillOpacity=".10" stroke={item.color} strokeWidth="2" /> : item.values.map((v,i)=>{const next=(i+1)%6;const n=item.values[next];return v===null||n===null?null:<line data-radar-segment key={i} x1={point(i,v)[0]} y1={point(i,v)[1]} x2={point(next,n)[0]} y2={point(next,n)[1]} stroke={item.color} strokeWidth="2"/>})}{item.values.map((v, i) => v === null ? null : <circle key={i} cx={point(i, v)[0]} cy={point(i, v)[1]} r="3" fill={item.color} />)}</g>)}
    </svg>
    <div className="radar-legend">{series.map((item) => <span key={item.name}><i style={{ background: item.color }} />{item.name}</span>)}</div>
    <table><thead><tr><th>维度 / 100</th><th>当前策略</th>{other ? <th>对比策略</th> : null}</tr></thead><tbody>{labels.map((label, i) => <tr key={label}><th>{label}</th><td title={dimensions[i]?.reason ?? undefined}>{scores[i] ?? '不可评估'}{scores[i] == null && dimensions[i]?.reason ? <small>{dimensions[i]?.reason}</small> : null}</td>{other ? <td>{otherScores[i] ?? '不可评估'}</td> : null}</tr>)}</tbody></table>
    {!comparable ? <p>两份报告的期间或类型不同，分数仅供并列查看，不代表同条件排名。</p> : null}
    <details><summary>评价口径与数据范围</summary><p>由后端 evaluation_v1 统一计算，固定线性刻度超出范围截断至 0–100。缺失维度不补零、不绘制完整面积，也不计算六维总分。分数不是已验证业绩或未来收益承诺。</p><ul>{rules.map((rule, i) => <li key={rule}>{labels[i]}：{rule}</li>)}</ul><p>当前公开报告没有原始市场阶段、配对实盘与风格观测时，只能评价前三维。报告：{report ? `${report.report_type === 'backtest' ? '回测' : '实盘类'} · ${report.period_start} — ${report.period_end}` : '尚未提交'}。证据是否通过验证，请查看下方证据护照。</p></details>
  </section>
}
