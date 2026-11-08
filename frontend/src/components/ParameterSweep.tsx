import { BacktestPeriod } from './BacktestPeriod'
import { SlidersHorizontal, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { formatSweepValue, sweepGrid, type SweepField, type SweepRange } from '../parameterSweep'
import type { BacktestResult } from '../types'
import './parameter-sweep.css'

type Result = { values: Record<string, number>; metrics: BacktestResult['metrics'] }
const rangeLabels = { from: '最小值', to: '最大值', step: '每次增加' }
const describeValues = (values: Record<string, number>, fields: SweepField[]) => Object.entries(values).map(([key, value]) => {
  const field = fields.find(item => item.key === key)
  return `${field?.label ?? '参数'}：${formatSweepValue(field, value)}`
}).join('；')
export function ParameterSweep({ fields, payload, onApply, disabled = false }: { fields: SweepField[]; payload: Record<string, unknown>; onApply: (values: Record<string, number>) => void; disabled?: boolean }) {
  const [ranges, setRanges] = useState<Record<string, SweepRange>>({})
  const [start, setStart] = useState(''), [end, setEnd] = useState('')
  const [results, setResults] = useState<Result[]>([]), [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false), [status, setStatus] = useState(''), [progress, setProgress] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const [snapshot, setSnapshot] = useState('')
  const [period, setPeriod] = useState('')
  const [resultFields, setResultFields] = useState<SweepField[]>([])
  const identity = JSON.stringify(payload)
  useEffect(() => () => controller.current?.abort(), [])
  let combinations: Record<string, number>[] = [], validation = ''
  try { combinations = sweepGrid(fields, ranges) } catch (cause) { validation = (cause as Error).message }
  const rangeFor = (field: SweepField): SweepRange => ranges[field.key] ?? { enabled: false, from: String(field.value * (field.scale ?? 1)), to: String(field.value * (field.scale ?? 1)), step: field.scale === 100 ? '10' : field.integer ? '1' : '0.1' }
  const preview = (field: SweepField, range: SweepRange) => {
    if (!range.enabled) return ''
    try {
      const values = sweepGrid([field], { [field.key]: range })
      return `${values.slice(0, 4).map(row => formatSweepValue(field, row[field.key])).join('、')}${values.length > 4 ? '…' : ''}`
    } catch { return '' }
  }
  const change = (field: SweepField, patch: Partial<SweepRange>) => setRanges(current => ({ ...current, [field.key]: { ...rangeFor(field), ...patch } }))
  async function run() {
    if (controller.current || disabled) return
    if (validation || (start && !Number.isFinite(Date.parse(start))) || (end && !Number.isFinite(Date.parse(end))) || (start && end && Date.parse(start) >= Date.parse(end))) { setStatus(validation || '请选择有效的历史开始和结束时间'); return }
    const abort = new AbortController(); controller.current = abort; setBusy(true); setResults([]); setErrors([]); setProgress(0)
    setSnapshot(identity); setResultFields(fields); setPeriod(`${start ? start.replace('T', ' ') : '最早行情'} — ${end ? end.replace('T', ' ') : '最新行情'}（本地时间）`)
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
          const result = await api.runBacktest(body,abort.signal)
          if (abort.signal.aborted) break
          const data = JSON.stringify(result.bars)
          if (barsSnapshot !== null && data !== barsSnapshot) throw new Error('行情数据已变化，这组不计入排名，请重新比较')
          if (!Number.isFinite(result.metrics.total_return)) throw new Error('收益率无效')
          barsSnapshot = data; completed++
          setResults(current => [...current, { values, metrics: result.metrics }].sort((a, b) => Number(b.metrics.total_return) - Number(a.metrics.total_return)))
        } catch (cause) {
          if (abort.signal.aborted) break
          failed++; setErrors(current => [...current, `${describeValues(values, fields)}：${cause instanceof Error ? cause.message : '回测失败'}`])
        }
        setProgress(completed + failed)
      }
      setStatus(`${abort.signal.aborted ? '已停止，保留已完成结果' : '比较完成'} · 成功 ${completed} · 失败 ${failed}`)
    } finally { controller.current = null; setBusy(false) }
  }
  const stale = snapshot !== identity
  const percent = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(2)}%`
  return <details className="parameter-sweep"><summary><SlidersHorizontal size={18}/><span><strong>比较参数</strong><small>多组回测</small></span><ChevronDown size={16}/></summary>
    <p>勾选参数、设置范围，逐组回测并按收益率排序。</p>
    <fieldset disabled={busy || disabled}><BacktestPeriod label="比较" start={start} end={end} disabled={busy || disabled} onApply={(start, end) => { setStart(start);setEnd(end) }}/>
    <p className="sweep-example">例：10到30，每次增加10，会比较10、20、30。</p>
    <div className="sweep-scroll"><table><thead><tr><th>要比较什么</th><th>当前值</th><th>最小值</th><th>最大值</th><th>每次增加</th></tr></thead><tbody>{fields.map(field => { const range = rangeFor(field); const values = preview(field, range); return <tr key={field.key}><td><label><input type="checkbox" checked={range.enabled} onChange={e => change(field, { enabled: e.target.checked })} />{field.label}{field.unit ? `（${field.unit}）` : ''}</label>{values && <small>将比较：{values}</small>}</td><td>{formatSweepValue(field, field.value)}</td>{(['from', 'to', 'step'] as const).map(key => <td key={key}><input aria-label={`${field.label} ${rangeLabels[key]}`} disabled={!range.enabled} type="number" min={key === 'step' ? undefined : field.min == null ? undefined : field.min * (field.scale ?? 1)} max={key === 'step' ? undefined : field.max == null ? undefined : field.max * (field.scale ?? 1)} step={field.integer ? 1 : 'any'} value={range[key]} onChange={e => change(field, { [key]: e.target.value })} /></td>)}</tr> })}</tbody></table></div>
    <div className="sweep-actions"><small>{validation || `将比较 ${combinations.length} 组`}</small><button type="button" disabled={!!validation} onClick={() => void run()}>开始比较</button></div></fieldset>
    <details className="sweep-notes"><summary>比较规则</summary><p>其余参数、资金、费用与风控保持当前设置，最多100组；不使用AI流程。历史表现不代表未来收益。</p></details>
    {busy && <><button type="button" onClick={() => controller.current?.abort()}>停止比较</button><small>保留已完成结果；正在执行的回测可能继续完成。</small></>}<p role="status">{status}{busy ? ` · 已处理 ${progress}` : ''}</p>
    {results.length > 0 && <><p>本次比较：{period}</p><p>{stale ? '策略已修改，请重新比较。' : '按收益率从高到低排列；使用一组参数后，仍需保存策略。'}</p><div className="sweep-scroll"><table><thead><tr><th>排名 / 参数</th><th>收益率</th><th title="资产从高点回落的最大幅度">最大回落</th><th title="夏普比率：收益与波动的比较指标">夏普比率</th><th>操作</th></tr></thead><tbody>{results.map((row, index) => <tr key={JSON.stringify(row.values)}><td>{index + 1}<small>{describeValues(row.values, resultFields)}</small></td><td>{percent(row.metrics.total_return)}</td><td>{percent(row.metrics.max_drawdown)}</td><td>{row.metrics.sharpe?.toFixed(2) ?? '—'}</td><td><button type="button" disabled={busy || stale} onClick={() => onApply(row.values)}>使用这组</button></td></tr>)}</tbody></table></div></>}
    {!!errors.length && <details><summary>未完成的回测（{errors.length}）</summary>{errors.map((error, i) => <p key={i}>{error}</p>)}</details>}
  </details>
}
