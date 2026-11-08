import type { AlertNotification, AlertRule, IndicatorPoint, MarketData } from '../types'
import { request } from '../request'
import { assertComputeIdentity, getComputeIdentity, getMarket } from './client'

function crossed(previous: number | null, current: number, threshold: number, above: boolean): boolean {
  if (previous == null) return above ? current > threshold : current < threshold
  return above ? previous <= threshold && threshold < current : previous >= threshold && threshold > current
}
function latestIndicator(points: IndicatorPoint[] | undefined): number | null {
  if (!points) return null
  for (let i = points.length - 1; i >= 0; i--) if (points[i].value != null && Number.isFinite(points[i].value)) return points[i].value
  return null
}

/** The server retains cooldown/ownership state; this function computes observations only. */
export function evaluateAlertObservation(rule: AlertRule, market: MarketData): { value: number; triggered: boolean } | null {
  if (!rule.enabled || market.bars.length < 30) return null
  const latest = market.bars.at(-1)!.close
  const previousClose = market.bars.at(-2)!.close
  const threshold = rule.threshold ?? 0
  if (!Number.isFinite(latest) || !Number.isFinite(threshold)) return null
  if (rule.kind.startsWith('price_')) return { value: latest, triggered: crossed(rule.last_value, latest, threshold, rule.kind === 'price_above' || rule.kind === 'price_crosses_above') }
  if (rule.kind === 'change_pct_above') {
    if (!Number.isFinite(previousClose) || previousClose <= 0) return null
    const value = latest / previousClose - 1
    return { value, triggered: value >= threshold && (rule.last_value == null || rule.last_value < threshold) }
  }
  if (rule.kind.startsWith('rsi_')) {
    const value = latestIndicator(market.indicators.rsi14)
    return value == null ? null : { value, triggered: crossed(rule.last_value, value, threshold, rule.kind === 'rsi_above') }
  }
  if (rule.kind !== 'macd_crosses_above' && rule.kind !== 'macd_crosses_below') return null
  const signal = new Map((market.indicators.macd_signal ?? []).filter(point => point.value != null && Number.isFinite(point.value)).map(point => [point.time, point.value!]))
  const macd = market.indicators.macd ?? []
  for (let i = macd.length - 1; i >= 0; i--) {
    const point = macd[i]
    if (point.value == null || !Number.isFinite(point.value) || !signal.has(point.time)) continue
    const value = point.value - signal.get(point.time)!
    return { value, triggered: crossed(rule.last_value, value, 0, rule.kind === 'macd_crosses_above') }
  }
  return null
}

let evaluating = false
/** Invoked while this browser is open. No timer or server evaluation fallback is installed. */
export async function evaluateBrowserAlerts(): Promise<AlertNotification[]> {
  if (evaluating) return []
  evaluating = true
  try {
    const identity = await getComputeIdentity()
    const alerts = await request<AlertRule[]>('/alerts')
    await assertComputeIdentity(identity)
    const grouped = new Map<string, AlertRule[]>()
    for (const alert of alerts) {
      if (!alert.enabled) continue
      const key = JSON.stringify([alert.symbol, alert.asset_class, alert.interval, alert.data_source])
      const rules = grouped.get(key) ?? []
      rules.push(alert)
      grouped.set(key, rules)
    }
    const notifications: AlertNotification[] = []
    for (const rules of grouped.values()) {
      const first = rules[0]
      let market: MarketData
      try { market = await getMarket(first.symbol, first.asset_class, first.interval, first.data_source, 'auto') }
      catch {
        // Market availability is best-effort, but a changed session ends the whole evaluation.
        await assertComputeIdentity(identity)
        continue
      }
      for (const rule of rules) {
        const observation = evaluateAlertObservation(rule, market)
        if (!observation) continue
        await assertComputeIdentity(identity)
        const response = await request<{ notification: AlertNotification | null }>(`/compute/alerts/${encodeURIComponent(rule.id)}/observations`, { method: 'POST', body: JSON.stringify(observation) })
        await assertComputeIdentity(identity)
        if (response.notification) notifications.push(response.notification)
      }
    }
    return notifications
  } finally { evaluating = false }
}
