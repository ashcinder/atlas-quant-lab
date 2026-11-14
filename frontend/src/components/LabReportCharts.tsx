import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import type { LabBacktestReport, LabReportPoint } from '../lab-strategy-types'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' })
const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 })
const dateValue = (time: number) => new Date((time + 8 * 3600) * 1000).toISOString().slice(0, 10)
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(2)}%`
const amount = (value: number) => `¥${numberFormatter.format(value)}`
const LEFT = 76
const RIGHT = 22
const series = [
  { key: 'strategy_return', label: '策略累计收益', slot: 'strategy', dash: undefined },
  { key: 'benchmark_return', label: '基准累计收益', slot: 'benchmark', dash: '7 4' },
  { key: 'excess_return', label: '算术超额收益', slot: 'excess', dash: '2 4' },
] as const

function plotScale(values: number[], height: number) {
  const lo = values.reduce((minimum, value) => Math.min(minimum, value), 0)
  const hi = values.reduce((maximum, value) => Math.max(maximum, value), 0)
  const padding = (hi - lo || Math.max(Math.abs(hi), 1)) * .12
  const low = lo - padding
  const high = hi + padding
  return { y: (value: number) => 16 + (high - value) / (high - low) * (height - 44),
    ticks: Array.from({ length: 5 }, (_, i) => low + (high - low) * i / 4) }
}

export function LabReportCharts({ report }: { report: LabBacktestReport }) {
  const id = useId()
  const container = useRef<HTMLElement>(null)
  const [width, setWidth] = useState(1000)
  const W = width
  const PLOT = W - LEFT - RIGHT
  useEffect(() => {
    if (!container.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) setWidth(Math.max(240, Math.round(entry.contentRect.width)))
    })
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [log, setLog] = useState(false)
  const [selectedTime, setSelectedTime] = useState<number | null>(null)
  const [tableOpen, setTableOpen] = useState(false)
  const [tablePage, setTablePage] = useState(0)
  const [texture, setTexture] = useState(false)
  const invalidRange = !!start && !!end && start > end
  const points = useMemo(() => invalidRange ? [] : report.series.filter(point => (!start || dateValue(point.time) >= start) && (!end || dateValue(point.time) <= end)), [report.series, start, end, invalidRange])
  const selectedIndex = Math.max(0, points.findIndex(point => point.time === selectedTime))
  const selected = points[selectedIndex]
  const hasBenchmark = report.benchmark !== null && report.series.some(point => point.benchmark_return !== null)
  const activeSeries = hasBenchmark ? series : series.slice(0, 1)
  const canLog = points.length > 0 && points.every(point => activeSeries.every(item => (point[item.key] ?? -1) > -1))
  const useLog = log && canLog
  const transform = (value: number) => useLog ? Math.log1p(value) : value
  const untransform = (value: number) => useLog ? Math.expm1(value) : value
  const linesScale = plotScale(points.flatMap(point => activeSeries.flatMap(item => point[item.key] === null ? [] : [transform(point[item.key]!)])), 218)
  const pnlScale = plotScale(points.map(point => point.daily_pnl), 142)
  const fillsScale = plotScale(points.flatMap(point => [point.buy_amount, point.sell_amount]), 142)
  const x = (index: number) => LEFT + (points.length < 2 ? PLOT / 2 : index / (points.length - 1) * PLOT)
  const pick = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!points.length || !bounds.width) return
    const ratio = ((event.clientX - bounds.left) / bounds.width * W - LEFT) / PLOT
    const index = Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))))
    setSelectedTime(points[index].time)
  }
  const keyPick = (event: KeyboardEvent<SVGSVGElement>) => {
    if (!points.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1
      : Math.min(points.length - 1, Math.max(0, selectedIndex + (event.key === 'ArrowRight' ? 1 : -1)))
    setSelectedTime(points[index].time)
  }
  const rangeChange = (which: 'start' | 'end', value: string) => {
    if (which === 'start') setStart(value)
    else setEnd(value)
    setTablePage(0)
  }
  const barWidth = Math.max(.7, Math.min(18, PLOT / Math.max(points.length, 1) * .38))
  const dateTicks = [...new Set([0, ...(W >= 600 ? [Math.floor((points.length - 1) / 2)] : []), points.length - 1])].filter(index => index >= 0)
  const bar = (point: LabReportPoint, index: number, value: number, offset: number, mode: 'buy' | 'sell' | 'gain' | 'loss', scale: ReturnType<typeof plotScale>) => {
    const baseline = scale.y(0)
    const y = scale.y(value)
    return <rect key={`${point.time}:${mode}`} className={`lab-plot-bar ${mode}`} x={x(index) + offset - barWidth / 2} y={Math.min(y, baseline)} width={barWidth} height={Math.max(value === 0 ? 0 : .6, Math.abs(y - baseline))} rx={Math.min(4, barWidth / 2)} style={texture ? { fill: `url(#${id}-${mode})` } : undefined} />
  }
  const grid = (scale: ReturnType<typeof plotScale>, height: number, returns: boolean) => <>
    {scale.ticks.map((value, i) => <g key={i} className="lab-plot-grid"><line x1={LEFT} x2={W - RIGHT} y1={scale.y(value)} y2={scale.y(value)} /><text x={LEFT - 10} y={scale.y(value) + 4} textAnchor="end">{returns ? percent(untransform(value)) : numberFormatter.format(value)}</text></g>)}
    <line className="lab-plot-zero" x1={LEFT} x2={W - RIGHT} y1={scale.y(0)} y2={scale.y(0)} />
    {dateTicks.map(index => <text key={index} className="lab-plot-date" x={x(index)} y={height - 3} textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'}>{dateValue(points[index].time)}</text>)}
  </>
  const crosshair = (height: number) => selected && <line className="lab-plot-crosshair" x1={x(selectedIndex)} x2={x(selectedIndex)} y1={12} y2={height - 27} />
  const svgProps = { viewBox: `0 0 ${W} 142`, preserveAspectRatio: 'none', tabIndex: 0, onPointerMove: pick, onKeyDown: keyPick }
  const from = report.series[0]
  const through = report.series.at(-1)
  const tableRows = points.slice(tablePage * 50, tablePage * 50 + 50)
  return <section ref={container} className="lab-report-charts" aria-label="回测图表">
    <div className="lab-report-filters">
      <label>图表起日<input type="date" min={from && dateValue(from.time)} max={through && dateValue(through.time)} value={start} onChange={event => rangeChange('start', event.target.value)} /></label>
      <label>图表止日<input type="date" min={from && dateValue(from.time)} max={through && dateValue(through.time)} value={end} onChange={event => rangeChange('end', event.target.value)} /></label>
      <button type="button" onClick={() => { setStart(''); setEnd(''); setTablePage(0) }}>重置范围</button>
      <fieldset className="lab-report-scale"><legend>收益坐标</legend>
        <label><input type="radio" name={`${id}-scale`} checked={!useLog} onChange={() => setLog(false)} />线性轴</label>
        <label><input type="radio" name={`${id}-scale`} checked={useLog} disabled={!canLog} onChange={() => setLog(true)} />对数轴</label>
      </fieldset>
      <label className="lab-report-checkbox"><input type="checkbox" checked={texture} onChange={event => setTexture(event.target.checked)} />纹理辅助</label>
      <button type="button" aria-expanded={tableOpen} onClick={() => setTableOpen(!tableOpen)}>{tableOpen ? '收起图表数据' : '查看图表数据'}</button>
    </div>
    <p className="lab-report-note">范围仅缩放下方三图；概览指标与年度收益保持完整回测区间。{useLog ? ' 对数轴对每条曲线的 1＋显示收益取对数，刻度仍显示收益率；算术超额收益不是几何超额净值。' : ''}{!canLog && points.length ? ' 部分曲线不满足 1＋显示收益 > 0，对数坐标不可用；算术超额收益不是几何超额净值。' : ''}</p>
    {invalidRange ? <p role="alert">图表止日不能早于起日。</p> : !points.length ? <p className="lab-report-empty">所选范围内没有交易日。</p> : <>
      <div className="lab-report-chart-legend">{activeSeries.map(item => <span key={item.key}><i className={item.slot} />{item.label}</span>)}</div>
      <figure><figcaption>累计收益 <span>最大回撤 {percent(report.drawdown?.value ?? 0)}</span></figcaption>
        <svg {...svgProps} viewBox={`0 0 ${W} 218`} role="img" aria-label="累计收益曲线；使用左右方向键查看交易日">
          {grid(linesScale, 218, true)}
          {report.drawdown && report.drawdown.end >= points[0].time && report.drawdown.start <= points.at(-1)!.time && (() => {
            const a = Math.max(0, points.findIndex(point => point.time >= report.drawdown!.start))
            const b = Math.max(a, points.reduce((last, point, index) => point.time <= report.drawdown!.end ? index : last, -1))
            return <rect className="lab-plot-drawdown" x={x(a)} y={12} width={Math.max(1, x(b) - x(a))} height={180}><title>最大回撤区间</title></rect>
          })()}
          {activeSeries.map(item => <path key={item.key} className={`lab-plot-line ${item.slot}`} strokeDasharray={item.dash} d={points.map((point, index) => point[item.key] === null ? '' : `${index === 0 || points[index - 1][item.key] === null ? 'M' : 'L'}${x(index)},${linesScale.y(transform(point[item.key]!))}`).join(' ')} />)}
          {crosshair(218)}
          {activeSeries.map(item => selected[item.key] !== null && <circle key={item.key} className={`lab-plot-marker ${item.slot}`} cx={x(selectedIndex)} cy={linesScale.y(transform(selected[item.key]!))} r={4} />)}
        </svg>
      </figure>
      <div className="lab-report-end-labels">{activeSeries.map(item => <span key={item.key}><i className={item.slot} />{item.label} {percent(points.at(-1)![item.key])}</span>)}</div>
      <figure><figcaption>每日盈亏 <span>人民币 / 元 · ＋盈利，−亏损</span></figcaption>
        <svg {...svgProps} role="img" aria-label="每日盈亏柱图；使用左右方向键查看交易日">
          <defs>{(['gain', 'loss'] as const).map(mode => <pattern key={mode} id={`${id}-${mode}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform={`rotate(${mode === 'gain' ? 45 : 135})`}><rect className={`lab-plot-pattern ${mode}`} width="6" height="6" /><line x1="0" x2="0" y1="0" y2="6" className="lab-plot-pattern-ink" /></pattern>)}</defs>
          {grid(pnlScale, 142, false)}{points.map((point, index) => bar(point, index, point.daily_pnl, 0, point.daily_pnl >= 0 ? 'gain' : 'loss', pnlScale))}{crosshair(142)}
        </svg>
      </figure>
      <figure><figcaption>成交金额 <span>人民币 / 元</span></figcaption>
        <div className="lab-report-chart-legend"><span><i className="strategy" />买入金额</span><span><i className="benchmark" />卖出金额</span></div>
        <svg {...svgProps} role="img" aria-label="每日买卖成交金额柱图；使用左右方向键查看交易日">
          <defs>{(['buy', 'sell'] as const).map(mode => <pattern key={mode} id={`${id}-${mode}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform={`rotate(${mode === 'buy' ? 45 : 135})`}><rect className={`lab-plot-pattern ${mode}`} width="6" height="6" /><line x1="0" x2="0" y1="0" y2="6" className="lab-plot-pattern-ink" /></pattern>)}</defs>
          {grid(fillsScale, 142, false)}{points.flatMap((point, index) => [bar(point, index, point.buy_amount, -barWidth / 2 - 1, 'buy', fillsScale), bar(point, index, point.sell_amount, barWidth / 2 + 1, 'sell', fillsScale)])}{crosshair(142)}
        </svg>
      </figure>
      <div className="lab-report-readout" aria-live="polite" aria-atomic="true">
        <strong>{dateFormatter.format(selected.time * 1000)}</strong>
        <span>策略 {percent(selected.strategy_return)}</span><span>基准 {percent(selected.benchmark_return)}</span><span>超额 {percent(selected.excess_return)}</span>
        <span>日盈亏 {amount(selected.daily_pnl)}</span><span>买入 {amount(selected.buy_amount)}</span><span>卖出 {amount(selected.sell_amount)}</span>
      </div>
      <div className="lab-report-range">
        <label>范围起点<input type="range" aria-label="图表范围起点" min={0} max={Math.max(0, report.series.length - 1)} value={start ? Math.max(0, report.series.findIndex(point => dateValue(point.time) >= start)) : 0} onChange={event => rangeChange('start', dateValue(report.series[Number(event.target.value)].time))} /></label>
        <label>范围终点<input type="range" aria-label="图表范围终点" min={0} max={Math.max(0, report.series.length - 1)} value={end ? Math.max(0, report.series.reduce((last, point, index) => dateValue(point.time) <= end ? index : last, -1)) : report.series.length - 1} onChange={event => rangeChange('end', dateValue(report.series[Number(event.target.value)].time))} /></label>
      </div>
    </>}
    {tableOpen && <div className="lab-report-chart-table"><div className="lab-report-table-scroll"><table><caption>图表数据 · 所选范围共 {points.length} 个交易日</caption><thead><tr><th>日期</th><th>策略收益</th><th>基准收益</th><th>超额收益</th><th>日盈亏（元）</th><th>买入金额（元）</th><th>卖出金额（元）</th></tr></thead><tbody>{tableRows.map(point => <tr key={point.time}><th scope="row">{dateValue(point.time)}</th><td>{percent(point.strategy_return)}</td><td>{percent(point.benchmark_return)}</td><td>{percent(point.excess_return)}</td><td>{amount(point.daily_pnl)}</td><td>{amount(point.buy_amount)}</td><td>{amount(point.sell_amount)}</td></tr>)}</tbody></table></div><div className="lab-report-pagination"><button type="button" disabled={tablePage === 0} onClick={() => setTablePage(tablePage - 1)}>上页图表数据</button><span>{tablePage + 1} / {Math.max(1, Math.ceil(points.length / 50))}</span><button type="button" disabled={(tablePage + 1) * 50 >= points.length} onClick={() => setTablePage(tablePage + 1)}>下页图表数据</button></div></div>}
  </section>
}
