import { lazy, Suspense, useMemo, useState } from 'react'
import type { ProjectReport, ProjectReportSummary } from '../compute/pythonProject'
import { formatNumber } from '../format'
import './python-project.css'

const EquityChart = lazy(() => import('./EquityChart').then(module => ({ default: module.EquityChart })))
const EMPTY_ROWS: NonNullable<ProjectReportSummary['equity']> = []
const PAGE_SIZE = 15

function money(value: unknown) {
  return typeof value === 'number' ? formatNumber(value, 2) : '—'
}

function formatReturn(value: unknown) {
  return typeof value === 'number' ? (value > 0 ? '+' : '') + (value * 100).toFixed(2) + '%' : '—'
}

function ProjectRunDetails({ summary }: { summary: ProjectReportSummary }) {
  const { data, equity = EMPTY_ROWS, trades = EMPTY_ROWS } = summary
  const result = data.result && typeof data.result === 'object' ? data.result as Record<string, unknown> : data
  const config = data.execution && typeof data.execution === 'object' ? data.execution as Record<string, unknown> : {}
  const [view, setView] = useState<'overview' | 'trades' | 'account'>('overview')
  const [page, setPage] = useState(0)
  const points = useMemo(() => {
    const series = new Map<number, number>()
    for (const row of equity) {
      const time = typeof row.date === 'string' ? Date.parse(row.date) / 1000 : NaN
      if (Number.isFinite(time) && typeof row.equity === 'number') series.set(time, row.equity)
    }
    let peak = typeof config.starting_cash === 'number' ? config.starting_cash : 0
    const points = []
    for (const [time, equity] of [...series].sort(([left], [right]) => left - right)) {
      peak = Math.max(peak, equity)
      points.push({ time, equity, drawdown: peak > 0 ? equity / peak - 1 : 0 })
    }
    return points
  }, [equity, config.starting_cash])
  const metrics = [
    ['累计收益', formatReturn(result.return)],
    ['最大回撤', typeof result.max_drawdown === 'number' ? (Math.abs(result.max_drawdown) * 100).toFixed(2) + '%' : '—'],
    ['已平仓', typeof result.sells === 'number' ? String(result.sells) : '—'],
    ['期末净值', money(result.equity)],
  ]
  const execution = [
    ['初始资金', money(config.starting_cash)],
    ['交易日', typeof data.sessions === 'number' ? String(data.sessions) : '—'],
    ['买入笔数', typeof result.buys === 'number' ? String(result.buys) : '—'],
    ['期末未平仓', typeof result.open === 'number' ? String(result.open) : '—'],
  ].filter(([, value]) => value !== '—')
  const rows = view === 'trades' ? trades : equity
  const count = Math.ceil(rows.length / PAGE_SIZE)
  const visible = rows.slice(Math.max(0, rows.length - (page + 1) * PAGE_SIZE), rows.length - page * PAGE_SIZE).reverse()
  return <section className="python-project-metrics project-results-detail" aria-label="项目回测明细">
    <h3>{typeof data.industry === 'string' ? data.industry : '项目报告'}</h3>
    {typeof data.from === 'string' && typeof data.to === 'string' ? <p>{data.from} 至 {data.to}</p> : null}
    <dl>{metrics.map(([label, value], index) => <div key={label} className={index === 0 ? 'project-metric-return' : undefined}>
      <dt>{label}</dt><dd data-tone={index === 0 && typeof result.return === 'number' ? Math.sign(result.return) : undefined}>{value}</dd>
    </div>)}</dl>
    {points.length || trades.length ? <div className="project-report-views" aria-label="报告视图">
      {([['overview', '权益概览'], ['trades', '逐笔成交'], ['account', '每日账户']] as const)
        .filter(([key]) => key === 'overview' || (key === 'trades' ? trades.length > 0 : equity.length > 0))
        .map(([key, label]) => <button type="button" key={key} aria-pressed={view === key} onClick={() => { setView(key); setPage(0) }}>{label}</button>)}
    </div> : null}
    {view === 'overview' ? <>
      {points.length ? <Suspense fallback={<p role="status">正在加载权益曲线…</p>}><EquityChart points={points} /></Suspense> : null}
      {execution.length ? <dl className="project-execution-details">{execution.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : null}
    </> : <>
      <div className="project-report-table"><table aria-label={view === 'trades' ? '逐笔成交' : '每日账户'}>
        {view === 'trades' ? <><thead><tr><th>日期 / 标的</th><th>方向 / 股数</th><th>成交价 / 费用</th></tr></thead>
          <tbody>{visible.map((row, index) => <tr key={index}><td>{row.date}<small>{row.time} · {row.symbol}</small></td>
            <td>{row.side === 'buy' ? '买入' : row.side === 'sell' ? '卖出' : '—'}<small>{row.shares ?? '—'}</small></td>
            <td>{money(row.price)}<small>{money(row.fee)}</small></td></tr>)}</tbody></>
          : <><thead><tr><th>日期</th><th>权益 / 现金</th><th>持仓数</th></tr></thead>
            <tbody>{visible.map((row, index) => <tr key={index}><td>{row.date}</td><td>{money(row.equity)}<small>{money(row.cash)}</small></td>
              <td>{row.positions ?? '—'}</td></tr>)}</tbody></>}
      </table></div>
      {count > 1 ? <div className="project-report-pagination">
        <button disabled={page === 0} onClick={() => setPage(value => value - 1)}>上一页</button>
        <span>{page + 1} / {count}</span>
        <button disabled={page + 1 >= count} onClick={() => setPage(value => value + 1)}>下一页</button>
      </div> : null}
    </>}
  </section>
}

export function ProjectReportDetails({ report }: { report: ProjectReport }) {
  return <>
    {report.summaries.map(summary => <ProjectRunDetails key={summary.path} summary={summary} />)}
    {Array.from(new Set(report.warnings)).map(warning => <p key={warning}>{warning}</p>)}
  </>
}
