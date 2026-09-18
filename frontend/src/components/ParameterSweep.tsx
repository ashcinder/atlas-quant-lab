import { BacktestPeriod } from './BacktestPeriod'
import { SlidersHorizontal, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { request } from '../request'
import { sweepGrid, type SweepField, type SweepRange } from '../parameterSweep'
import type { BacktestResult } from '../types'
import './parameter-sweep.css'

type Result = { values: Record<string, number>; metrics: BacktestResult['metrics'] }
export function ParameterSweep({ fields, payload, onApply, disabled = false }: { fields: SweepField[]; payload: Record<string, unknown>; onApply: (values: Record<string, number>) => void; disabled?: boolean }) {
  const [ranges, setRanges] = useState<Record<string, SweepRange>>({})
  const [start, setStart] = useState(''), [end, setEnd] = useState('')
  const [results, setResults] = useState<Result[]>([]), [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false), [status, setStatus] = useState(''), [progress, setProgress] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const [snapshot, setSnapshot] = useState('')
  const [period, setPeriod] = useState('')
  const identity = JSON.stringify(payload)
  useEffect(() => () => controller.current?.abort(), [])
  let combinations: Record<string, number>[] = [], validation = ''
  try { combinations = sweepGrid(fields, ranges) } catch (cause) { validation = (cause as Error).message }
  const rangeFor = (field: SweepField): SweepRange => ranges[field.key] ?? { enabled: false, from: String(field.value), to: String(field.value), step: field.integer ? '1' : '0.1' }
  const change = (field: SweepField, patch: Partial<SweepRange>) => setRanges(current => ({ ...current, [field.key]: { ...rangeFor(field), ...patch } }))
  async function run() {
    if (controller.current || disabled) return
    if (validation || (start && !Number.isFinite(Date.parse(start))) || (end && !Number.isFinite(Date.parse(end))) || (start && end && Date.parse(start) >= Date.parse(end))) { setStatus(validation || '请选择有效的历史开始和结束时间'); return }
    const abort = new AbortController(); controller.current = abort; setBusy(true); setResults([]); setErrors([]); setProgress(0)
    setSnapshot(identity); setPeriod(`${start ? start.replace('T', ' ') : '最早行情'} — ${end ? end.replace('T', ' ') : '最新行情'}（本地时间）`)
    const base = structuredClone(payload), grid = combinations
    let completed = 0, failed = 0, barsSnapshot: string | null = null
    try {
      for (const values of grid) {
        if (abort.signal.aborted) break
        setStatus(`正在回测 ${completed + failed + 1} / ${grid.length}`)
        const candidate = structuredClone(base)
        // Paths originate only from the exposed strategy fields.
        for (const [path, value] of Object.entries(values)) {
          const keys = path.split('.'); let target = candidate
          for (const key of keys.slice(0, -1)) target = target[key] as Record<string, unknown>
          target[keys.at(-1)!] = value
        }
        const body = { ...candidate, start: start ? new Date(start).toISOString() : null, end: end ? new Date(end).toISOString() : null, persist: false }
        try {
          const result = await request<BacktestResult>('/backtests', { method: 'POST', body: JSON.stringify(body), signal: abort.signal })
          if (abort.signal.aborted) break
          const data = JSON.stringify(result.bars)
          if (barsSnapshot !== null && data !== barsSnapshot) throw new Error('历史数据发生变化，本组合不参与排名，请重新搜索')
          if (!Number.isFinite(result.metrics.total_return)) throw new Error('收益率无效')
          barsSnapshot = data; completed++
          setResults(current => [...current, { values, metrics: result.metrics }].sort((a, b) => Number(b.metrics.total_return) - Number(a.metrics.total_return)))
        } catch (cause) {
          if (abort.signal.aborted) break
          failed++; setErrors(current => [...current, `${JSON.stringify(values)}：${cause instanceof Error ? cause.message : '回测失败'}`])
        }
        setProgress(completed + failed)
      }
      setStatus(`${abort.signal.aborted ? '已停止，保留已完成结果' : '搜索结束'} · 成功 ${completed} · 失败 ${failed}`)
    } finally { controller.current = null; setBusy(false) }
  }
  const stale = snapshot !== identity
  const percent = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(2)}%`
  return <details className="parameter-sweep"><summary><SlidersHorizontal size={18}/><span><strong>参数优化</strong><small>网格穷举 · 比较历史收益</small></span><ChevronDown size={16}/></summary>
    <p>在指定范围逐个回测，按总收益率排序（最多 100 组）。沿用当前资金、费用与风控；批量搜索不运行 AI 流程。历史最优仅针对本次区间与网格，不代表未来收益。</p>
    <fieldset disabled={busy || disabled}><BacktestPeriod label="优化" start={start} end={end} disabled={busy || disabled} onApply={(start, end) => { setStart(start);setEnd(end) }}/>
    <small>本地时区，提交时转换为 UTC。仅调整勾选参数，其余参数固定。</small>
    <div className="sweep-scroll"><table><thead><tr><th>搜索参数</th><th>起点</th><th>终点</th><th>步长</th></tr></thead><tbody>{fields.map(field => { const range = rangeFor(field); return <tr key={field.key}><td><label><input type="checkbox" checked={range.enabled} onChange={e => change(field, { enabled: e.target.checked })} />{field.label}</label></td>{(['from', 'to', 'step'] as const).map(key => <td key={key}><input aria-label={`${field.label} ${key}`} type="number" step={field.integer ? 1 : 'any'} value={range[key]} onChange={e => change(field, { [key]: e.target.value })} /></td>)}</tr> })}</tbody></table></div>
    <small>{validation || `共 ${combinations.length} 组`}</small><button type="button" disabled={!!validation} onClick={() => void run()}>开始优化</button></fieldset>
    {busy && <><button type="button" onClick={() => controller.current?.abort()}>停止搜索</button><small>停止后不再提交新组合；当前后台回测可能仍会完成。</small></>}<p role="status">{status}{busy ? ` · 已处理 ${progress}` : ''}</p>
    {results.length > 0 && <><p>本次搜索：{period}</p><p>{stale ? '策略或回测配置已修改，请重新搜索后应用参数。' : '排名第一为已成功完成组合中的最高收益。点击应用将更新当前策略参数。'}</p><div className="sweep-scroll"><table><thead><tr><th>排名 / 参数</th><th>收益率</th><th>最大回撤</th><th>Sharpe</th><th>操作</th></tr></thead><tbody>{results.map((row, index) => <tr key={JSON.stringify(row.values)}><td>{index + 1}<small>{JSON.stringify(row.values)}</small></td><td>{percent(row.metrics.total_return)}</td><td>{percent(row.metrics.max_drawdown)}</td><td>{row.metrics.sharpe?.toFixed(2) ?? '—'}</td><td><button type="button" disabled={busy || stale} onClick={() => onApply(row.values)}>应用参数</button></td></tr>)}</tbody></table></div></>}
    {!!errors.length && <details><summary>失败组合（{errors.length}）</summary>{errors.map((error, i) => <p key={i}>{error}</p>)}</details>}
  </details>
}
