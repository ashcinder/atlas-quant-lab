import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { labMultiApi } from '../lab-multi-api'
import { labMultiEngineLabels, multiJobActive, multiJobEngine, multiJobStatus } from '../lab-strategy-types'
import type { LabBacktestReport, LabMultiJob, LabReportExport, LabReportPage, LabReportQuery, LabReportRow, LabReportTable } from '../lab-strategy-types'
import { LabReportCharts } from './LabReportCharts'
import './lab-backtest-report.css'

const tabs = [
  ['overview', '收益概览'], ['trades', '交易详情'], ['positions', '持仓详情'],
  ['accounts', '账户详情'], ['logs', '输出日志'], ['performance', '性能分析'],
] as const
const levels = ['INFO', 'WARN', 'DEBUG', 'ERROR']
const formatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
const dateOnly = (time: number) => new Date((time + 8 * 3600) * 1000).toISOString().slice(0, 10)
const timestamp = (time: unknown) => typeof time === 'number' ? formatter.format(time * 1000) : '未记录'
const numeric = (value: unknown, precision = 4) => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: precision, maximumFractionDigits: precision }).format(value) : '—'
const percent = (value: number | null) => value === null ? '—' : `${numeric(value * 100, 2)}%`
const errorMessage = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message : fallback

type Tab = typeof tabs[number][0]
type Download = (table: LabReportExport, query?: LabReportQuery) => Promise<void>
type Column = { key: string; label: string; numeric?: boolean; precision?: number }
const columns: Record<Exclude<LabReportTable, 'logs'>, Column[]> = {
  trades: [{ key: 'time', label: '时间' }, { key: 'symbol', label: '合约代码' }, { key: 'name', label: '合约名称' },
    { key: 'side', label: '买/卖' }, { key: 'position_effect', label: '开/平' }, { key: 'quantity', label: '成交量', numeric: true, precision: 0 },
    { key: 'price', label: '成交价', numeric: true }, { key: 'fee', label: '费用', numeric: true }],
  positions: [{ key: 'time', label: '时间' }, { key: 'symbol', label: '合约代码' }, { key: 'name', label: '合约名称' },
    { key: 'last_price', label: '最新价', numeric: true }, { key: 'direction', label: '多/空' }, { key: 'quantity', label: '持仓数量', numeric: true, precision: 0 },
    { key: 'avg_price', label: '持仓均价', numeric: true }, { key: 'market_value', label: '市值', numeric: true },
    { key: 'dividend_receivable', label: '应收分红', numeric: true },
    { key: 'pnl', label: '持仓浮盈亏', numeric: true }, { key: 'sellable', label: '可卖数量', numeric: true, precision: 0 }, { key: 'fee', label: '当日费用', numeric: true }],
  accounts: [{ key: 'time', label: '日期' }, { key: 'account_type', label: '账户类别' }, { key: 'cash', label: '可用资金', numeric: true },
    { key: 'equity', label: '总权益', numeric: true }, { key: 'market_value', label: '市值', numeric: true }, { key: 'margin', label: '保证金', numeric: true },
    { key: 'fee', label: '当日费用', numeric: true }, { key: 'daily_pnl', label: '每日盈亏', numeric: true }],
}
const translations: Record<string, string> = { buy: '买入', sell: '卖出', BUY: '买入', SELL: '卖出', long: '多', LONG: '多', short: '空', SHORT: '空', open: '开', close: '平', close_today: '平今', close_yesterday: '平昨', OPEN: '开', CLOSE: '平', CLOSE_TODAY: '平今', CLOSE_YESTERDAY: '平昨', stock: '股票', STOCK: '股票' }

function Dialog({ open, title, children, onClose, large = false }: { open: boolean; title: string; children: ReactNode; onClose: () => void; large?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])
  return <dialog ref={ref} className={`lab-report-dialog${large ? ' lab-report-dialog-full' : ''}`} aria-labelledby={id} onCancel={event => { if (event.target === event.currentTarget) { event.preventDefault(); onClose() } }} onClose={event => { if (event.target === event.currentTarget) onClose() }}>
    <header><h2 id={id}>{title}</h2><button type="button" onClick={onClose} aria-label={`关闭${title}`}>关闭</button></header>
    {open && children}
  </dialog>
}

