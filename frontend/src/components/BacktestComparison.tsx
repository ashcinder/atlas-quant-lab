import { useId, useState, type KeyboardEvent } from 'react'
import { ResultsPanel } from './ResultsPanel'
import './python-project.css'
import { comparisonLabels, type ComparisonEngine, type ComparisonRow, type PreparedComparison } from '../compute/compareBacktests'
import { formatDate, formatNumber, formatPercent } from '../format'

const statuses = { pending: '等待运行', running: '回测中', completed: '已完成', error: '失败', cancelled: '已取消', skipped: '已跳过' }

export function BacktestComparison({ rows, compact = false, context }: {
  rows: ComparisonRow[]
  compact?: boolean
  context?: Omit<PreparedComparison, 'request'>
}) {
  const id = useId()
  const [preferred, setPreferred] = useState<ComparisonEngine>()
  if (!rows.length) return null
  const selected = rows.find(row => row.engine === preferred)
    ?? rows.find(row => row.result)
    ?? rows[0]

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 }
    const offset = offsets[event.key]
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1
      : offset ? (index + offset + rows.length) % rows.length : undefined
    if (next === undefined) return
    event.preventDefault()
    const engine = rows[next].engine
    setPreferred(engine)
    document.getElementById(`${id}-${engine}`)?.focus()
  }

  const results = rows.flatMap(row => row.result ? [row.result] : [])
  const firstError = rows[0].error
  const commonError = firstError && rows.every(row => row.status === 'error' && row.error === firstError) ? firstError : undefined
  const method = context?.method ?? results[0]?.execution_model
  const trineReturn = rows.find(row => row.engine === 'atlas')?.result?.metrics.total_return
  const allAgree = results.length === rows.length && results.every(result =>
    formatPercent(result.metrics.total_return) === formatPercent(results[0].metrics.total_return)
    && formatPercent(result.metrics.max_drawdown) === formatPercent(results[0].metrics.max_drawdown)
    && result.trades.length === results[0].trades.length)
  return <section className={compact ? 'project-engine-results' : 'lab-comparison engine-comparison'} aria-label="三框架回测结果">
    <header className="engine-comparison-heading">
      <h3>{method === 'unified' ? '统一账本校验' : method === 'native' ? '独立撮合对比' : '引擎对比结果'}</h3>
      <span>{results.length} / {rows.length} 完成</span>
    </header>
    <p>{method === 'unified' ? '三套引擎回放相同的成交规则，用于校验一致性。'
      : method === 'native' ? '输入行情与仓位信号一致。收益差异反映各自的成交、费用和仓位规则。'
        : '使用同一历史区间回测。'}</p>
    {context ? <p className="engine-comparison-period" title={`行情版本 ${context.datasetId}`}>
      {formatDate(context.from)} 至 {formatDate(context.to)} · {formatNumber(context.barCount, 0)} 根 K 线
    </p> : null}
    {commonError ? <p className="project-compare-error" role="alert">{commonError}</p> : null}
    {allAgree ? <p className="engine-comparison-agreement">三套报告的收益、回撤和成交笔数在显示精度内一致。</p> : null}
    <div className="engine-comparison-table">
      <table><thead><tr><th scope="col">引擎</th><th scope="col">收益</th><th scope="col">最大回撤</th><th scope="col">成交</th></tr></thead>
        {rows.map(({ engine, status, result, error }) => {
          const change = result?.metrics.total_return
          const delta = engine !== 'atlas' && change != null && trineReturn != null ? (change - trineReturn) * 100 : null
          return <tbody key={engine}>
            <tr><th scope="row"><strong>{comparisonLabels[engine]}</strong><small data-status={status}>{statuses[status]}</small></th>
              <td>{formatPercent(change)}
                {delta != null && Math.abs(delta) >= 0.005 ? <small title="相对 Trine 的收益差，单位为百分点">{delta > 0 ? '+' : ''}{delta.toFixed(2)} 个百分点</small> : null}
              </td>
              <td>{formatPercent(result?.metrics.max_drawdown)}</td>
              <td>{result ? formatNumber(result.trades.length, 0) : '—'}</td>
            </tr>
            {error && !commonError ? <tr className="engine-comparison-details"><td colSpan={4}><small>{error}</small></td></tr> : null}
          </tbody>
        })}
      </table>
    </div>
    <div className="engine-comparison-reports">
      <div role="tablist" aria-label="回测引擎" className="engine-report-tabs">
        {rows.map(({ engine, status }, index) => <button type="button" role="tab" key={engine} id={`${id}-${engine}`}
          aria-controls={`${id}-report`} aria-selected={selected.engine === engine} tabIndex={selected.engine === engine ? 0 : -1}
          onClick={() => setPreferred(engine)} onKeyDown={event => navigate(event, index)}>
          {comparisonLabels[engine]}
          {status !== 'completed' ? <small>{statuses[status]}</small> : null}
        </button>)}
      </div>
      <div role="tabpanel" id={`${id}-report`} aria-labelledby={`${id}-${selected.engine}`} tabIndex={0}>
        {selected.result ? <>
          <header className="engine-report-heading"><h4>{comparisonLabels[selected.engine]} 回测报告</h4>
            {selected.result.engine_version ? <small>{selected.result.engine_version}</small> : null}
          </header>
          <ResultsPanel result={selected.result} loading={false} panelMode="normal" onPanelMode={() => undefined} controls={false} />
        </> : <p className="engine-report-status" role="status">{(commonError ? undefined : selected.error) ?? `${comparisonLabels[selected.engine]} · ${statuses[selected.status]}`}</p>}
      </div>
    </div>
  </section>
}
