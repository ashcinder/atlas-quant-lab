import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import App from './App'
import type { Asset, BacktestResult, MarketData, Strategy } from './types'

vi.mock('./api', () => ({ api: { searchAssets: vi.fn(), getStrategies: vi.fn(), listRuns: vi.fn(), getRun: vi.fn(), getMarket: vi.fn(), runBacktest: vi.fn() } }))
vi.mock('./components/AlertDrawer', () => ({ AlertDrawer: () => null }))
vi.mock('./components/HistoryDrawer', () => ({ HistoryDrawer: ({ open, runs, onOpen }: { open: boolean; runs: { id: string }[]; onOpen: (run: { id: string }) => void }) => open ? <>{runs.map(run => <button key={run.id} onClick={() => onOpen(run)}>打开 {run.id}</button>)}</> : null }))
vi.mock('./components/ResultsPanel', () => ({ ResultsPanel: () => null }))
vi.mock('./components/StrategyPanel', () => ({ StrategyPanel: ({ codeContext, start, end, onStart, onEnd }: { codeContext?: React.ReactNode; start: string; end: string; onStart: (s: string) => void; onEnd: (s: string) => void }) => <>{codeContext}<input aria-label="开始" value={start} onChange={e => onStart(e.target.value)} /><input aria-label="结束" value={end} onChange={e => onEnd(e.target.value)} /></> }))
vi.mock('./components/TradingChart', () => ({ TradingChart: ({ bars, datasetKey, source, lastBarTime, isStale, onLoadHistory }: { bars: { time: number }[]; datasetKey: string; source?: string; lastBarTime?: number; isStale?: boolean; onLoadHistory?: (before: number, signal: AbortSignal) => Promise<unknown> }) => <><output data-testid="chart-bars" data-times={bars.map(bar => bar.time).join(',')} data-dataset={datasetKey} data-source={source} data-last-time={lastBarTime} data-stale={String(isStale)}>{bars.length}</output>{onLoadHistory && <button onClick={() => void onLoadHistory(300, new AbortController().signal)}>测试加载更早行情</button>}</> }))
vi.mock('./components/StrategyLabWorkspace', async () => {
  const { useState } = await import('react')
  return { StrategyLabWorkspace: function LabDraft({ onCustomResult,source }: { source:string; onCustomResult: (result: BacktestResult, code: {name:string;source:string;hash:string}) => void }) {
    const [draft, setDraft] = useState('')
    return <><output data-testid="lab-source">{source}</output><input aria-label="实验室草稿" value={draft} onChange={(event) => setDraft(event.target.value)} /><button onClick={() => onCustomResult({run_id:'code',created_at:'2026-01-01',asset:btc,interval:'1d',strategy,data_source:'binance',bars:market.bars,indicators:{},trades:[],equity:[],metrics:{},regime_metrics:{},warnings:[],source_note:null}, {name:'我的测试代码',source:'def target_bps(index, close, sma):\n return 5000',hash:'a'.repeat(64)})}>完成代码回测</button></>
  } }
})
vi.mock('./components/PortfolioWorkspace', async () => {
  const { useState } = await import('react')
  return { PortfolioWorkspace: function PortfolioDraft() {
    const [weight, setWeight] = useState('30')
    return <input aria-label="组合权重草稿" value={weight} onChange={(event) => setWeight(event.target.value)} />
  } }
})

const btc: Asset = { symbol: 'BTC-USD', name: '比特币', asset_class: 'crypto', exchange: 'CRYPTO', currency: 'USD', timezone: 'UTC', tags: [] }
const eth: Asset = { ...btc, symbol: 'ETH-USD', name: '以太坊' }
const aapl: Asset = { ...btc, symbol: 'AAPL', name: '苹果', asset_class: 'equity', exchange: 'NASDAQ' }
const strategy: Strategy = { id: 'sma_cross', name: 'SMA', category: '趋势', description: '', suitable_for: '', risk_level: '中', mode: 'single', parameters: [] }
const market: MarketData = { asset: btc, interval: '1d', source: 'binance', adjustment: 'raw', source_note: null, fetched_at: 1, last_bar_time: 1, cache_hit: false, is_stale: false, bars: [{ time: 1, open: 1, high: 1, low: 1, close: 1, volume: 1 }], indicators: {} }

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: vi.fn() })
  window.history.replaceState(null, '', '/#single')
  vi.mocked(api.searchAssets).mockResolvedValue([btc, eth])
  vi.mocked(api.getStrategies).mockResolvedValue([strategy])
  vi.mocked(api.listRuns).mockResolvedValue([])
  vi.mocked(api.getMarket).mockResolvedValue(market)
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('switches from Binance to automatic data when selecting a stock', async () => {
  vi.mocked(api.searchAssets).mockResolvedValue([btc, aapl])
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('行情数据源'), { target: { value: 'binance' } })
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, asset: aapl, source: 'sina' })
  fireEvent.click(screen.getByRole('button', { name: /AAPL/ }))
  expect(api.getMarket).toHaveBeenLastCalledWith('AAPL', 'equity', '1d', 'auto', 'auto', expect.any(Object))
  expect((screen.getByLabelText('行情数据源') as HTMLSelectElement).value).toBe('auto')
  expect((screen.getByRole('option', { name: '加密货币' }) as HTMLOptionElement).disabled).toBe(true)
  await waitFor(() => expect(screen.getByRole('button', { name: '运行回测' }).hasAttribute('disabled')).toBe(false))
  vi.mocked(api.runBacktest).mockReturnValue(new Promise(() => {}))
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AAPL', asset_class: 'equity', data_source: 'auto' }))
})

