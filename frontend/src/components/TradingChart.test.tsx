import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Bar } from '../types'
import { TradingChart } from './TradingChart'

const mock = vi.hoisted(() => ({ range: { from: 0, to: 1 }, logical: undefined as undefined | (() => void), setRange: vi.fn(), fit: vi.fn() }))
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
const base = { bars: [bar(3), bar(4)], indicators: {}, trades: [], chartType: 'candles' as const, interval: '15m' as const, datasetKey: 'btc', showVolume: false, showMacd: false, onShowVolume: vi.fn(), onShowMacd: vi.fn() }
beforeEach(() => {
  mock.range = { from: 0, to: 1 }
  mock.fit.mockClear(); mock.setRange.mockClear()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { fn(0); return 0 })
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: vi.fn(), clear: vi.fn() })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('loads on user pan at the left edge and preserves the zoom and visible bars when history is prepended', async () => {
  const fetch = vi.fn().mockResolvedValue([bar(1), bar(2)])
  render(<TradingChart {...base} onLoadHistory={fetch} />)
  act(() => { mock.logical?.() })
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.pointerDown(screen.getByLabelText('金融K线、成交量与MACD技术指标图'))
  act(() => { mock.logical?.() })
  await waitFor(() => expect(mock.setRange).toHaveBeenCalledWith({ from: 2, to: 3 }))
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(mock.fit).toHaveBeenCalledTimes(1)
})

it('retains the existing chart and exposes a retry when older data fails to load', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error('历史窗口不可用')).mockResolvedValueOnce([])
  render(<TradingChart {...base} onLoadHistory={fetch} />)
  fireEvent.click(screen.getByRole('button', { name: '加载更早行情' }))
  await screen.findByText('更早行情暂不可用：历史窗口不可用')
  fireEvent.click(screen.getByRole('button', { name: '重试加载历史' }))
  await screen.findByText('该数据源未提供更早行情，可切换周期或来源')
  expect(mock.fit).toHaveBeenCalledTimes(1)
})
