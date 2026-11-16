import { useId, useState, type KeyboardEvent } from 'react'
import { ResultsPanel } from './ResultsPanel'
import './python-project.css'
import { comparisonLabels, type ComparisonEngine, type ComparisonRow, type PreparedComparison } from '../compute/compareBacktests'
import { formatDate, formatNumber, formatPercent } from '../format'
import { Download } from 'lucide-react'
import { ComparisonDiagnostics } from './ComparisonDiagnostics'
import type { BacktestResult } from '../types'

const statuses = { pending: '等待运行', running: '回测中', completed: '已完成', error: '失败', cancelled: '已取消', skipped: '已跳过' }

function downloadEngineReport(result: BacktestResult, engine: ComparisonEngine) {
  const payload = { ...result, backtest_engine: engine }
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload)], { type: 'application/json;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${result.asset.symbol.replace(/[^a-z0-9.-]/gi, '_')}-${engine}-${result.run_id}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function BacktestComparison({ rows, compact = false, context, allowPublish = true }: {
  rows: ComparisonRow[]
  compact?: boolean
  context?: Omit<PreparedComparison, 'request'>
  allowPublish?: boolean
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
  const commonIssue = firstError && rows.every(row => row.status === rows[0].status && row.error === firstError) ? firstError : undefined
  const method = context?.method ?? results[0]?.execution_model
  const actionVersion = results[0]?.daily_action_version
  const sharedActions = actionVersion && results.every(result => result.daily_action_version === actionVersion)
  const unadjustedDaily = !sharedActions && method === 'native'
    && results.some(result => result.interval === '1d' && result.data_source === 'rqalpha-sina')
  const trineReturn = rows.find(row => row.engine === 'atlas')?.result?.metrics.total_return
  const allAgree = results.length === rows.length && results.every(result =>
    formatPercent(result.metrics.total_return) === formatPercent(results[0].metrics.total_return)
    && formatPercent(result.metrics.max_drawdown) === formatPercent(results[0].metrics.max_drawdown)
    && (result.metrics.trade_count ?? result.trades.length) === (results[0].metrics.trade_count ?? results[0].trades.length))
  const coverage = results.find(result => result.bar_count && result.equity.length)
  return <section className={compact ? 'project-engine-results' : 'lab-comparison engine-comparison'} aria-label="三框架回测结果">
    <header className="engine-comparison-heading">
      <h3>{method === 'unified' ? '统一账本校验' : method === 'native' ? '独立撮合对比' : '引擎对比结果'}</h3>
      <span>{results.length} / {rows.length} 完成</span>
    </header>
    {!commonIssue ? <p>{method === 'unified' ? '三套引擎回放相同的成交规则，用于校验一致性。'
      : method === 'native' ? '输入行情与仓位信号一致。各引擎独立处理成交、费用、仓位和公司行动。'
        : '使用同一历史区间回测。'}</p> : null}
    {sharedActions ? <p title={actionVersion}>分红送转已计入。策略信号和基准使用同一复权序列，成交按不复权价格撮合。</p> : null}
    {unadjustedDaily ? <p className="project-compare-error">本次未共用分红送转数据，跨除权日的原生收益与回撤口径不同。</p> : null}
    {context ? <p className="engine-comparison-period" title={`行情版本 ${context.datasetId}`}>
      {formatDate(context.from)} 至 {formatDate(context.to)} · {formatNumber(context.barCount, 0)} 根 K 线
    </p> : coverage ? <p className="engine-comparison-period">
      {formatDate(coverage.equity[0].time)} 至 {formatDate(coverage.equity.at(-1)!.time)} · {formatNumber(coverage.bar_count, 0)} 根 K 线
    </p> : null}
    {commonIssue ? <p className="project-compare-error" role={rows[0].status === 'error' ? 'alert' : 'status'}>{commonIssue}</p> : null}
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
              <td>{result ? formatNumber(result.metrics.trade_count ?? result.trades.length, 0) : '—'}</td>
            </tr>
            {error && !commonIssue ? <tr className="engine-comparison-details"><td colSpan={4}><small>{error}</small></td></tr> : null}
          </tbody>
        })}
      </table>
    </div>
    <ComparisonDiagnostics rows={rows} />
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
            <button type="button" onClick={() => downloadEngineReport(selected.result!, selected.engine)}>
              <Download size={14} />下载{comparisonLabels[selected.engine]}报告
            </button>
          </header>
          <ResultsPanel result={selected.result} loading={false} panelMode="normal" onPanelMode={() => undefined} controls={false} allowPublish={allowPublish} />
        </> : <p className="engine-report-status" role="status">{(commonIssue ? undefined : selected.error) ?? `${comparisonLabels[selected.engine]} · ${statuses[selected.status]}`}</p>}
      </div>
    </div>
  </section>
}