it.each(['auto', 'yahoo', 'demo'] as const)('preserves the compatible %s source when selecting a stock', async (source) => {
  vi.mocked(api.searchAssets).mockResolvedValue([btc, aapl])
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('行情数据源'), { target: { value: source } })
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, asset: aapl })
  fireEvent.click(screen.getByRole('button', { name: /AAPL/ }))
  expect(api.getMarket).toHaveBeenLastCalledWith('AAPL', 'equity', '1d', source, 'auto', expect.any(Object))
})

it('keeps Binance available when switching between cryptocurrencies', async () => {
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('行情数据源'), { target: { value: 'binance' } })
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, asset: eth })
  fireEvent.click(screen.getByRole('button', { name: /ETH-USD/ }))
  expect(api.getMarket).toHaveBeenLastCalledWith('ETH-USD', 'crypto', '1d', 'binance', 'auto', expect.any(Object))
  expect((screen.getByRole('option', { name: '加密货币' }) as HTMLOptionElement).disabled).toBe(false)
})

it('boots a saved stock with automatic data if its saved source is Binance', async () => {
  vi.mocked(localStorage.getItem).mockImplementation(key => key.startsWith('atlas-quant-preferences:') ? JSON.stringify({ symbol: 'AAPL', assetClass: 'equity', source: 'binance' }) : null)
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, asset: aapl, source: 'sina' })
  render(<App />)
  await waitFor(() => expect(api.getMarket).toHaveBeenCalled())
  expect(api.getMarket).toHaveBeenCalledWith('AAPL', 'equity', '1d', 'auto', 'auto', expect.any(Object))
  expect((screen.getByLabelText('行情数据源') as HTMLSelectElement).value).toBe('auto')
})

it('opens a stock history run with its own bars and clears the previous date range and incompatible source', async () => {
  vi.mocked(api.listRuns).mockResolvedValue([{ id: 'stock-history', mode: 'single', strategy_id: 'sma_cross', symbol: 'AAPL', created_at: '2026-01-01', total_return: 0, max_drawdown: 0, status: 'completed' }])
  vi.mocked(api.getRun).mockResolvedValue({ run_id: 'stock-history', created_at: '2026-01-01', asset: aapl, interval: '1d', strategy, data_source: 'sina:cache', source_note: null, bars: [{ ...market.bars[0], time: 300 }], indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] })
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('行情数据源'), { target: { value: 'binance' } })
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-03-01T08:00' } })
  fireEvent.click(screen.getByRole('button', { name: '回测历史' }))
  fireEvent.click(screen.getByRole('button', { name: '打开 stock-history' }))
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('300'))
  expect((screen.getByLabelText('开始') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('结束') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('行情数据源') as HTMLSelectElement).value).toBe('auto')
  expect(screen.getByTestId('chart-bars').getAttribute('data-dataset')).toContain('stock-history')
})

it.each(['raw', null] as const)('uses saved adjustment %s for history paging instead of current preferences', async adjustment => {
  vi.mocked(localStorage.getItem).mockImplementation(key => key.startsWith('atlas-quant-preferences:') ? JSON.stringify({ adjustment: 'forward' }) : null)
  vi.mocked(api.listRuns).mockResolvedValue([{ id: 'adjustment-history', mode: 'single', strategy_id: 'sma_cross', symbol: 'AAPL', created_at: '2026-01-01', total_return: 0, max_drawdown: 0, status: 'completed' }])
  vi.mocked(api.getRun).mockResolvedValue({ run_id: 'adjustment-history', created_at: '2026-01-01', asset: aapl, interval: '1d', adjustment, strategy, data_source: 'sina', source_note: null, bars: [{ ...market.bars[0], time: 300 }], indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] })
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.click(screen.getByRole('button', { name: '回测历史' }))
  fireEvent.click(screen.getByRole('button', { name: '打开 adjustment-history' }))
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('300'))
  if (adjustment == null) {
    expect(screen.queryByText('测试加载更早行情')).toBeNull()
    return
  }
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, asset: aapl, adjustment: 'raw', source: 'sina' })
  fireEvent.click(screen.getByText('测试加载更早行情'))
  await waitFor(() => expect(api.getMarket).toHaveBeenLastCalledWith('AAPL', 'equity', '1d', 'auto', 'raw', expect.objectContaining({ end: '1970-01-01T00:04:59.000Z' })))
})

