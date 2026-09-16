import type { Bar, IndicatorPoint } from './types'
export const indicatorCatalog = [
  { key: 'sma20', label: 'MA · 快均线', pane: false, period: 20, color: '#f3b451' },
  { key: 'sma50', label: 'MA · 慢均线', pane: false, period: 50, color: '#7aa2f7' },
  { key: 'ema', label: 'EMA · 指数均线', pane: false, period: 20, color: '#b68ce0' },
  { key: 'boll', label: 'BOLL · 布林带（2σ）', pane: false, period: 20, color: '#8899aa' },
  { key: 'vwap', label: 'VWAP · 日内量价均价（UTC）', pane: false, period: 0, color: '#36afa3' },
  { key: 'rsi', label: 'RSI · 相对强弱', pane: true, period: 14, color: '#b68ce0' },
  { key: 'kdj', label: 'KDJ · 随机指标', pane: true, period: 9, color: '#f3b451' },
  { key: 'atr', label: 'ATR · 平均真实波幅', pane: true, period: 14, color: '#36afa3' },
  { key: 'cci', label: 'CCI · 顺势指标', pane: true, period: 20, color: '#7aa2f7' },
  { key: 'roc', label: 'ROC · 变动率（%）', pane: true, period: 12, color: '#f3b451' },
  { key: 'obv', label: 'OBV · 能量潮', pane: true, period: 0, color: '#36afa3' },
] as const
export type IndicatorSettings = Record<string, { period: number; color: string }>
export const defaultIndicatorSettings = (): IndicatorSettings => Object.fromEntries(indicatorCatalog.map(x => [x.key, { period: x.period, color: x.color }]))

// Display-only indicators: never feed chart selections into strategy execution.
export function calculateChartIndicators(bars: Bar[], settings: IndicatorSettings): Record<string, IndicatorPoint[]> {
  const output: Record<string, IndicatorPoint[]> = {}
  const put = (key: string, values: Array<number | null>) => { output[key] = bars.map((bar, i) => ({ time: bar.time, value: values[i] != null && Number.isFinite(values[i]) ? values[i] : null })) }
  const close = bars.map(b => b.close)
  const mean = (xs: number[]) => xs.reduce((s, v) => s + v, 0) / xs.length
  for (const spec of indicatorCatalog) {
    const n = Math.max(2, Math.min(500, Math.trunc(settings[spec.key]?.period || spec.period || 14)))
    const out: Array<number | null> = []
    let ema = 0, gain = 0, loss = 0, atr = 0, obv = 0, pv = 0, volume = 0, day = -1, k = 50, d = 50
    const upper: Array<number | null> = [], lower: Array<number | null> = [], ds: Array<number | null> = [], js: Array<number | null> = []
    bars.forEach((bar, i) => {
      const window = close.slice(Math.max(0, i - n + 1), i + 1)
      let value: number | null = null
      if (spec.key === 'sma20' || spec.key === 'sma50' || spec.key === 'boll') {
        if (i >= n - 1) value = mean(window)
        if (spec.key === 'boll') {
          const deviation = value == null ? null : Math.sqrt(mean(window.map(x => (x - value!) ** 2)))
          upper.push(value == null ? null : value + 2 * deviation!); lower.push(value == null ? null : value - 2 * deviation!)
        }
      } else if (spec.key === 'ema') {
        if (i === n - 1) ema = mean(window)
        else if (i >= n) ema += 2 / (n + 1) * (bar.close - ema)
        if (i >= n - 1) value = ema
      } else if (spec.key === 'rsi' && i > 0) {
        const delta = bar.close - close[i - 1]
        if (i <= n) { gain += Math.max(0, delta) / n; loss += Math.max(0, -delta) / n }
        else { gain = (gain * (n - 1) + Math.max(0, delta)) / n; loss = (loss * (n - 1) + Math.max(0, -delta)) / n }
        if (i >= n) value = gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)
      } else if (spec.key === 'atr') {
        const tr = i === 0 ? bar.high - bar.low : Math.max(bar.high - bar.low, Math.abs(bar.high - close[i - 1]), Math.abs(bar.low - close[i - 1]))
        if (i < n) atr += tr / n; else atr = (atr * (n - 1) + tr) / n
        if (i >= n - 1) value = atr
      } else if (spec.key === 'roc' && i >= n) value = close[i - n] === 0 ? null : (bar.close / close[i - n] - 1) * 100
      else if (spec.key === 'obv') { if (i > 0) obv += Math.sign(bar.close - close[i - 1]) * bar.volume; value = obv }
      else if (spec.key === 'vwap') {
        const nextDay = Math.floor(bar.time / 86400)
        if (day !== nextDay) { day = nextDay; pv = 0; volume = 0 }
        pv += (bar.high + bar.low + bar.close) / 3 * bar.volume; volume += bar.volume
        value = volume > 0 ? pv / volume : null
      } else if (spec.key === 'cci' && i >= n - 1) {
        const typical = bars.slice(i - n + 1, i + 1).map(b => (b.high + b.low + b.close) / 3)
        const avg = mean(typical), deviation = mean(typical.map(x => Math.abs(x - avg)))
        value = deviation === 0 ? 0 : (typical[n - 1] - avg) / (0.015 * deviation)
      } else if (spec.key === 'kdj') {
        if (i >= n - 1) {
          const slice = bars.slice(i - n + 1, i + 1), high = Math.max(...slice.map(x => x.high)), low = Math.min(...slice.map(x => x.low))
          const rsv = high === low ? 50 : (bar.close - low) / (high - low) * 100
          k = (2 * k + rsv) / 3; d = (2 * d + k) / 3; value = k
        }
        ds.push(value == null ? null : d); js.push(value == null ? null : 3 * k - 2 * d)
      }
      out.push(value)
    })
    put(spec.key === 'boll' ? 'boll_mid' : spec.key, out)
    if (spec.key === 'boll') { put('boll_upper', upper); put('boll_lower', lower) }
    if (spec.key === 'kdj') { put('kdj_d', ds); put('kdj_j', js) }
  }
  return output
}
