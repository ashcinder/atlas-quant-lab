import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import App from './App'
import type { Asset, BacktestResult, MarketData, Strategy } from './types'

vi.mock('./api', () => ({ api: { searchAssets: vi.fn(), getStrategies: vi.fn(), listRuns: vi.fn(), getMarket: vi.fn(), runBacktest: vi.fn() } }))
vi.mock('./components/AlertDrawer', () => ({ AlertDrawer: () => null }))
vi.mock('./components/HistoryDrawer', () => ({ HistoryDrawer: () => null }))
vi.mock('./components/ResultsPanel', () => ({ ResultsPanel: () => null }))
vi.mock('./components/StrategyPanel', () => ({ StrategyPanel: ({ start, end, onStart, onEnd }: { start: string; end: string; onStart: (s: string) => void; onEnd: (s: string) => void }) => <><input aria-label="开始" value={start} onChange={e => onStart(e.target.value)} /><input aria-label="结束" value={end} onChange={e => onEnd(e.target.value)} /></> }))
vi.mock('./components/TradingChart', () => ({ TradingChart: ({ bars }: { bars: unknown[] }) => <output data-testid="chart-bars">{bars.length}</output> }))
vi.mock('./components/StrategyLabWorkspace', async () => {
  const { useState } = await import('react')
  return { StrategyLabWorkspace: function LabDraft() {
    const [draft, setDraft] = useState('')
    return <input aria-label="实验室草稿" value={draft} onChange={(event) => setDraft(event.target.value)} />
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
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

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
it('rejects reversed dates before starting the engine', async () => {
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('chart-bars').textContent).toBe('1'))
  fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2025-03-01T08:00' } })
  fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2025-01-01T08:00' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(screen.getByText('回测开始时间必须早于结束时间')).toBeTruthy()
})