describe('workspace continuity and request ownership', () => {
  it('retains lab and portfolio drafts across global navigation', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: '策略实验室' }))
    fireEvent.change(await screen.findByLabelText('实验室草稿'), { target: { value: 'private in-memory draft' } })
    fireEvent.click(screen.getByRole('button', { name: '投资组合' }))
    fireEvent.change(await screen.findByLabelText('组合权重草稿'), { target: { value: '45' } })
    fireEvent.click(screen.getByRole('button', { name: '策略实验室' }))
    expect((screen.getByLabelText('实验室草稿') as HTMLInputElement).value).toBe('private in-memory draft')
    fireEvent.click(screen.getByRole('button', { name: '投资组合' }))
    expect((screen.getByLabelText('组合权重草稿') as HTMLInputElement).value).toBe('45')
    expect(JSON.stringify(vi.mocked(localStorage.setItem).mock.calls)).not.toContain('private in-memory draft')
  })

  it('keeps catalogs usable when only history fails and offers a reconnect action', async () => {
    vi.mocked(api.listRuns).mockRejectedValue(new Error('history down'))
    render(<App />)
    expect(await screen.findByRole('button', { name: /ETH-USD/ })).toBeTruthy()
    expect(await screen.findByText(/暂时无法加载：回测历史/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '重新连接' })).toBeTruthy()
  })

  it('does not show the old instrument chart or late backtest under a new symbol', async () => {
    let resolveBacktest!: (result: BacktestResult) => void
    vi.mocked(api.runBacktest).mockReturnValue(new Promise((resolve) => { resolveBacktest = resolve }))
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
    fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
    vi.mocked(api.getMarket).mockReturnValue(new Promise(() => {}))
    fireEvent.click(screen.getByRole('button', { name: /ETH-USD/ }))
    expect(screen.getByTestId('chart-bars').textContent).toBe('0')
    await act(async () => { resolveBacktest({ run_id: 'old-btc-run', created_at: '2026-01-01', asset: btc, interval: '1d', strategy, data_source: 'binance', source_note: null, bars: market.bars, indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] }) })
    expect(screen.getByTestId('chart-bars').textContent).toBe('0')
  })
})


it('submits the chosen backtest range as UTC timestamps', async () => {
  vi.mocked(api.runBacktest).mockReturnValue(new Promise(() => {}))
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-03-01T08:00' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({ start: new Date('2025-01-01T08:00').toISOString(), end: new Date('2025-03-01T08:00').toISOString() }))
})
it('shows the backtest bars instead of recent market bars and changes the dataset key for the run', async () => {
  const historicalBars = [{ ...market.bars[0], time: 100 }, { ...market.bars[0], time: 200 }]
  vi.mocked(api.runBacktest).mockResolvedValue({ run_id: 'historical-run', created_at: '2026-01-01', asset: btc, interval: '1d', strategy, data_source: 'binance', source_note: null, bars: historicalBars, indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] })
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('1'))
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('100,200'))
  expect(screen.getByTestId('chart-bars').getAttribute('data-dataset')).toContain('historical-run')
})

it('keeps the historical chart and its metadata during live refresh and clears it on interval change', async () => {
  const timer = vi.spyOn(window, 'setInterval')
  const historicalBars = [{ ...market.bars[0], time: 100 }, { ...market.bars[0], time: 200 }]
  vi.mocked(api.runBacktest).mockResolvedValue({ run_id: 'historical-run', created_at: '2026-01-01', asset: btc, interval: '1d', strategy, data_source: 'binance:cache', source_note: null, bars: historicalBars, indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] })
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('100,200'))
  await waitFor(() => expect(screen.getByRole('button', { name: '运行回测' }).hasAttribute('disabled')).toBe(false))
  vi.mocked(api.getMarket).mockResolvedValue({ ...market, source: 'yahoo:stale-cache', is_stale: true, last_bar_time: 999 })
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const refreshTimer = timer.mock.calls.filter(([, delay]) => delay === 60_000).at(-1)
  expect(refreshTimer).toBeDefined()
  const refresh = refreshTimer![0] as () => void
  await act(async () => { refresh() })
  expect(api.getMarket).toHaveBeenLastCalledWith('BTC-USD', 'crypto', '1d', 'auto', 'auto', expect.objectContaining({ refresh: true }))
  expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('100,200')
  expect(screen.getByTestId('chart-bars').getAttribute('data-source')).toBe('binance:cache')
  expect(screen.getByTestId('chart-bars').getAttribute('data-last-time')).toBe('200')
  expect(screen.getByTestId('chart-bars').getAttribute('data-stale')).toBe('false')
  expect(screen.queryByText('真实缓存 · 刷新失败')).toBeNull()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '1时' })) })
  expect(screen.getByTestId('chart-bars').getAttribute('data-times')).toBe('1')
  expect(screen.getByTestId('chart-bars').getAttribute('data-dataset')).not.toContain('historical-run')
})

