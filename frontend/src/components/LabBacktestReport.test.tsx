import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { labMultiApi } from '../lab-multi-api'
import { defaultMultiSettings } from '../lab-strategy-types'
import type { LabBacktestReport, LabMultiJob, LabReportPage, LabReportRow } from '../lab-strategy-types'
import { LabBacktestReport as Report } from './LabBacktestReport'
import { LabMultiBacktestForm, LabMultiBacktestResult } from './LabMultiBacktest'

vi.mock('../lab-multi-api', () => ({ labMultiApi: { reportRows: vi.fn(), reportSource: vi.fn(), downloadReport: vi.fn() } }))
vi.mock('../api', () => ({ api: { searchAssets: vi.fn().mockResolvedValue([]) } }))
vi.mock('./EquityChart', () => ({ EquityChart: () => <div>历史权益曲线</div> }))

const days = ['2025-01-02', '2025-01-03', '2025-01-06'].map(day => Date.parse(`${day}T15:00:00+08:00`) / 1000)
const report: LabBacktestReport = {
  schema_version: 'atlas.rqalpha.report/v1', benchmark: { symbol: '000300.SS', name: '合成基准' },
  conventions: { trading_days: 252, period_win_rate: '正收益期间占比' },
  metrics: ['回测收益', '回测年化收益', '基准收益', '基准年化收益', '累计净值', '超额收益最大回撤率', '年胜率', '季度胜率', '月胜率', '日胜率', '阿尔法', '贝塔', '夏普率', '索提诺比率', '信息比率', '年化波动率', '最大回撤', '年化跟踪误差', '年化下行波动率'].map((label, index) => ({ key: `synthetic-${index}`, label, value: index === 10 ? null : .04, format: index === 4 ? 'number' : 'percent', precision: 2, definition: `${label}的合成测试口径`, source: 'synthetic-test-fixture', reason: index === 10 ? '短样本不可计算' : null })),
  series: days.map((time, i) => ({ time, equity: 10200 + i * 100, net_value: 1.02 + i * .01, strategy_return: .02 + i * .01, benchmark_return: .01 + i * .005, excess_return: .01 + i * .005, daily_pnl: i === 1 ? -100 : 200, buy_amount: i === 0 ? 3000 : 0, sell_amount: i === 2 ? 1000 : 0 })),
  annual_returns: [{ year: 2025, start: days[0], end: days[2], partial: true, strategy: .04, benchmark: .02 }],
  drawdown: { start: days[0], end: days[1], value: .01 },
  tables: { trades: { count: 120, recorded: true }, positions: { count: 3, recorded: true }, accounts: { count: 3, recorded: true }, logs: { count: 2, recorded: true } },
  logs_truncated: false, performance: { enabled: false },
}
const job: LabMultiJob = { id: 'synthetic-job-a', strategy_id: 'synthetic-strategy', revision: 3, name: '合成回测', status: 'succeeded', progress: 1, error: null, created_at: '2025-01-06T08:00:00Z', started_at: '2025-01-06T08:00:00Z', finished_at: '2025-01-06T08:00:02Z', elapsed_seconds: 2, settings: { ...defaultMultiSettings, engine_id: 'rqalpha', symbols: ['600519.SS', '000001.SZ'] }, source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), engine_id: 'rqalpha', engine_version: '6.5.0', matching_type: 'current_bar', result: { equity: report.series.map(point => ({ time: point.time, equity: point.equity, cash: 5000, market_value: point.equity - 5000 })), trades: [], initial_capital: 10000, final_equity: 10400, total_return: .04, max_drawdown: .01, report } }
const trade: LabReportRow = { time: days[0], symbol: '600519.SS', name: '合成标的甲', side: 'buy', position_effect: 'open', quantity: 100, price: 10, fee: 5, commission: 5, tax: 0, order_id: 'synthetic-order', exec_id: 'synthetic-fill' }
const page = (rows: LabReportRow[] = [trade], total = 120): LabReportPage => ({ rows, total, unfiltered_total: total, offset: 0, limit: 50, recorded: true, logs_truncated: false })
const openTab = (name: string) => fireEvent.click(screen.getByRole('tab', { name }))

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) } })
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:synthetic-report') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { expect(this.isConnected).toBe(true) })
  vi.mocked(labMultiApi.reportRows).mockReset().mockResolvedValue(page())
  vi.mocked(labMultiApi.reportSource).mockReset().mockResolvedValue({ source: '# fixed synthetic source', source_sha256: job.source_sha256, revision: 3 })
  vi.mocked(labMultiApi.downloadReport).mockReset().mockResolvedValue({ blob: new Blob(['synthetic CSV']), filename: 'synthetic.csv' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('synthetic six-tab report', () => {
  it('shows nineteen metrics, honest null reasons and keyboard-operable tabs', () => {
    const { container } = render(<Report job={job} ownerId="synthetic-owner" />)
    expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['收益概览', '交易详情', '持仓详情', '账户详情', '输出日志', '性能分析'])
    expect(container.querySelectorAll('.lab-report-metrics > div')).toHaveLength(19)
    expect(screen.getByText('短样本不可计算')).toBeVisible()
    expect(screen.getByText('未经 ZKP 验证')).toBeVisible()
    expect(screen.getByText('耗时 2.00 秒')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('tab', { name: '收益概览' }), { key: 'End' })
    expect(screen.getByRole('tab', { name: '性能分析' })).toHaveFocus()
    expect(screen.getByText('该次回测未开启性能分析。')).toBeVisible()
    expect(labMultiApi.reportRows).not.toHaveBeenCalled()
  })

  it('opens the annual table with partial-year coverage and exports the full annual report', async () => {
    render(<Report job={job} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByRole('button', { name: '查看年度收益' }))
    const annual = screen.getByRole('dialog', { name: '策略年度收益' })
    expect(within(annual).getByText('2025（部分年度）')).toBeVisible()
    expect(within(annual).getByText('2025-01-02 至 2025-01-06')).toBeVisible()
    fireEvent.click(within(annual).getByRole('button', { name: '下载年度收益 CSV' }))
    await waitFor(() => expect(labMultiApi.downloadReport).toHaveBeenCalledWith('synthetic-owner', job.id, 'annual', {}, expect.any(AbortSignal)))
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    fireEvent.click(within(annual).getByRole('button', { name: '关闭策略年度收益' }))
    expect(screen.queryByRole('dialog', { name: '策略年度收益' })).toBeNull()
  })

  it('closing a nested annual dialog keeps the full report open', () => {
    render(<Report job={job} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByRole('button', { name: '查看完整报告' }))
    const full = screen.getByRole('dialog', { name: '完整回测报告' })
    fireEvent.click(within(full).getByRole('button', { name: '查看年度收益' }))
    const annual = screen.getByRole('dialog', { name: '策略年度收益' })
    fireEvent.click(within(annual).getByRole('button', { name: '关闭策略年度收益' }))
    expect(screen.queryByRole('dialog', { name: '策略年度收益' })).toBeNull()
    expect(screen.getByRole('dialog', { name: '完整回测报告' })).toBeVisible()
    expect(within(full).getByRole('tab', { name: '收益概览' })).toBeVisible()
  })

  it('shares graph selection by keyboard, supports log NAV and offers a tabular alternative', () => {
    render(<Report job={job} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByLabelText('对数轴'))
    expect(screen.getByText(/对数轴对每条曲线的 1＋显示收益取对数/)).toBeVisible()
    const line = screen.getByRole('img', { name: /累计收益曲线/ })
    fireEvent.keyDown(line, { key: 'End' })
    expect(screen.getByText('2025/01/06')).toBeVisible()
    expect(line.querySelector('path')?.getAttribute('d')).not.toMatch(/NaN|Infinity/)
    fireEvent.click(screen.getByRole('button', { name: '查看图表数据' }))
    expect(screen.getByRole('table', { name: /图表数据/ })).toBeVisible()
    fireEvent.change(screen.getByLabelText('图表起日'), { target: { value: '2025-01-06' } })
    expect(screen.getByRole('table', { name: /图表数据.*1 个交易日/ })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '重置范围' }))
    expect(screen.getByRole('table', { name: /图表数据.*3 个交易日/ })).toBeVisible()
    fireEvent.change(screen.getByLabelText('图表起日'), { target: { value: '2025-01-07' } })
    fireEvent.change(screen.getByLabelText('图表止日'), { target: { value: '2025-01-02' } })
    expect(screen.getByRole('alert')).toHaveTextContent('图表止日不能早于起日')
  })

  it('disables logarithmic scaling for nonpositive values without replacing null benchmark data', () => {
    const noBenchmark = { ...report, benchmark: null, series: report.series.map(point => ({ ...point, strategy_return: -1, net_value: 0, benchmark_return: null, excess_return: null })) }
    render(<Report job={{ ...job, result: { ...job.result!, report: noBenchmark } }} ownerId="synthetic-owner" />)
    expect(screen.getByLabelText('对数轴')).toBeDisabled()
    expect(screen.getByText('未设置基准')).toBeVisible()
    expect(screen.getByText(/部分曲线不满足 1＋显示收益 > 0/)).toBeVisible()
    expect(screen.queryByText('基准累计收益')).toBeNull()
  })

  it('shows zero drawdown for a successful monotonically increasing report', () => {
    const noDrawdown = { ...report, drawdown: null }
    render(<Report job={{ ...job, result: { ...job.result!, report: noDrawdown } }} ownerId="synthetic-owner" />)
    expect(screen.getByText('最大回撤 0.00%')).toBeVisible()
    expect(screen.queryByText('最大回撤 不可计算')).toBeNull()
    expect(screen.queryByText('最大回撤区间')).toBeNull()
  })

  it('disables the log axis when arithmetic excess is below minus one despite positive asset NAVs', () => {
    const excessOutsideDomain = { ...report, series: report.series.map(point => ({ ...point, net_value: 1.02, strategy_return: .02, benchmark_return: 1.5, excess_return: -1.48 })) }
    render(<Report job={{ ...job, result: { ...job.result!, report: excessOutsideDomain } }} ownerId="synthetic-owner" />)
    expect(screen.getByLabelText('对数轴')).toBeDisabled()
    expect(screen.getByText(/部分曲线不满足 1＋显示收益 > 0/)).toBeVisible()
    expect(screen.getByText(/算术超额收益不是几何超额净值/)).toBeVisible()
    expect(screen.queryByText(/存在非正净值/)).toBeNull()
    const line = screen.getByRole('img', { name: /累计收益曲线/ })
    expect(line.querySelector('path')?.getAttribute('d')).not.toMatch(/NaN|Infinity/)
  })

  it('uses server pagination and exports all applied matches rather than the visible page', async () => {
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('交易详情')
    expect(await screen.findByText('合成标的甲')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(labMultiApi.reportRows).toHaveBeenLastCalledWith('synthetic-owner', job.id, 'trades', expect.objectContaining({ offset: 50, limit: 50 }), expect.any(AbortSignal)))
    fireEvent.change(screen.getByLabelText('证券代码'), { target: { value: '600519.ss' } })
    fireEvent.change(screen.getByLabelText('交易方向'), { target: { value: 'buy' } })
    fireEvent.change(screen.getByLabelText('明细起日'), { target: { value: '2025-01-02' } })
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    await waitFor(() => expect(labMultiApi.reportRows).toHaveBeenLastCalledWith('synthetic-owner', job.id, 'trades', expect.objectContaining({ offset: 0, symbol: '600519.SS', side: 'buy', start: '2025-01-02' }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByLabelText('显示佣金、税费与原生标识'))
    expect(screen.getByRole('columnheader', { name: '佣金' })).toBeVisible()
    expect(screen.getByText('开', { selector: 'td' })).toBeVisible()
    expect(screen.getByText('synthetic-fill')).toBeVisible()
    await waitFor(() => expect(screen.getByRole('button', { name: '导出全部筛选结果' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '导出全部筛选结果' }))
    await waitFor(() => expect(labMultiApi.downloadReport).toHaveBeenCalled())
    const exportQuery = vi.mocked(labMultiApi.downloadReport).mock.calls[0][3]
    expect(exportQuery).toMatchObject({ symbol: '600519.SS', side: 'buy', start: '2025-01-02' })
    expect(exportQuery).not.toHaveProperty('offset')
    expect(exportQuery).not.toHaveProperty('limit')
  })

  it('distinguishes failed detail reads from empty results and retries the same query', async () => {
    vi.mocked(labMultiApi.reportRows).mockRejectedValueOnce(new Error('合成读取失败')).mockResolvedValueOnce(page([], 0))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('账户详情')
    expect(await screen.findByRole('alert')).toHaveTextContent('合成读取失败')
    fireEvent.click(screen.getByRole('button', { name: '重试读取明细' }))
    expect(await screen.findByText('当前筛选条件下暂无记录。')).toBeVisible()
    expect(labMultiApi.reportRows).toHaveBeenCalledTimes(2)
  })

  it('filters log levels, reverses order, reports quotas and renders untrusted messages as text', async () => {
    const logs: LabReportRow[] = [{ sequence: 1, time: days[0], level: 'WARN', source: 'strategy', line: 12, message: '<img src=x onerror=alert(1)>' }]
    vi.mocked(labMultiApi.reportRows).mockResolvedValue({ ...page(logs, 1), logs_truncated: true })
    const { container } = render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('输出日志')
    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeVisible()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/部分内容未保留/)).toBeVisible()
    expect(screen.getByText(/第 12 行/)).toBeVisible()
    fireEvent.click(screen.getByLabelText('DEBUG'))
    await waitFor(() => expect(labMultiApi.reportRows).toHaveBeenLastCalledWith('synthetic-owner', job.id, 'logs', expect.objectContaining({ levels: 'INFO,WARN,ERROR' }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByLabelText('倒序'))
    await waitFor(() => expect(labMultiApi.reportRows).toHaveBeenLastCalledWith('synthetic-owner', job.id, 'logs', expect.objectContaining({ descending: true }), expect.any(AbortSignal)))
    for (const level of ['INFO', 'WARN', 'ERROR']) fireEvent.click(screen.getByLabelText(level))
    expect(screen.getByText('未选择日志等级。')).toBeVisible()
    expect(screen.getByRole('button', { name: '下载日志' })).toBeDisabled()
  })

  it('keeps diagnostic-only jobs honest while allowing their recorded logs', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ sequence: 1, time: days[0], level: 'ERROR', source: 'strategy', message: '合成错误日志' }], 1))
    const diagnostic = { ...report, metrics: [], series: [], annual_returns: [], drawdown: null }
    render(<Report job={{ ...job, status: 'failed', error: '策略执行失败', result: null, report: diagnostic }} ownerId="synthetic-owner" />)
    expect(screen.getByText('本次没有完整的经济结果')).toBeVisible()
    expect(screen.queryByText('期末权益')).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent('策略执行失败')
    openTab('输出日志')
    expect(await screen.findByText('合成错误日志')).toBeVisible()
  })

  it('aborts stale requests when switching job identity and does not leak another history record', async () => {
    let finish!: (value: LabReportPage) => void
    vi.mocked(labMultiApi.reportRows).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValue(page([{ ...trade, name: '合成标的乙' }]))
    const { rerender } = render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('交易详情')
    const signal = vi.mocked(labMultiApi.reportRows).mock.calls[0][4]
    rerender(<Report job={{ ...job, id: 'synthetic-job-b' }} ownerId="synthetic-owner" />)
    expect(signal?.aborted).toBe(true)
    openTab('交易详情')
    expect(await screen.findByText('合成标的乙')).toBeVisible()
    await act(async () => finish(page([{ ...trade, name: '不应出现的旧记录' }])))
    expect(screen.queryByText('不应出现的旧记录')).toBeNull()
  })

  it('loads the frozen source, handles a failed download and prevents duplicate concurrent downloads', async () => {
    let complete!: (file: { blob: Blob; filename: string }) => void
    vi.mocked(labMultiApi.downloadReport).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    render(<Report job={job} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByRole('button', { name: '查看本次源码' }))
    const source = screen.getByRole('dialog', { name: '本次运行源码' })
    expect(await within(source).findByText('# fixed synthetic source')).toBeVisible()
    expect(labMultiApi.reportSource).toHaveBeenCalledWith('synthetic-owner', job.id, expect.any(AbortSignal))
    fireEvent.click(within(source).getByRole('button', { name: '关闭本次运行源码' }))
    fireEvent.click(screen.getByRole('button', { name: '下载回测快照' }))
    fireEvent.click(screen.getByRole('button', { name: '正在下载…' }))
    expect(labMultiApi.downloadReport).toHaveBeenCalledTimes(1)
    await act(async () => complete({ blob: new Blob(['synthetic']), filename: 'snapshot.json' }))
    vi.mocked(labMultiApi.downloadReport).mockRejectedValueOnce(new Error('合成下载失败'))
    fireEvent.click(screen.getByRole('button', { name: '下载回测快照' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('合成下载失败')
  })

  it('offers a wide native dialog and keeps tab identifiers unique across reports', () => {
    const { container } = render(<><Report job={job} ownerId="synthetic-owner" /><Report job={{ ...job, id: 'synthetic-job-b' }} ownerId="synthetic-owner" /></>)
    const ids = [...container.querySelectorAll('[role=tab]')].map(element => element.id)
    expect(new Set(ids).size).toBe(ids.length)
    fireEvent.click(screen.getAllByRole('button', { name: '查看完整报告' })[0])
    const expanded = screen.getByRole('dialog', { name: '完整回测报告' })
    expect(expanded).toBeVisible()
    expect(within(expanded).getByRole('tab', { name: '收益概览' })).toBeVisible()
    fireEvent.click(within(expanded).getByRole('button', { name: '关闭完整回测报告' }))
    expect(screen.queryByRole('dialog', { name: '完整回测报告' })).toBeNull()
  })

  it('preserves legacy native data and clearly marks unavailable report tables', async () => {
    render(<LabMultiBacktestResult job={{ ...job, result: { ...job.result!, report: undefined, native_metrics: { sharpe: null } } }} ownerId="synthetic-owner" />)
    expect(screen.getByText(/历史结果未记录新版报告数据/)).toBeVisible()
    fireEvent.click(screen.getByText('成交明细（0）'))
    expect(screen.getByText('暂无成交。')).toBeVisible()
    openTab('持仓详情')
    expect(screen.getByText(/历史回测未记录新版持仓详情/)).toBeVisible()
    expect(labMultiApi.reportRows).not.toHaveBeenCalled()
    openTab('收益概览')
    expect(await screen.findByText('历史权益曲线')).toBeVisible()
  })

  it.each([['close', '平'], ['close_today', '平今'], ['close_yesterday', '平昨']])('translates native position effect %s without exposing the raw enum', async (effect, label) => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ ...trade, position_effect: effect }]))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('交易详情')
    expect(await screen.findByText(label, { selector: 'td' })).toBeVisible()
    expect(screen.queryByText(effect, { selector: 'td' })).toBeNull()
  })

  it('labels native position PnL and unavailable sellable shares without inventing realized profit', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ time: days[0], symbol: '600519.SS', name: '合成持仓', last_price: 11, direction: 'long', quantity: 100, avg_price: 10, market_value: 1100, pnl: 100, fee: 5, sellable: null }], 1))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('持仓详情')
    expect(await screen.findByText('合成持仓')).toBeVisible()
    expect(screen.getByRole('columnheader', { name: '持仓浮盈亏' })).toBeVisible()
    expect(screen.getByRole('columnheader', { name: '当日费用' })).toBeVisible()
    expect(screen.getByText('+100.0000')).toBeVisible()
    expect(screen.getByText(/不是累计已实现盈亏/)).toBeVisible()
    expect(screen.queryByRole('columnheader', { name: '累计已实现盈亏' })).toBeNull()
  })

  it('preserves zero-quantity receivable positions and displays their native dividend amount', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ time: days[0], symbol: '600519.SS', name: '合成应收记录', last_price: null, direction: 'long', quantity: 0, avg_price: null, market_value: 0, dividend_receivable: 123.45, pnl: null, fee: 0, sellable: 0 }], 1))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('持仓详情')
    const row = (await screen.findByText('合成应收记录')).closest('tr')!
    const headings = within(screen.getByRole('table', { name: /持仓详情/ })).getAllByRole('columnheader')
    const quantityColumn = headings.findIndex(heading => heading.textContent === '持仓数量')
    const receivableColumn = headings.findIndex(heading => heading.textContent === '应收分红')
    expect(within(row).getAllByRole('cell')[quantityColumn]).toHaveTextContent(/^0$/)
    expect(within(row).getAllByRole('cell')[receivableColumn]).toHaveTextContent('123.4500')
    expect(screen.getByText(/数量为零但仍有应收分红的记录会保留/)).toBeVisible()
    expect(screen.getByText('显示 1–1 / 1 条')).toBeVisible()
  })

  it('exposes all account funding components without recalculating native equity from only cash and market value', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ time: days[0], account_type: 'stock', cash: 800, equity: 1548, market_value: 500, margin: 0, fee: 5, daily_pnl: 10, frozen_cash: 100, dividend_receivable: 120, cash_liabilities: 20, cash_liabilities_interest: 2, pending_cash_flow: 50 }], 1))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('账户详情')
    expect(await screen.findByText('1,548.0000')).toBeVisible()
    expect(screen.queryByRole('columnheader', { name: '冻结资金' })).toBeNull()
    fireEvent.click(screen.getByLabelText('显示资金组成'))
    for (const label of ['冻结资金', '应收分红', '现金负债', '负债利息', '待到账申赎']) expect(screen.getByRole('columnheader', { name: label })).toBeVisible()
    const table = screen.getByRole('table', { name: /账户详情/ })
    const headings = within(table).getAllByRole('columnheader')
    const row = within(table).getAllByRole('row')[1]
    for (const [label, value] of [['冻结资金', '100.0000'], ['应收分红', '120.0000'], ['现金负债', '20.0000'], ['负债利息', '2.0000'], ['待到账申赎', '50.0000']]) {
      expect(within(row).getAllByRole('cell')[headings.findIndex(heading => heading.textContent === label)]).toHaveTextContent(value)
    }
    expect(screen.getByText(/不能仅由可用资金＋市值推算/)).toBeVisible()
    expect(labMultiApi.reportRows).toHaveBeenCalledTimes(1)
  })

  it('shows null or missing legacy account components as unavailable rather than zero', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue(page([{ time: days[0], account_type: 'stock', cash: 800, equity: 1300, market_value: 500, margin: 0, fee: 0, daily_pnl: 0, frozen_cash: null, dividend_receivable: null }], 1))
    render(<Report job={job} ownerId="synthetic-owner" />)
    openTab('账户详情')
    await screen.findByText('1,300.0000')
    fireEvent.click(screen.getByLabelText('显示资金组成'))
    const table = screen.getByRole('table', { name: /账户详情/ })
    const row = within(table).getAllByRole('row')[1]
    expect(within(row).getAllByRole('cell').filter(cell => cell.textContent === '—')).toHaveLength(5)
    expect(screen.getByText(/未记录或不适用字段显示“—”，不补零/)).toBeVisible()
  })

  it('uses recorded legacy trades without pretending final positions are daily history', async () => {
    render(<LabMultiBacktestResult job={{ ...job, result: { ...job.result!, report: undefined } }} ownerId="synthetic-owner" />)
    openTab('交易详情')
    expect(await screen.findByText('合成标的甲')).toBeVisible()
    expect(labMultiApi.reportRows).toHaveBeenCalledWith('synthetic-owner', job.id, 'trades', expect.any(Object), expect.any(AbortSignal))
    openTab('账户详情')
    expect(screen.getByText(/历史回测未记录新版账户详情/)).toBeVisible()
    expect(labMultiApi.reportRows).toHaveBeenCalledTimes(1)
  })

  it('renders an undefined annual strategy return as unavailable rather than zero', () => {
    const annualReport = { ...report, annual_returns: [{ ...report.annual_returns[0], strategy: null, benchmark: null }] }
    render(<Report job={{ ...job, result: { ...job.result!, report: annualReport } }} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByRole('button', { name: '查看年度收益' }))
    const annual = screen.getByRole('dialog', { name: '策略年度收益' })
    expect(within(annual).getAllByRole('cell').filter(cell => cell.textContent === '—')).toHaveLength(2)
    expect(within(annual).queryByText('0.00%')).toBeNull()
  })

  it('handles a cancelled diagnostic-only run and unavailable tables without a fabricated balance', async () => {
    vi.mocked(labMultiApi.reportRows).mockResolvedValue({ ...page([], 0), recorded: false })
    render(<Report job={{ ...job, status: 'cancelled', progress: null, result: null, report: { ...report, metrics: [], series: [], annual_returns: [] } }} ownerId="synthetic-owner" />)
    expect(screen.getByText('本次没有完整的经济结果')).toBeVisible()
    expect(screen.queryByText('10,400.0000')).toBeNull()
    openTab('持仓详情')
    expect(await screen.findByText(/未记录此类明细/)).toBeVisible()
  })

  it('retries frozen-source failures and rejects invalid date filters before fetching', async () => {
    vi.mocked(labMultiApi.reportSource).mockRejectedValueOnce(new Error('合成源码读取失败'))
    render(<Report job={job} ownerId="synthetic-owner" />)
    fireEvent.click(screen.getByRole('button', { name: '查看本次源码' }))
    const source = screen.getByRole('dialog', { name: '本次运行源码' })
    expect(await within(source).findByText('合成源码读取失败')).toBeVisible()
    fireEvent.click(within(source).getByRole('button', { name: '重试读取源码' }))
    expect(await within(source).findByText('# fixed synthetic source')).toBeVisible()
    fireEvent.click(within(source).getByRole('button', { name: '关闭本次运行源码' }))
    openTab('交易详情')
    await screen.findByText('合成标的甲')
    fireEvent.change(screen.getByLabelText('明细起日'), { target: { value: '2025-01-06' } })
    fireEvent.change(screen.getByLabelText('明细止日'), { target: { value: '2025-01-02' } })
    expect(screen.getByRole('button', { name: '应用筛选' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('明细止日不能早于起日')
    expect(labMultiApi.reportRows).toHaveBeenCalledTimes(1)
  })

  it('keeps cancelled progress indeterminate and does not invent a report', () => {
    render(<Report job={{ ...job, status: 'running', progress: null, result: null }} ownerId="synthetic-owner" />)
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('value')
    expect(screen.getByText('回测尚未完成')).toBeVisible()
  })
})

it('offers only frozen benchmark settings and clears the benchmark when returning to Atlas', () => {
  const change = vi.fn()
  render(<LabMultiBacktestForm value={{ ...job.settings, benchmark: '000300.SS' }} assets={[]} onChange={change} coverage={null} coverageBusy={false} coverageError="" onCoverage={vi.fn()} />)
  expect(screen.getByLabelText('收益基准')).toHaveValue('000300.SS')
  fireEvent.change(screen.getByLabelText('收益基准'), { target: { value: '000905.SS' } })
  expect(change).toHaveBeenLastCalledWith({ benchmark: '000905.SS' })
  expect(screen.getByText(/缺少覆盖时会明确提示/)).toBeVisible()
  fireEvent.change(screen.getByLabelText('回测引擎'), { target: { value: 'atlas_portfolio' } })
  expect(change).toHaveBeenLastCalledWith({ engine_id: 'atlas_portfolio', benchmark: null })
})
