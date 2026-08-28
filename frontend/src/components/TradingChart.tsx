import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Eye, EyeOff, Pause, Play, RotateCcw, StepForward, X } from 'lucide-react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type MouseEventParams,
  type SeriesMarker,
  TickMarkType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Bar, IndicatorPoint, Interval, Trade } from '../types'
import { formatNumber } from '../format'

interface Props {
  bars: Bar[]
  indicators: Record<string, IndicatorPoint[]>
  trades: Trade[]
  chartType: 'candles' | 'line'
  interval: Interval
  source?: string
  datasetKey: string
  lastBarTime?: number
  isStale?: boolean
  showVolume: boolean
  showMacd: boolean
  onShowVolume: (show: boolean) => void
  onShowMacd: (show: boolean) => void
}

interface ChartPayload {
  bars: Bar[]
  indicators: Record<string, IndicatorPoint[]>
  trades: Trade[]
}

interface ChartBinding {
  update: (payload: ChartPayload, fit: boolean) => void
}

interface ReplayAccount {
  cash: number
  quantity: number
  trades: Trade[]
}

function timeValue(time: Time): number {
  if (typeof time === 'number') return time
  if (typeof time === 'string') return Math.floor(Date.parse(time) / 1000)
  return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000)
}

function axisTime(time: Time, tickMarkType: TickMarkType, interval: Interval) {
  const date = new Date(timeValue(time) * 1000)
  if (tickMarkType === TickMarkType.Year) return String(date.getFullYear())
  if (tickMarkType === TickMarkType.Month) return `${date.getMonth() + 1}月`
  if (interval === '1d' || interval === '1wk' || tickMarkType === TickMarkType.DayOfMonth) {
    return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`
  }
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function chartOptions(interval: Interval) {
  return {
    autoSize: true,
    layout: {
    background: { type: ColorType.Solid, color: '#0b0f14' },
    textColor: '#8b98a8',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    panes: { separatorColor: '#253140', separatorHoverColor: '#39485b', enableResize: true },
    },
    grid: {
      vertLines: { color: 'rgba(37, 49, 64, 0.42)' },
      horzLines: { color: 'rgba(37, 49, 64, 0.52)' },
    },
    rightPriceScale: { borderColor: '#253140', minimumWidth: 104, ticksVisible: true },
    timeScale: {
      borderColor: '#314052', borderVisible: true, ticksVisible: true, minimumHeight: 32,
      visible: true, timeVisible: true, secondsVisible: false, rightOffset: 8,
      tickMarkFormatter: (time: Time, type: TickMarkType) => axisTime(time, type, interval),
    },
    localization: {
      locale: 'zh-CN',
      timeFormatter: (time: Time) => marketTime(timeValue(time)),
    },
    crosshair: {
      vertLine: { color: '#64748b', labelBackgroundColor: '#253140' },
      horzLine: { color: '#64748b', labelBackgroundColor: '#253140' },
    },
  }
}

function indicatorData(points: IndicatorPoint[] = []) {
  return points.filter((point) => point.value != null).map((point) => ({
    time: point.time as UTCTimestamp,
    value: point.value as number,
  }))
}

function latestIndicator(points: IndicatorPoint[] = []) {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    if (points[index].value != null) return points[index].value
  }
  return undefined
}

function marketTime(time?: number) {
  if (!time) return '等待行情'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(time * 1000))
}

function rangeTime(time: number, interval: Interval) {
  const date = new Date(time * 1000)
  const day = `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`
  if (interval === '1d' || interval === '1wk') return day
  return `${day} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export const TradingChart = memo(function TradingChart({
  bars, indicators, trades, chartType, interval, source, datasetKey, lastBarTime, isStale = false,
  showVolume, showMacd, onShowVolume, onShowMacd,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasWrapRef = useRef<HTMLDivElement>(null)
  const volumeCaptionRef = useRef<HTMLDivElement>(null)
  const macdCaptionRef = useRef<HTMLDivElement>(null)
  const timeStartRef = useRef<HTMLSpanElement>(null)
  const timeMiddleRef = useRef<HTMLSpanElement>(null)
  const timeEndRef = useRef<HTMLSpanElement>(null)
  const crosshairTimeRef = useRef<HTMLDivElement>(null)
  const bindingRef = useRef<ChartBinding | null>(null)
  const payloadRef = useRef<ChartPayload>({ bars: [], indicators: {}, trades: [] })
  const lastDatasetRef = useRef<string | null>(null)
  const lastBarCountRef = useRef(0)
  const [visibleIndicators, setVisibleIndicators] = useState(() => new Set(['sma20', 'sma50']))
  const [replayMode, setReplayMode] = useState(false)
  const [replayPlaying, setReplayPlaying] = useState(false)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayAccount, setReplayAccount] = useState<ReplayAccount>({ cash: 100_000, quantity: 0, trades: [] })
  const displayBars = useMemo(() => replayMode ? bars.slice(0, replayIndex + 1) : bars, [bars, replayIndex, replayMode])
  const replayTime = displayBars.at(-1)?.time ?? Number.POSITIVE_INFINITY
  const displayIndicators = useMemo(() => Object.fromEntries(Object.entries(indicators).map(([key, points]) => [key, replayMode ? points.filter((point) => point.time <= replayTime) : points])), [indicators, replayMode, replayTime])
  const displayTrades = useMemo(() => replayMode
    ? [...trades.filter((trade) => trade.time <= replayTime), ...replayAccount.trades]
    : trades, [replayAccount.trades, replayMode, replayTime, trades])
  const bindingKey = `${datasetKey}:${replayMode ? 'replay' : 'live'}`
  payloadRef.current = { bars: displayBars, indicators: displayIndicators, trades: displayTrades }
  const latest = displayBars.at(-1)
  const change = displayBars.length > 1 && latest ? latest.close / displayBars[displayBars.length - 2].close - 1 : 0
  const indicatorControls = useMemo(() => [
    { key: 'sma20', label: 'MA20' },
    { key: 'sma50', label: 'MA50' },
    { key: 'boll', label: 'BOLL' },
  ], [])

  useEffect(() => {
    setReplayMode(false)
    setReplayPlaying(false)
    setReplayIndex(0)
    setReplayAccount({ cash: 100_000, quantity: 0, trades: [] })
  }, [datasetKey])

  useEffect(() => {
    if (!replayMode || !replayPlaying) return
    const timer = window.setInterval(() => {
      setReplayIndex((current) => {
        if (current >= bars.length - 1) {
          setReplayPlaying(false)
          return current
        }
        return current + 1
      })
    }, 550)
    return () => window.clearInterval(timer)
  }, [bars.length, replayMode, replayPlaying])

  useEffect(() => {
    if (!replayMode) return
    localStorage.setItem(`atlas:replay:v1:${datasetKey}`, JSON.stringify({ replayIndex, replayAccount }))
  }, [datasetKey, replayAccount, replayIndex, replayMode])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const chart = createChart(container, chartOptions(interval))
    let setMainData: (nextBars: Bar[]) => void
    let setMarkers: (markers: SeriesMarker<Time>[]) => void

    if (chartType === 'candles') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#22c7a9', downColor: '#ff5a67', borderVisible: false,
        wickUpColor: '#22c7a9', wickDownColor: '#ff5a67', priceLineVisible: true,
      }, 0)
      const markerPlugin = createSeriesMarkers(series, [], { autoScale: true })
      setMainData = (nextBars) => series.setData(nextBars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        open: bar.open, high: bar.high, low: bar.low, close: bar.close,
      })))
      setMarkers = (markers) => markerPlugin.setMarkers(markers)
    } else {
      const series = chart.addSeries(LineSeries, { color: '#e6edf5', lineWidth: 2, priceLineVisible: true }, 0)
      const markerPlugin = createSeriesMarkers(series, [], { autoScale: true })
      setMainData = (nextBars) => series.setData(nextBars.map((bar) => ({
        time: bar.time as UTCTimestamp, value: bar.close,
      })))
      setMarkers = (markers) => markerPlugin.setMarkers(markers)
    }

    let nextPane = 1
    let volumePane = -1
    let macdPane = -1
    let setVolume: ((nextBars: Bar[]) => void) | undefined
    if (showVolume) {
      volumePane = nextPane++
      const volume = chart.addSeries(HistogramSeries, {
        title: 'VOL', priceFormat: { type: 'volume' }, priceScaleId: 'right', priceLineVisible: false, lastValueVisible: false,
      }, volumePane)
      setVolume = (nextBars) => volume.setData(nextBars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(34,199,169,.45)' : 'rgba(255,90,103,.45)',
      })))
    }
    const overlaySetters = new Map<string, (points: IndicatorPoint[]) => void>()
    const addOverlay = (key: string, color: string, width: 1 | 2 = 1) => {
      if (!visibleIndicators.has(key)) return
      const series = chart.addSeries(LineSeries, {
        color, lineWidth: width, priceLineVisible: false, lastValueVisible: false,
      }, 0)
      overlaySetters.set(key, (points) => series.setData(indicatorData(points)))
    }
    addOverlay('sma20', '#f3b451', 2)
    addOverlay('sma50', '#7aa2f7', 2)
    if (visibleIndicators.has('boll')) {
      addOverlay('boll_upper', '#8b98a8')
      addOverlay('boll_mid', '#64748b')
      addOverlay('boll_lower', '#8b98a8')
    }

    let setMacd: ((nextIndicators: Record<string, IndicatorPoint[]>) => void) | undefined
    if (showMacd) {
      macdPane = nextPane
      const macd = chart.addSeries(LineSeries, { title: 'MACD', color: '#7aa2f7', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, macdPane)
      const signal = chart.addSeries(LineSeries, { title: 'SIGNAL', color: '#f3b451', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, macdPane)
      const histogram = chart.addSeries(HistogramSeries, { title: 'HIST', priceLineVisible: false, lastValueVisible: false }, macdPane)
      setMacd = (nextIndicators) => {
        macd.setData(indicatorData(nextIndicators.macd))
        signal.setData(indicatorData(nextIndicators.macd_signal))
        histogram.setData((nextIndicators.macd_hist ?? []).filter((point) => point.value != null).map((point) => ({
          time: point.time as UTCTimestamp,
          value: point.value as number,
          color: (point.value as number) >= 0 ? 'rgba(34,199,169,.55)' : 'rgba(255,90,103,.55)',
        })))
      }
    }

    const binding: ChartBinding = {
      update: (payload, fit) => {
        setMainData(payload.bars)
        setVolume?.(payload.bars)
        overlaySetters.forEach((setter, key) => setter(payload.indicators[key] ?? []))
        setMacd?.(payload.indicators)
        setMarkers(payload.trades.map((trade) => ({
          time: trade.time as UTCTimestamp,
          position: trade.side === 'buy' ? 'belowBar' : 'aboveBar',
          color: trade.side === 'buy' ? '#22c7a9' : '#ff5a67',
          shape: trade.side === 'buy' ? 'arrowUp' : 'arrowDown',
        })))
        if (fit && payload.bars.length > 0) chart.timeScale().fitContent()
      },
    }
    bindingRef.current = binding
    const initial = payloadRef.current
    binding.update(initial, initial.bars.length > 0)
    if (initial.bars.length > 0) lastDatasetRef.current = bindingKey
    lastBarCountRef.current = initial.bars.length
    const panes = chart.panes()
    panes[0]?.setStretchFactor(5)
    if (volumePane >= 0) panes[volumePane]?.setStretchFactor(1.15)
    if (macdPane >= 0) panes[macdPane]?.setStretchFactor(1.55)

    const syncPaneCaptions = () => {
      const wrap = canvasWrapRef.current
      if (!wrap) return
      const wrapTop = wrap.getBoundingClientRect().top
      const place = (caption: HTMLDivElement | null, paneIndex: number) => {
        if (!caption || paneIndex < 0) return
        const paneElement = chart.panes()[paneIndex]?.getHTMLElement()
        if (paneElement) {
          const desiredTop = paneElement.getBoundingClientRect().top - wrapTop + 4
          const maximumTop = Math.max(3, wrap.clientHeight - 32 - caption.offsetHeight - 3)
          caption.style.transform = `translateY(${Math.min(Math.max(3, desiredTop), maximumTop)}px)`
        }
      }
      place(volumeCaptionRef.current, volumePane)
      place(macdCaptionRef.current, macdPane)
    }
    const resizeObserver = new ResizeObserver(() => requestAnimationFrame(syncPaneCaptions))
    resizeObserver.observe(container)
    container.addEventListener('pointerup', syncPaneCaptions)
    requestAnimationFrame(syncPaneCaptions)
    const syncVisibleTime = () => {
      const range = chart.timeScale().getVisibleRange()
      const payloadBars = payloadRef.current.bars
      const start = range ? timeValue(range.from) : payloadBars[0]?.time
      const end = range ? timeValue(range.to) : payloadBars.at(-1)?.time
      if (start == null || end == null) return
      if (timeStartRef.current) timeStartRef.current.textContent = rangeTime(start, interval)
      if (timeMiddleRef.current) timeMiddleRef.current.textContent = rangeTime(Math.round((start + end) / 2), interval)
      if (timeEndRef.current) timeEndRef.current.textContent = rangeTime(end, interval)
    }
    chart.timeScale().subscribeVisibleTimeRangeChange(syncVisibleTime)
    requestAnimationFrame(syncVisibleTime)

    const syncCrosshairTime = (param: MouseEventParams<Time>) => {
      const label = crosshairTimeRef.current
      if (!label || !param.point || param.time == null) {
        label?.classList.remove('is-visible')
        label?.setAttribute('aria-hidden', 'true')
        return
      }
      const labelWidth = 150
      const priceScaleWidth = 104
      const idealLeft = param.point.x - labelWidth / 2
      const maxLeft = Math.max(5, container.clientWidth - priceScaleWidth - labelWidth - 5)
      label.textContent = rangeTime(timeValue(param.time), interval)
      label.style.left = `${Math.min(Math.max(5, idealLeft), maxLeft)}px`
      label.classList.add('is-visible')
      label.setAttribute('aria-hidden', 'false')
    }
    chart.subscribeCrosshairMove(syncCrosshairTime)

    return () => {
      resizeObserver.disconnect()
      container.removeEventListener('pointerup', syncPaneCaptions)
      chart.timeScale().unsubscribeVisibleTimeRangeChange(syncVisibleTime)
      chart.unsubscribeCrosshairMove(syncCrosshairTime)
      bindingRef.current = null
      chart.remove()
    }
  }, [bindingKey, chartType, interval, showMacd, showVolume, visibleIndicators])

  useEffect(() => {
    const fit = displayBars.length > 0 && (lastDatasetRef.current !== bindingKey || lastBarCountRef.current === 0)
    bindingRef.current?.update({ bars: displayBars, indicators: displayIndicators, trades: displayTrades }, fit)
    if (displayBars.length > 0) lastDatasetRef.current = bindingKey
    lastBarCountRef.current = displayBars.length
  }, [bindingKey, displayBars, displayIndicators, displayTrades])

  const toggleIndicator = (key: string) => {
    setVisibleIndicators((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  const startReplay = () => {
    if (bars.length < 50) return
    const stored = localStorage.getItem(`atlas:replay:v1:${datasetKey}`)
    if (stored) {
      try {
        const session = JSON.parse(stored) as { replayIndex: number; replayAccount: ReplayAccount }
        setReplayIndex(Math.min(Math.max(40, session.replayIndex), bars.length - 1))
        setReplayAccount(session.replayAccount)
      } catch {
        setReplayIndex(Math.max(40, Math.floor(bars.length * 0.7)))
      }
    } else {
      setReplayIndex(Math.max(40, Math.floor(bars.length * 0.7)))
      setReplayAccount({ cash: 100_000, quantity: 0, trades: [] })
    }
    setReplayMode(true)
    setReplayPlaying(false)
  }
  const stepReplay = () => setReplayIndex((current) => Math.min(bars.length - 1, current + 1))
  const placeReplayOrder = (side: 'buy' | 'sell') => {
    if (!latest || !replayMode) return
    setReplayAccount((current) => {
      const feeRate = 0.001
      const slippageRate = 0.0005
      const executionPrice = latest.close * (side === 'buy' ? 1 + slippageRate : 1 - slippageRate)
      const quantity = side === 'buy'
        ? current.cash * 0.25 / (executionPrice * (1 + feeRate))
        : current.quantity
      if (quantity <= 0) return current
      const notional = quantity * executionPrice
      const fee = notional * feeRate
      const slippageCost = quantity * Math.abs(executionPrice - latest.close)
      const cash = side === 'buy' ? current.cash - notional - fee : current.cash + notional - fee
      const position = side === 'buy' ? current.quantity + quantity : 0
      const trade: Trade = {
        id: 1_000_000 + current.trades.length, time: latest.time, side,
        reason: '历史回放手动交易', price: executionPrice, quantity,
        notional, fee, slippage_cost: slippageCost, position_after: position, cash_after: cash,
        realized_pnl: null,
      }
      return { cash, quantity: position, trades: [...current.trades, trade] }
    })
  }
  const isDemo = source?.startsWith('demo') ?? false
  const latestMacd = latestIndicator(displayIndicators.macd)
  const latestSignal = latestIndicator(displayIndicators.macd_signal)
  const replayEquity = replayAccount.cash + replayAccount.quantity * (latest?.close ?? 0)

  return (
    <section className="chart-workspace">
      <div className="chart-legend">
        <div className="ohlc-row">
          <span>开 <b>{formatNumber(latest?.open)}</b></span>
          <span>高 <b>{formatNumber(latest?.high)}</b></span>
          <span>低 <b>{formatNumber(latest?.low)}</b></span>
          <span>收 <b className={change >= 0 ? 'positive' : 'negative'}>{formatNumber(latest?.close)}</b></span>
          <span className={change >= 0 ? 'positive' : 'negative'}>{change >= 0 ? '+' : ''}{(change * 100).toFixed(2)}%</span>
        </div>
        <div className="indicator-toggles">
          <span className="market-freshness" title={`数据源最后可用K线：${marketTime(lastBarTime)}`}>{isStale ? '刷新失败 · ' : ''}{marketTime(lastBarTime)}</span>
          {indicatorControls.map((item) => <button key={item.key} className={visibleIndicators.has(item.key) ? 'is-active' : ''} onClick={() => toggleIndicator(item.key)}>{item.label}</button>)}
          <button className={`pane-toggle ${showVolume ? 'is-active' : ''}`} onClick={() => onShowVolume(!showVolume)} title={showVolume ? '隐藏成交量窗格' : '显示成交量窗格'}>{showVolume ? <Eye size={11} /> : <EyeOff size={11} />}VOL</button>
          <button className={`pane-toggle ${showMacd ? 'is-active' : ''}`} onClick={() => onShowMacd(!showMacd)} title={showMacd ? '隐藏MACD窗格' : '显示MACD窗格'}>{showMacd ? <Eye size={11} /> : <EyeOff size={11} />}MACD</button>
          {!replayMode ? <button className="replay-launch" onClick={startReplay} title="从历史时点逐根回放"><RotateCcw size={11} />回放</button> : null}
          <span className={`source-pill ${isDemo ? 'demo' : isStale ? 'stale' : ''}`}>{source ?? '等待数据'}</span>
        </div>
      </div>
      {replayMode ? <div className="replay-toolbar"><span className="replay-status"><i />REPLAY <b>{replayIndex + 1}</b><em>/ {bars.length}</em></span><button onClick={() => setReplayPlaying((value) => !value)} title={replayPlaying ? '暂停' : '播放'}>{replayPlaying ? <Pause size={13} fill="currentColor" /> : <Play size={13} fill="currentColor" />}</button><button onClick={stepReplay} title="下一根K线"><StepForward size={13} /></button><span className="replay-clock">{rangeTime(latest?.time ?? 0, interval)}</span><span className="replay-account"><small>模拟权益</small><strong>{formatNumber(replayEquity, 2)}</strong><em>仓位 {formatNumber(replayAccount.quantity, 4)}</em></span><button className="paper-buy" onClick={() => placeReplayOrder('buy')}>买入25%</button><button className="paper-sell" onClick={() => placeReplayOrder('sell')}>全部卖出</button><button className="replay-exit" onClick={() => { setReplayMode(false); setReplayPlaying(false) }} title="返回实时图表"><X size={13} /></button></div> : null}
      <div className="chart-canvas-wrap" ref={canvasWrapRef}>
        <div className="chart-canvas" ref={containerRef} aria-label="金融K线、成交量与MACD技术指标图" />
        {showVolume ? <div className="pane-caption volume-caption" ref={volumeCaptionRef}><button onClick={() => onShowVolume(false)} title="隐藏成交量"><Eye size={11} /></button><strong>VOL · 成交量</strong><span>{formatNumber(latest?.volume, 0)}</span></div> : null}
        {showMacd ? <div className="pane-caption macd-caption" ref={macdCaptionRef}><button onClick={() => onShowMacd(false)} title="隐藏MACD"><Eye size={11} /></button><strong>MACD (12, 26, 9)</strong><span className="macd-value">M {formatNumber(latestMacd, 2)}</span><span className="signal-value">S {formatNumber(latestSignal, 2)}</span></div> : null}
        <div className="chart-time-axis" aria-label="当前可见K线时间范围"><span ref={timeStartRef} /><span ref={timeMiddleRef} /><span ref={timeEndRef} /></div>
        <div className="crosshair-time-label" ref={crosshairTimeRef} aria-hidden="true" />
      </div>
    </section>
  )
})