it('retains stale-cache warnings for the backtest and does not reuse its timestamp in portfolio mode', async () => {
  vi.mocked(api.runBacktest).mockResolvedValue({ run_id: 'stale-run', created_at: '2026-01-01', asset: btc, interval: '1d', strategy, data_source: 'binance:stale-cache', source_note: '刷新失败', bars: market.bars, indicators: {}, trades: [], equity: [], metrics: {}, regime_metrics: {}, warnings: [] })
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await waitFor(() => expect(screen.getByTestId('chart-bars').getAttribute('data-dataset')).toContain('stale-run'))
  expect(screen.getByTestId('chart-bars').getAttribute('data-stale')).toBe('true')
  expect(screen.getByText('真实缓存 · 刷新失败')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '投资组合' }))
  expect(await screen.findByLabelText('组合权重草稿')).toBeTruthy()
  expect(screen.getByText('等待K线')).toBeTruthy()
  expect(screen.queryByText('真实缓存 · 刷新失败')).toBeNull()
})
it('rejects reversed dates before starting the engine', async () => {
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-03-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(screen.getByText('回测开始时间必须早于结束时间')).toBeTruthy()
})

it('explains an impossible short daily range before requesting a backtest and accepts the same range at 15 minutes', async () => {
  vi.mocked(api.runBacktest).mockReturnValue(new Promise(() => {}))
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-01-11T18:00' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(screen.getByRole('alert').textContent).toContain('日线')
  expect(screen.getByRole('alert').textContent).toContain('至少需要40根')
  expect(screen.getByRole('alert').textContent).toContain('更短的K线周期')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '15分' })) })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({ interval: '15m', start: new Date('2025-01-01T08:00').toISOString(), end: new Date('2025-01-11T18:00').toISOString() }))
})

it('does not suggest an unavailable shorter interval for a short 15-minute range', async () => {
  vi.mocked(api.runBacktest).mockReturnValue(new Promise(() => {}))
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '15分' })) })
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-01-01T09:00' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(screen.getByRole('alert').textContent).toContain('15分钟')
  expect(screen.getByRole('alert').textContent).toContain('延长日期范围')
  expect(screen.getByRole('alert').textContent).not.toContain('更短的K线周期')
})


it('shows the code identity and reruns the same Python snapshot after lab navigation', async () => {
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.click(screen.getByRole('button', {name:'策略实验室'}))
  fireEvent.click(await screen.findByRole('button', {name:'完成代码回测'}))
  expect(await screen.findByText('我的测试代码')).toBeTruthy()
  expect(screen.getByText('当前回测 · 我编写的 Python')).toBeTruthy()
  vi.mocked(api.runBacktest).mockReturnValue(new Promise(() => {}))
  fireEvent.click(screen.getByRole('button', {name:'运行回测'}))
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({strategy_id:'python_bounded',python_source:'def target_bps(index, close, sma):\n return 5000',release_id:null}))
})

it('preserves a shell-owned Proof deep link when the hidden quant workspace boots', async () => {
  window.history.replaceState(null, '', '/#/proof/qzp_test')
  document.title = 'Proof 验证 · Atlas'
  render(<App />)
  await waitFor(() => expect(api.getMarket).toHaveBeenCalled())
  expect(window.location.hash).toBe('#/proof/qzp_test')
  expect(document.title).toBe('Proof 验证 · Atlas')
})


it('keeps the selected immutable history source when entering the Python workspace',async()=>{
 render(<App />)
 await waitFor(()=>expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
 fireEvent.change(screen.getByLabelText('行情数据源'),{target:{value:'huggingface'}})
 fireEvent.click(screen.getByRole('button',{name:'策略实验室'}))
 expect(await screen.findByTestId('lab-source')).toHaveProperty('textContent','huggingface')
})
