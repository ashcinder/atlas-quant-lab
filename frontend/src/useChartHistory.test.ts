import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useChartHistory } from './useChartHistory'
import type { Bar } from './types'

const bar = (time: number, close = 10): Bar => ({ time, open: 10, high: 11, low: 9, close, volume: 1 })
afterEach(cleanup)

it('loads one page at a time, merges overlapping rows and keeps history on live refresh', async () => {
  let resolve!: (bars: Bar[]) => void
  const fetch = vi.fn().mockImplementation(() => new Promise<Bar[]>(done => { resolve = done }))
  const { result, rerender } = renderHook(({ bars }) => useChartHistory(bars, 'btc', fetch), { initialProps: { bars: [bar(3), bar(4)] } })
  let pending!: Promise<void>
  act(() => { pending = result.current.load(); void result.current.load() })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toBe(3)
  await act(async () => { resolve([bar(2), bar(1), bar(2), bar(3, 99)]); await pending })
  expect(result.current.bars.map(row => row.time)).toEqual([1, 2, 3, 4])
  expect(result.current.bars[2].close).toBe(10)
  rerender({ bars: [bar(4, 10.5), bar(5)] })
  expect(result.current.bars.map(row => row.time)).toEqual([1, 2, 3, 4, 5])
  expect(result.current.bars[3].close).toBe(10.5)
})

it('cancels stale history when the asset, interval, source or backtest identity changes', async () => {
  let resolve!: (bars: Bar[]) => void
  const fetch = vi.fn().mockImplementation(() => new Promise<Bar[]>(done => { resolve = done }))
  const { result, rerender } = renderHook(({ key, bars }) => useChartHistory(bars, key, fetch), { initialProps: { key: 'btc:1d:binance', bars: [bar(3)] } })
  let pending!: Promise<void>
  act(() => { pending = result.current.load() })
  const signal: AbortSignal = fetch.mock.calls[0][1]
  rerender({ key: 'aapl:1h:sina', bars: [bar(7)] })
  expect(signal.aborted).toBe(true)
  await act(async () => { resolve([bar(1)]); await pending })
  expect(result.current.bars.map(row => row.time)).toEqual([7])
  expect(result.current.status).toBe('idle')
})

it('stops automatically at a source boundary and requires an explicit retry after a failure', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error('上游暂不可用')).mockResolvedValueOnce([])
  const { result } = renderHook(() => useChartHistory([bar(3)], 'btc', fetch))
  await act(async () => { await result.current.load() })
  expect(result.current.status).toBe('error')
  expect(result.current.bars).toEqual([bar(3)])
  await act(async () => { await result.current.load() })
  expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { await result.current.load(true) })
  expect(result.current.status).toBe('end')
  await act(async () => { await result.current.load() })
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('does not load history during replay or without a supported source', async () => {
  const fetch = vi.fn()
  const replay = renderHook(() => useChartHistory([bar(3)], 'btc', fetch, false))
  await act(async () => { await replay.result.current.load() })
  const unsupported = renderHook(() => useChartHistory([bar(3)], 'demo'))
  await act(async () => { await unsupported.result.current.load() })
  expect(fetch).not.toHaveBeenCalled()
})

it('cancels a pending page on replay and can load again after leaving replay', async () => {
  let resolve!: (bars: Bar[]) => void
  const fetch = vi.fn().mockImplementationOnce(() => new Promise<Bar[]>(done => { resolve = done })).mockResolvedValueOnce([bar(2)])
  const { result, rerender } = renderHook(({ enabled }) => useChartHistory([bar(3)], 'btc', fetch, enabled), { initialProps: { enabled: true } })
  let pending!: Promise<void>
  act(() => { pending = result.current.load() })
  const signal: AbortSignal = fetch.mock.calls[0][1]
  rerender({ enabled: false })
  expect(signal.aborted).toBe(true)
  expect(result.current.status).toBe('idle')
  await act(async () => { resolve([bar(1)]); await pending })
  expect(result.current.bars.map(row => row.time)).toEqual([3])
  rerender({ enabled: true })
  await act(async () => { await result.current.load() })
  expect(result.current.bars.map(row => row.time)).toEqual([2, 3])
})
