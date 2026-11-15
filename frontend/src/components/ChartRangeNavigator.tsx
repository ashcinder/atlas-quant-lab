import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { X } from 'lucide-react'
import type { Bar, ChartOverviewPoint } from '../types'
import './chart-navigator.css'

export interface ChartIndexRange { from: number; to: number }

type DragTarget = 'from' | 'to' | 'window'

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function overviewPath(bars: ChartOverviewPoint[], start: number, end: number) {
  if (bars.length < 2) return ''
  const step = Math.ceil(bars.length / 240)
  const points: ChartOverviewPoint[] = []
  for (let start = 0; start < bars.length; start += step) {
    let low = start
    let high = start
    for (let index = start + 1; index < Math.min(start + step, bars.length); index += 1) {
      if (bars[index].close < bars[low].close) low = index
      if (bars[index].close > bars[high].close) high = index
    }
    for (const index of low === high ? [low] : [Math.min(low, high), Math.max(low, high)]) {
      points.push(bars[index])
    }
  }
  const first = bars[0]
  const last = bars[bars.length - 1]
  if (points[0].time !== first.time) points.unshift(first)
  if (points.at(-1)?.time !== last.time) points.push(last)
  const values = points.map(point => point.close)
  const min = Math.min(...values)
  const spread = Math.max(...values) - min
  return points.map(({ time, close }, point) =>
    `${point === 0 ? 'M' : 'L'}${((time - start) / (end - start) * 1000).toFixed(2)},${(spread ? 32 - (close - min) * 27 / spread : 18).toFixed(2)}`).join(' ')
}

interface Props {
  bars: Bar[]
  earliest: number
  latest: number
  visibleRange: ChartIndexRange | null
  overview: readonly ChartOverviewPoint[]
  formatTime: (time: number) => string
  onRangeChange: (range: ChartIndexRange) => void
  onLatest: (range: ChartIndexRange) => void
  onClose: () => void
}

export function ChartRangeNavigator({
  bars, earliest, latest, visibleRange, overview, formatTime, onRangeChange, onLatest, onClose,
}: Props) {
  const series = useMemo(() => {
    const points = new Map(overview.map(point => [point.time, point]))
    const step = Math.max(1, Math.floor(bars.length / 480))
    for (let index = 0; index < bars.length; index += step) points.set(bars[index].time, bars[index])
    const lastBar = bars.at(-1)
    if (lastBar) points.set(lastBar.time, lastBar)
    return overviewPath([...points.values()].sort((a, b) => a.time - b.time), earliest, latest)
  }, [bars, earliest, latest, overview])
  const drag = useRef<{ id: number; target: DragTarget; at: number; range: ChartIndexRange; next: ChartIndexRange } | null>(null)
  const [preview, setPreview] = useState<ChartIndexRange | null>(null)
  const selected = preview ?? visibleRange ?? { from: bars[0].time, to: bars.at(-1)!.time }
  const from = clamp(selected.from, earliest, latest - 1)
  const to = clamp(selected.to, from + 1, latest)
  const percent = (time: number) => `${(time - earliest) / (latest - earliest) * 100}%`

  function timeAt(event: PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const fraction = clamp((event.clientX - bounds.left) / Math.max(1, bounds.width), 0, 1)
    return Math.round(earliest + fraction * (latest - earliest))
  }

  function moveWindow(start: number, width: number) {
    const left = clamp(start, earliest, latest - width)
    return { from: left, to: left + width }
  }

  function moveEdge(edge: 'from' | 'to', time: number, anchor: ChartIndexRange) {
    return edge === 'from'
      ? { from: clamp(time, earliest, anchor.to - 1), to: anchor.to }
      : { from: anchor.from, to: clamp(time, anchor.from + 1, latest) }
  }

  function beginDrag(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0 || drag.current) return
    const at = timeAt(event)
    const edge = (event.target as HTMLElement).closest<HTMLElement>('[data-range-edge]')?.dataset.rangeEdge
    const target = edge === 'from' || edge === 'to' ? edge : 'window'
    const width = to - from
    const range = target === 'window' && (at < from || at > to)
      ? moveWindow(at - Math.round(width / 2), width) : { from, to }
    drag.current = { id: event.pointerId, target, at, range, next: range }
    event.currentTarget.setPointerCapture(event.pointerId)
    setPreview(range)
  }

  function updateDrag(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current
    if (!active || active.id !== event.pointerId) return
    const delta = timeAt(event) - active.at
    active.next = active.target === 'window'
      ? moveWindow(active.range.from + delta, active.range.to - active.range.from)
      : moveEdge(active.target, active.range[active.target] + delta, active.range)
    setPreview(active.next)
  }

  function finishDrag(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current
    if (!active || active.id !== event.pointerId) return
    drag.current = null
    setPreview(null)
    if (event.type === 'pointerup') onRangeChange(active.next)
  }

  function keyMove(event: KeyboardEvent<HTMLButtonElement>, edge: 'from' | 'to') {
    const current = edge === 'from' ? from : to
    const barStep = Math.max(1, (bars[1]?.time ?? bars[0].time + 60) - bars[0].time)
    const pageStep = Math.max(barStep, Math.round((to - from) / 10))
    const next = {
      ArrowLeft: current - barStep, ArrowDown: current - barStep,
      ArrowRight: current + barStep, ArrowUp: current + barStep,
      PageDown: current - pageStep, PageUp: current + pageStep, Home: earliest, End: latest,
    }[event.key]
    if (next === undefined) return
    event.preventDefault()
    onRangeChange(moveEdge(edge, next, { from, to }))
  }

  return <section className="chart-navigator" aria-label="K线区间导航">
    <div className="chart-navigator-header">
      <button type="button" className="chart-boundary" aria-label="查看最早行情" onClick={() => onRangeChange(moveWindow(earliest, to - from))}>
        <span>最早</span><time>{formatTime(earliest)}</time>
      </button>
      <div className="chart-navigator-end">
        <button type="button" className="chart-boundary" aria-label="回到最新行情" onClick={() => onLatest(moveWindow(latest - (to - from), to - from))}>
          <span>最新</span><time>{formatTime(latest)}</time>
        </button>
        <button type="button" className="chart-navigator-close" aria-label="关闭区间导航" onClick={onClose}><X size={15} /></button>
      </div>
    </div>
    <div className="chart-navigator-track" onPointerDown={beginDrag} onPointerMove={updateDrag}
      onPointerUp={finishDrag} onPointerCancel={finishDrag} onLostPointerCapture={finishDrag}>
      <svg viewBox="0 0 1000 36" preserveAspectRatio="none" aria-hidden="true">
        <path className="chart-navigator-line" d={series} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="chart-navigator-selection" style={{ left: percent(from), right: `${100 - (to - earliest) / (latest - earliest) * 100}%` }} aria-hidden="true" />
      {(['from', 'to'] as const).map(edge => {
        const time = edge === 'from' ? from : to
        return <button type="button" key={edge} data-range-edge={edge} role="slider"
          className="chart-navigator-handle" style={{ left: percent(time) }}
          aria-label={edge === 'from' ? '图表区间起点' : '图表区间终点'}
          aria-valuemin={edge === 'from' ? earliest : from + 1} aria-valuemax={edge === 'from' ? to - 1 : latest}
          aria-valuenow={time} aria-valuetext={formatTime(time)}
          onKeyDown={event => keyMove(event, edge)} />
      })}
    </div>
  </section>
}
