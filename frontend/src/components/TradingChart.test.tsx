import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Bar } from '../types'
import { TradingChart } from './TradingChart'

const mock = vi.hoisted(() => ({ overview: vi.fn(), getWindow: vi.fn(), range: { from: 0, to: 1 }, logical: undefined as undefined | (() => void), setRange: vi.fn(), fit: vi.fn() }))
vi.mock('../api', () => ({ api: { getChartOverview: mock.overview, getChartWindow: mock.getWindow } }))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: {}, LineSeries: {}, HistogramSeries: {}, ColorType: { Solid: 'solid' }, TickMarkType: {},
  createSeriesMarkers: () => ({ setMarkers: vi.fn() }),
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn(), applyOptions: vi.fn(), createPriceLine: vi.fn() }),
    applyOptions: vi.fn(), panes: () => [], remove: vi.fn(), subscribeCrosshairMove: vi.fn(), unsubscribeCrosshairMove: vi.fn(),
    timeScale: () => ({
      getVisibleLogicalRange: () => mock.range, setVisibleLogicalRange: mock.setRange, fitContent: mock.fit,
      getVisibleRange: () => null, subscribeVisibleTimeRangeChange: vi.fn(), unsubscribeVisibleTimeRangeChange: vi.fn(),
      subscribeVisibleLogicalRangeChange: (fn: () => void) => { mock.logical = fn }, unsubscribeVisibleLogicalRangeChange: vi.fn(),
    }),
  }),
}))
const bar = (time: number): Bar => ({ time, open: 10, high: 11, low: 9, close: 10, volume: 1 })
const base = { bars: [bar(3), bar(4)], indicators: {}, trades: [], chartType: 'candles' as const, interval: '15m' as const, datasetKey: 'btc', showVolume: false, showMacd: false, onShowVolume: vi.fn(), onShowMacd: vi.fn(), showRangeNavigator: true, onShowRangeNavigator: vi.fn() }
beforeEach(() => {
  mock.range = { from: 0, to: 1 }
  mock.fit.mockClear(); mock.setRange.mockClear()
  mock.overview.mockReset().mockResolvedValue([])
  mock.getWindow.mockReset()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { fn(0); return 0 })
  vi.stubGlobal('PointerEvent', MouseEvent)
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: vi.fn(), clear: vi.fn() })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const chart = () => screen.getByLabelText('金融K线、成交量与MACD技术指标图')

function dragEarlier() {
  fireEvent.pointerDown(chart(), { clientX: 30, clientY: 30, button: 0 })
  fireEvent.pointerUp(chart(), { clientX: 120, clientY: 30, button: 0 })
}

it('loads on a drag at the left edge and preserves the visible bars when history is prepended', async () => {
  const fetch = vi.fn().mockResolvedValue([bar(1), bar(2)])
  render(<TradingChart {...base} onLoadHistory={fetch} />)
  act(() => { mock.logical?.() })
  fireEvent.pointerDown(chart(), { clientX: 30, clientY: 30, button: 0 })
  fireEvent.pointerUp(chart(), { clientX: 30, clientY: 30, button: 0 })
  expect(fetch).not.toHaveBeenCalled()
  dragEarlier()
  await waitFor(() => expect(mock.setRange).toHaveBeenCalledWith({ from: 2, to: 3 }))
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(mock.fit).toHaveBeenCalledTimes(1)
})

it('retries on the next drag after a failed request without exposing a manual history button', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error('历史窗口不可用')).mockResolvedValueOnce([])
  render(<TradingChart {...base} onLoadHistory={fetch} />)
  expect(screen.queryByRole('button', { name: '加载更早行情' })).toBeNull()
  dragEarlier()
  await screen.findByText(/更早行情暂不可用：历史窗口不可用/)
  dragEarlier()
  await screen.findByText('已到该数据源的历史起点')
  expect(mock.fit).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('omits the removed range navigator', () => {
  render(<TradingChart {...base} />)
  expect(screen.queryByRole('button', { name: '区间导航' })).toBeNull()
  expect(screen.queryByRole('slider')).toBeNull()
})
