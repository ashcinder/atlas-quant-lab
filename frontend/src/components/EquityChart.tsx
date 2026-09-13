import { chartTheme } from '../theme'
import { memo, useEffect, useRef } from 'react'
import { ColorType, createChart, AreaSeries, LineSeries, type UTCTimestamp } from 'lightweight-charts'
import { formatNumber, formatPercent } from '../format'
import type { EquityPoint } from '../types'
import { bindChartTheme } from '../chartTheme'

export const EquityChart = memo(function EquityChart({ points }: { points: EquityPoint[] }) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const equityCaptionRef = useRef<HTMLDivElement>(null)
  const drawdownCaptionRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const container = canvasRef.current
    const wrap = wrapRef.current
    if (!container || !wrap || points.length === 0) return
    const theme = chartTheme()
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: theme.background },
        textColor: theme.text, fontSize: 11,
        panes: { separatorColor: theme.border, separatorHoverColor: theme.text, enableResize: true },
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.border } },
      rightPriceScale: { borderColor: theme.border },
      timeScale: { borderColor: theme.border, timeVisible: true },
    })
    const releaseTheme = bindChartTheme(chart)
    const equity = chart.addSeries(AreaSeries, { lineColor: theme.accent, topColor: 'rgba(8,126,120,.16)', bottomColor: 'rgba(8,126,120,.01)', lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0)
    const benchmark = chart.addSeries(LineSeries, { color: '#64748b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, 0)
    const drawdown = chart.addSeries(AreaSeries, { lineColor: '#d95d73', topColor: 'rgba(217,93,115,.04)', bottomColor: 'rgba(217,93,115,.22)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'percent' } }, 1)
    equity.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.equity })))
    benchmark.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.benchmark })))
    drawdown.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.drawdown * 100 })))
    equity.priceScale().applyOptions({ scaleMargins: { top: .24, bottom: .08 } })
    drawdown.priceScale().applyOptions({ scaleMargins: { top: .3, bottom: .06 } })
    const panes = chart.panes()
    panes[0]?.setStretchFactor(3)
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
      releaseTheme()
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
