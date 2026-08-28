import { memo, useEffect, useRef } from 'react'
import { ColorType, createChart, HistogramSeries, LineSeries, type UTCTimestamp } from 'lightweight-charts'
import type { EquityPoint } from '../types'

export const EquityChart = memo(function EquityChart({ points }: { points: EquityPoint[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current || points.length === 0) return
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#111821' }, textColor: '#8b98a8' },
      grid: { vertLines: { color: 'rgba(37,49,64,.35)' }, horzLines: { color: 'rgba(37,49,64,.45)' } },
      rightPriceScale: { borderColor: '#253140' },
      timeScale: { borderColor: '#253140', timeVisible: true },
    })
    const equity = chart.addSeries(LineSeries, { color: '#22c7a9', lineWidth: 2, priceLineVisible: false }, 0)
    const benchmark = chart.addSeries(LineSeries, { color: '#64748b', lineWidth: 1, priceLineVisible: false }, 0)
    const drawdown = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'percent' } }, 1)
    equity.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.equity })))
    benchmark.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.benchmark })))
    drawdown.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.drawdown * 100, color: 'rgba(255,90,103,.55)' })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [points])
  return <div className="equity-chart" ref={ref} aria-label="权益、基准与回撤曲线" />
})