function cell(row: LabReportRow, column: Column, table: LabReportTable) {
  const value = row[column.key]
  if (column.key === 'time') return typeof value === 'number' ? table === 'accounts' ? dateOnly(value) : timestamp(value) : '—'
  if (value === null || value === undefined || value === '') return '—'
  if (column.numeric) return `${(column.key === 'pnl' || column.key === 'daily_pnl') && typeof value === 'number' && value > 0 ? '+' : ''}${numeric(value, column.precision)}`
  return translations[String(value)] ?? String(value)
}

function ReportRows({ ownerId, job, table, report, download, downloading }: { ownerId: string; job: LabMultiJob; table: LabReportTable; report?: LabBacktestReport; download: Download; downloading: string | null }) {
  const [response, setResponse] = useState<{ key: string; page: LabReportPage | null; error: string }>({ key: '', page: null, error: '' })
  const [attempt, setAttempt] = useState(0)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(50)
  const [filters, setFilters] = useState({ start: '', end: '', symbol: '', side: '' })
  const [applied, setApplied] = useState<LabReportQuery>({})
  const [sort, setSort] = useState('time')
  const [descending, setDescending] = useState(false)
  const [visibleLevels, setVisibleLevels] = useState(levels)
  const [feeDetails, setFeeDetails] = useState(false)
  const [fundingDetails, setFundingDetails] = useState(false)
  const invalidRange = !!filters.start && !!filters.end && filters.start > filters.end
  const noLevels = table === 'logs' && visibleLevels.length === 0
  const query: LabReportQuery = { ...applied, offset, limit, sort, descending, ...(table === 'logs' ? { levels: visibleLevels.join(',') } : {}) }
  const signature = JSON.stringify(query)
  const responseKey = JSON.stringify([ownerId, job.id, job.status, table, signature, attempt])
  const busy = !noLevels && response.key !== responseKey
  const error = response.key === responseKey ? response.error : ''
  const page = noLevels ? { rows: [], total: 0, unfiltered_total: report?.tables.logs.count ?? 0, offset: 0, limit, recorded: true, logs_truncated: report?.logs_truncated ?? false } : response.page
  useEffect(() => {
    const controller = new AbortController()
    let current = true
    if (noLevels) return () => controller.abort()
    labMultiApi.reportRows(ownerId, job.id, table, JSON.parse(signature) as LabReportQuery, controller.signal).then(page => {
      if (current) setResponse({ key: responseKey, page, error: '' })
    }).catch(reason => {
      if (current && !controller.signal.aborted) setResponse(previous => ({ key: responseKey, page: previous.page, error: errorMessage(reason, '无法读取报告明细。') }))
    })
    return () => { current = false; controller.abort() }
  }, [ownerId, job.id, table, signature, responseKey, noLevels])
  const apply = (event: FormEvent) => {
    event.preventDefault()
    if (invalidRange) return
    setOffset(0)
    setApplied({ start: filters.start || undefined, end: filters.end || undefined, symbol: filters.symbol.trim().toUpperCase() || undefined, side: filters.side as LabReportQuery['side'] })
  }
  const exportRows = () => {
    const allMatching = { ...query }
    delete allMatching.offset
    delete allMatching.limit
    void download(table, allMatching)
  }
  const total = page?.total ?? 0
  const countText = `${total ? offset + 1 : 0}–${Math.min(offset + limit, total)} / ${total}`
  const activeColumns = table === 'logs' ? [] : [...columns[table], ...(table === 'trades' && feeDetails ? [
    { key: 'commission', label: '佣金', numeric: true }, { key: 'tax', label: '税费', numeric: true }, { key: 'order_id', label: '订单标识' }, { key: 'exec_id', label: '成交标识' },
  ] : []), ...(table === 'accounts' && fundingDetails ? [
    { key: 'frozen_cash', label: '冻结资金', numeric: true }, { key: 'dividend_receivable', label: '应收分红', numeric: true },
    { key: 'cash_liabilities', label: '现金负债', numeric: true }, { key: 'cash_liabilities_interest', label: '负债利息', numeric: true },
    { key: 'pending_cash_flow', label: '待到账申赎', numeric: true },
  ] : [])]
  return <section className="lab-report-detail" aria-label={tabs.find(([key]) => key === table)?.[1]}>
    <form className="lab-report-filters" onSubmit={apply}>
      <label>明细起日<input type="date" value={filters.start} onChange={event => setFilters({ ...filters, start: event.target.value })} /></label>
      <label>明细止日<input type="date" value={filters.end} onChange={event => setFilters({ ...filters, end: event.target.value })} /></label>
      {table !== 'accounts' && table !== 'logs' && <label>证券代码<input type="search" placeholder="例如 600519.SS" value={filters.symbol} onChange={event => setFilters({ ...filters, symbol: event.target.value })} /></label>}
      {table === 'trades' && <label>交易方向<select value={filters.side} onChange={event => setFilters({ ...filters, side: event.target.value })}><option value="">全部</option><option value="buy">买入</option><option value="sell">卖出</option></select></label>}
      <button type="submit" disabled={invalidRange}>应用筛选</button>
      <button type="button" onClick={() => { setFilters({ start: '', end: '', symbol: '', side: '' }); setApplied({}); setOffset(0) }}>重置筛选</button>
      <label>排序字段<select value={sort} onChange={event => { setSort(event.target.value); setOffset(0) }}><option value="time">时间</option>{table !== 'logs' && table !== 'accounts' && <option value="symbol">证券代码</option>}</select></label>
      <label className="lab-report-checkbox"><input type="checkbox" checked={descending} onChange={event => { setDescending(event.target.checked); setOffset(0) }} />倒序</label>
      <button type="button" disabled={!!downloading || noLevels || busy || page?.recorded === false} onClick={exportRows}>{downloading === table ? '正在下载…' : table === 'logs' ? '下载日志' : '导出全部筛选结果'}</button>
    </form>
    {invalidRange && <p role="alert">明细止日不能早于起日。</p>}
    {table === 'logs' && <fieldset className="lab-report-levels"><legend>日志等级</legend>{levels.map(level => <label key={level}><input type="checkbox" checked={visibleLevels.includes(level)} onChange={event => { setVisibleLevels(current => event.target.checked ? levels.filter(value => value === level || current.includes(value)) : current.filter(value => value !== level)); setOffset(0) }} />{level}</label>)}</fieldset>}
    {table === 'trades' && <label className="lab-report-checkbox lab-report-column-choice"><input type="checkbox" checked={feeDetails} onChange={event => setFeeDetails(event.target.checked)} />显示佣金、税费与原生标识</label>}
    {table === 'accounts' && <label className="lab-report-checkbox lab-report-column-choice"><input type="checkbox" checked={fundingDetails} onChange={event => setFundingDetails(event.target.checked)} />显示资金组成</label>}
    {table === 'positions' && <p className="lab-report-note">持仓浮盈亏不是累计已实现盈亏；费用为当日费用。可卖量为结算前原生快照，未采集时显示“—”。数量为零但仍有应收分红的记录会保留。</p>}
    {table === 'accounts' && <p className="lab-report-note">金额单位为人民币元。总权益按原生账户记录展示，不能仅由可用资金＋市值推算；展开资金组成可查看冻结资金、应收分红、待到账申赎及负债。未记录或不适用字段显示“—”，不补零。</p>}
    {table === 'trades' && <p className="lab-report-note">成交价和费用单位为人民币元；开平字段仅按原生记录显示，不代表支持期货交易。</p>}
    {(report?.logs_truncated || page?.logs_truncated) && table === 'logs' && <p className="lab-report-notice" role="status">日志已达到采集配额，部分内容未保留；交易和账户明细不会因此静默截断。</p>}
    {error ? <div className="lab-report-error" role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt(attempt + 1)}>重试读取明细</button></div>
      : busy && !page ? <p className="lab-report-empty" role="status">正在读取报告明细…</p>
      : page?.recorded === false ? <p className="lab-report-empty">本次历史回测未记录此类明细；不会自动重跑或补写历史。</p>
      : !page?.rows.length ? <p className="lab-report-empty" role="status">{noLevels ? '未选择日志等级。' : busy ? '正在读取报告明细…' : '当前筛选条件下暂无记录。'}</p>
      : <div className={`lab-report-table-scroll${busy ? ' is-loading' : ''}`} aria-busy={busy}>
        {table === 'logs' ? <table className="lab-report-log-table"><caption>运行日志</caption><thead><tr><th>时间</th><th>等级</th><th>来源</th><th>正文</th></tr></thead><tbody>{page.rows.map((row, index) => <tr key={row.sequence ?? `${offset}:${index}`}><td>{timestamp(row.time)}</td><td><span className={`lab-report-log-level level-${String(row.level).toLowerCase()}`}>{row.level}</span></td><td>{row.source ?? '未记录'}{typeof row.line === 'number' ? ` · 第 ${row.line} 行` : ''}</td><td><pre>{row.message}</pre></td></tr>)}</tbody></table>
          : <table><caption>{tabs.find(([key]) => key === table)?.[1]} · 全部金额以人民币元计</caption><thead><tr>{activeColumns.map(column => <th key={column.key} scope="col" className={column.numeric ? 'numeric' : undefined}>{column.label}</th>)}</tr></thead><tbody>{page.rows.map((row, index) => <tr key={`${offset + index}:${row.time}:${row.symbol ?? ''}`}>{activeColumns.map(column => <td key={column.key} className={column.numeric ? `numeric${column.key === 'pnl' || column.key === 'daily_pnl' ? Number(row[column.key]) < 0 ? ' is-negative' : Number(row[column.key]) > 0 ? ' is-positive' : '' : ''}` : undefined}>{cell(row, column, table)}</td>)}</tr>)}</tbody></table>}
      </div>}
    <div className="lab-report-pagination"><span aria-live="polite">显示 {countText} 条{page && page.total !== page.unfiltered_total ? ` · 原始 ${page.unfiltered_total} 条` : ''}</span>
      <label>每页<select value={limit} onChange={event => { setLimit(Number(event.target.value)); setOffset(0) }}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></label>
      <button type="button" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</button><button type="button" disabled={busy || offset + limit >= total} onClick={() => setOffset(offset + limit)}>下一页</button>
    </div>
    <p className="lab-report-note">导出包含已应用筛选下的全部记录，不限当前页；切换标签不会重新运行回测。</p>
  </section>
}

