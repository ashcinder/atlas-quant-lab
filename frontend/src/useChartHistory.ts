import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Bar } from './types'

export type LoadChartHistory = (before: number, signal: AbortSignal) => Promise<Bar[]>
type Status = 'idle' | 'loading' | 'end' | 'error'
interface History {
  key: string
  bars: Bar[]
  status: Status
  error?: string
}

function merge(older: Bar[], current: Bar[]) {
  const rows = new Map(older.map(bar => [bar.time, bar]))
  current.forEach(bar => rows.set(bar.time, bar))
  return [...rows.values()].sort((a, b) => a.time - b.time)
}

export function useChartHistory(bars: Bar[], datasetKey: string, fetchHistory?: LoadChartHistory, enabled = true) {
  const [history, setHistory] = useState<History>({ key: '', bars: [], status: 'idle' })
  const inFlight = useRef<AbortController | null>(null)
  const current = history.key === datasetKey ? history : undefined
  const combined = useMemo(() => merge(history.key === datasetKey ? history.bars : [], bars), [bars, datasetKey, history.key, history.bars])
  useEffect(() => () => {
    inFlight.current?.abort()
    inFlight.current = null
  }, [datasetKey, enabled])
  const load = useCallback(async (retry = false) => {
    if (!enabled || !fetchHistory || !combined.length || inFlight.current || current?.status === 'end' || (current?.status === 'error' && !retry)) return
    const before = combined[0].time
    const controller = new AbortController()
    inFlight.current = controller
    setHistory({ key: datasetKey, bars: current?.bars ?? [], status: 'loading' })
    controller.signal.addEventListener('abort', () => {
      setHistory(previous => previous.key === datasetKey && previous.status === 'loading' ? { ...previous, status: 'idle' } : previous)
    }, { once: true })
    try {
      const page = await fetchHistory(before, controller.signal)
      if (controller.signal.aborted) return
      const older = page.filter(bar => Number.isFinite(bar.time) && bar.time < before)
      setHistory({ key: datasetKey, bars: merge(combined, older), status: older.length ? 'idle' : 'end' })
    } catch (reason) {
      if (controller.signal.aborted) return
      setHistory({ key: datasetKey, bars: current?.bars ?? [], status: 'error', error: reason instanceof Error ? reason.message : '请稍后重试' })
    } finally {
      if (inFlight.current === controller) inFlight.current = null
    }
  }, [combined, current, datasetKey, enabled, fetchHistory])

  return { bars: combined, load, status: current?.status ?? 'idle', error: current?.error }
}
