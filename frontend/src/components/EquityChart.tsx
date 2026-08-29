import { memo, useEffect, useRef } from 'react'
import { ColorType, createChart, HistogramSeries, LineSeries, type UTCTimestamp } from 'lightweight-charts'
import { formatNumber, formatPercent } from '../format'
import type { EquityPoint } from '../types'

export const EquityChart = memo(function EquityChart({ points }: { points: EquityPoint[] }) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const equityCaptionRef = useRef<HTMLDivElement>(null)
  const drawdownCaptionRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const container = canvasRef.current
    const wrap = wrapRef.current
    if (!container || !wrap || points.length === 0) return
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#111821' },
        textColor: '#8b98a8',
        panes: { separatorColor: '#253140', separatorHoverColor: '#39485b', enableResize: true },
        attributionLogo: false,
      },
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
    const panes = chart.panes()
    panes[0]?.setStretchFactor(2)
    panes[1]?.setStretchFactor(1)
    const syncCaptions = () => {
      const wrapTop = wrap.getBoundingClientRect().top
      const place = (caption: HTMLDivElement | null, paneIndex: number) => {
        const pane = chart.panes()[paneIndex]?.getHTMLElement()
        if (!caption || !pane) return
        const desiredTop = pane.getBoundingClientRect().top - wrapTop + 5
        caption.style.transform = `translateY(${Math.max(4, desiredTop)}px)`
      }
      place(equityCaptionRef.current, 0)
      place(drawdownCaptionRef.current, 1)
    }
    const resizeObserver = new ResizeObserver(() => requestAnimationFrame(syncCaptions))
    resizeObserver.observe(container)
    container.addEventListener('pointerup', syncCaptions)
    chart.timeScale().fitContent()
    requestAnimationFrame(syncCaptions)
    return () => {
      resizeObserver.disconnect()
      container.removeEventListener('pointerup', syncCaptions)
      chart.remove()
    }
  }, [points])
  const latest = points.at(-1)
  return <div className="equity-chart" ref={wrapRef} aria-label="策略权益、基准权益与回撤曲线">
    <div className="equity-chart-canvas" ref={canvasRef} />
    <div className="result-pane-caption" ref={equityCaptionRef}>
      <strong>权益曲线</strong>
      <span><i className="strategy" />策略权益 {formatNumber(latest?.equity, 2)}</span>
      <span><i className="benchmark" />基准权益 {formatNumber(latest?.benchmark, 2)}</span>
    </div>
    <div className="result-pane-caption drawdown" ref={drawdownCaptionRef}>
      <strong>回撤曲线</strong>
      <small>相对历史权益峰值</small>
      <span>{formatPercent(latest?.drawdown)}</span>
    </div>
  </div>
})