function ReportContent({ job, ownerId, legacyOverview, onLegacyDownload, onExpand }: { job: LabMultiJob; ownerId: string; legacyOverview?: ReactNode; onLegacyDownload?: () => void; onExpand?: () => void }) {
  const id = useId()
  const [tab, setTab] = useState<Tab>('overview')
  const [annualOpen, setAnnualOpen] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [source, setSource] = useState<{ source: string; source_sha256: string; revision: number } | null>(null)
  const [sourceBusy, setSourceBusy] = useState(false)
  const [sourceError, setSourceError] = useState('')
  const [downloading, setDownloading] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const sourceController = useRef<AbortController | null>(null)
  const downloadController = useRef<AbortController | null>(null)
  const report = job.report ?? job.result?.report
  const legacy = !!job.result && !report
  const engine = multiJobEngine(job)
  const version = job.engine_version ?? job.result?.engine_version
  const first = report?.series[0]?.time ?? job.result?.equity[0]?.time
  const last = report?.series.at(-1)?.time ?? job.result?.equity.at(-1)?.time
  useEffect(() => () => { sourceController.current?.abort(); downloadController.current?.abort() }, [])
  const download: Download = async (table, query = {}) => {
    if (downloadController.current) return
    if (legacy && table === 'snapshot' && onLegacyDownload) { onLegacyDownload(); return }
    const controller = new AbortController()
    downloadController.current = controller
    setDownloading(table); setDownloadError('')
    try {
      const file = await labMultiApi.downloadReport(ownerId, job.id, table, query, controller.signal)
      if (controller.signal.aborted) return
      const url = URL.createObjectURL(file.blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = file.filename
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) {
      if (!controller.signal.aborted) setDownloadError(errorMessage(reason, '无法下载回测报告。'))
    } finally {
      if (downloadController.current === controller) { downloadController.current = null; setDownloading(null) }
    }
  }
  const loadSource = async () => {
    if (sourceController.current) return
    const controller = new AbortController()
    sourceController.current = controller
    setSourceOpen(true); setSourceBusy(true); setSourceError('')
    try {
      const snapshot = await labMultiApi.reportSource(ownerId, job.id, controller.signal)
      if (!controller.signal.aborted) setSource(snapshot)
    } catch (reason) {
      if (!controller.signal.aborted) setSourceError(errorMessage(reason, '无法读取本次运行源码。'))
    } finally {
      if (sourceController.current === controller) { sourceController.current = null; setSourceBusy(false) }
    }
  }
  const selectTab = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    setTab(tabs[next][0])
    document.getElementById(`${id}-tab-${tabs[next][0]}`)?.focus()
  }
  const overview = <>
    {!job.result ? <div className="lab-report-empty"><strong>{multiJobActive(job) ? '回测尚未完成' : '本次没有完整的经济结果'}</strong><p>不展示未经计算的收益。已产生的运行日志可在“输出日志”中查看。</p></div>
      : legacy ? <><p className="lab-report-notice">此历史结果未记录新版报告数据，以下保留原始净值、指标及成交；逐日持仓、基准和日志不会补造。</p>{legacyOverview}</>
        : report && <>
          <div className="lab-report-section-heading"><h3>概览指标 <small>完整回测区间</small></h3><span>{report.benchmark ? `${report.benchmark.name} · ${report.benchmark.symbol}` : '未设置基准'}</span></div>
          <dl className="lab-report-metrics">{report.metrics.map(metric => <div key={metric.key}><dt title={metric.definition}>{metric.label}</dt><dd>{metric.value === null ? <><span>—</span><small>{metric.reason ?? '不可计算'}</small></> : metric.format === 'percent' ? `${numeric(metric.value * 100, metric.precision)}%` : numeric(metric.value, metric.precision)}</dd></div>)}</dl>
          <div className="lab-report-overview-actions"><button type="button" onClick={() => setAnnualOpen(true)}>查看年度收益</button><button type="button" disabled={!!downloading} onClick={() => void download('annual')}>{downloading === 'annual' ? '正在下载…' : '导出年度收益'}</button></div>
          <LabReportCharts report={report} />
          <details className="lab-report-conventions"><summary>指标口径与计算来源</summary><p>期间胜率按平台定义的正收益期间占比展示，不是逐笔交易胜率。不可计算项不填零。</p><div className="lab-report-table-scroll"><table><thead><tr><th>指标</th><th>定义</th><th>来源 / 缺值原因</th></tr></thead><tbody>{report.metrics.map(metric => <tr key={metric.key}><th scope="row">{metric.label}</th><td>{metric.definition}</td><td>{metric.source}{metric.reason ? ` · ${metric.reason}` : ''}</td></tr>)}</tbody></table></div><dl>{Object.entries(report.conventions).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value ?? '未记录'}</dd></div>)}</dl></details>
        </>}
  </>
  return <div className="lab-report">
    <header className="lab-report-heading"><div><h3>{job.name || 'RQAlpha 回测报告'}</h3><p>草稿修订 {job.revision} · {multiJobStatus[job.status]} · {labMultiEngineLabels[engine]}{version ? ` ${version}` : ''}</p></div><span className="lab-report-unverified">未经 ZKP 验证</span></header>
    <div className="lab-report-run-strip"><span>{first !== undefined && last !== undefined ? `${dateOnly(first)} 至 ${dateOnly(last)}` : '实际运行区间尚未记录'}</span><span>{typeof job.elapsed_seconds === 'number' ? `耗时 ${numeric(job.elapsed_seconds, 2)} 秒` : '耗时未记录'}</span><span>日线 · current_bar 收盘价撮合</span></div>
    <div className="lab-report-toolbar"><button type="button" onClick={() => void loadSource()} disabled={sourceBusy}>查看本次源码</button><button type="button" disabled={!!downloading} onClick={() => void download('snapshot')}>{downloading === 'snapshot' ? '正在下载…' : '下载回测快照'}</button>{onExpand && <button type="button" onClick={onExpand}>查看完整报告</button>}</div>
    <p className="lab-report-note">学术非商用历史回测，不是实盘或持续模拟。当前 K 线收盘价撮合不代表收盘后可以该价格成交。</p>
    {multiJobActive(job) && <progress aria-label="多股回测进度" max={1} value={job.progress ?? undefined} />}
    {job.error && <p className="lab-report-error" role="alert">{job.error}</p>}
    {downloadError && <p className="lab-report-error" role="alert">{downloadError}</p>}
    <div className="lab-report-tabs" role="tablist" aria-label="回测报告标签">{tabs.map(([key, label], index) => <button key={key} type="button" role="tab" id={`${id}-tab-${key}`} aria-selected={tab === key} aria-controls={`${id}-panel-${key}`} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)} onKeyDown={event => selectTab(event, index)}>{label}</button>)}</div>
    <section className="lab-report-panel" role="tabpanel" id={`${id}-panel-${tab}`} aria-labelledby={`${id}-tab-${tab}`} tabIndex={0}>
      {tab === 'overview' ? overview
        : tab === 'performance' ? <div className="lab-report-empty"><h3>性能分析</h3><p>{report?.performance.enabled ? '本报告未提供详细性能采样数据。' : '该次回测未开启性能分析。'}</p><p>查看报告不会启动采集或重新运行策略；总运行耗时与函数性能采样不是同一指标。</p></div>
          : legacy && tab !== 'trades' ? <p className="lab-report-empty">此历史回测未记录新版{tabs.find(([key]) => key === tab)?.[1]}。原始成交和完整快照仍保留在“收益概览”中，不会自动重跑。</p>
            : <ReportRows key={`${job.id}:${tab}`} ownerId={ownerId} job={job} table={tab} report={report} download={download} downloading={downloading} />}
    </section>
    <details className="lab-report-snapshot"><summary>本次运行参数和源码摘要</summary><p>{labMultiEngineLabels[engine]} · 引擎版本 {version ?? '历史未记录'} · current_bar 收盘价撮合</p><p>使用本次已保存快照，不跟随当前草稿修改。</p><dl><div><dt>源码 SHA-256</dt><dd><code>{job.source_sha256}</code></dd></div><div><dt>行情 SHA-256</dt><dd><code>行情 SHA-256 {job.dataset_sha256 ?? '历史未记录'}</code></dd></div><div><dt>手续费率</dt><dd>{percent(job.settings.commission_rate)}</dd></div><div><dt>滑点率</dt><dd>{percent(job.settings.slippage_rate)}</dd></div><div><dt>股票池</dt><dd>{job.settings.symbols.join('、') || '未记录'}</dd></div></dl>{!!Object.keys(job.settings.parameters ?? {}).length && <pre>{JSON.stringify(job.settings.parameters, null, 2)}</pre>}</details>
    <Dialog open={annualOpen} title="策略年度收益" onClose={() => setAnnualOpen(false)}><div className="lab-report-modal-body"><p className="lab-report-note">按每年实际交易日复利计算；部分年度只反映所列覆盖区间，不是全年或年化收益。</p><div className="lab-report-table-scroll"><table><thead><tr><th>时间</th><th>策略</th><th>基准</th><th>实际覆盖</th></tr></thead><tbody>{report?.annual_returns.map(row => <tr key={row.year}><th scope="row">{row.year}{row.partial ? '（部分年度）' : ''}</th><td className="numeric">{percent(row.strategy)}</td><td className="numeric">{percent(row.benchmark)}</td><td>{dateOnly(row.start)} 至 {dateOnly(row.end)}</td></tr>)}</tbody></table></div><button type="button" disabled={!!downloading} onClick={() => void download('annual')}>下载年度收益 CSV</button>{downloadError && <p role="alert">{downloadError}</p>}</div></Dialog>
    <Dialog open={sourceOpen} title="本次运行源码" onClose={() => { sourceController.current?.abort(); sourceController.current = null; setSourceBusy(false); setSourceOpen(false) }}><div className="lab-report-modal-body">{sourceBusy ? <p role="status">正在读取固定版本源码…</p> : sourceError ? <div role="alert"><p>{sourceError}</p><button type="button" onClick={() => void loadSource()}>重试读取源码</button></div> : source ? <><p>草稿修订 {source.revision} · SHA-256 <code>{source.source_sha256}</code></p><pre className="lab-report-source"><code>{source.source}</code></pre></> : null}</div></Dialog>
  </div>
}

export function LabBacktestReport(props: { job: LabMultiJob; ownerId: string; legacyOverview?: ReactNode; onLegacyDownload?: () => void }) {
  const [expanded, setExpanded] = useState(false)
  return <>
    {!expanded && <ReportContent key={`${props.ownerId}:${props.job.id}`} {...props} onExpand={() => setExpanded(true)} />}
    <Dialog open={expanded} title="完整回测报告" large onClose={() => setExpanded(false)}><ReportContent key={`${props.ownerId}:${props.job.id}`} {...props} /></Dialog>
  </>
}
