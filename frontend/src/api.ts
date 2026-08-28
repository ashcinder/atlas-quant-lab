import type {
  Asset,
  Adjustment,
  BacktestResult,
  DataSource,
  Interval,
  MarketData,
  PortfolioResult,
  RunSummary,
  Strategy,
  AlertNotification,
  AlertRule,
  AlertRuleInput,
  CustomStrategyRecord,
  CustomStrategySpec,
  ResearchJob,
} from './types'

const API_ROOT = import.meta.env.VITE_API_ROOT ?? '/api/v1'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  searchAssets(query = '') {
    return request<Asset[]>(`/assets/search?q=${encodeURIComponent(query)}`)
  },
  getStrategies(mode: 'single' | 'portfolio') {
    return request<Strategy[]>(`/strategies?mode=${mode}`)
  },
  getMarket(
    symbol: string,
    assetClass: string,
    interval: Interval,
    source: DataSource,
    adjustment: Adjustment,
    options: { signal?: AbortSignal; refresh?: boolean } = {},
  ) {
    const params = new URLSearchParams({
      symbol,
      asset_class: assetClass,
      interval,
      source,
      adjustment,
      refresh: String(Boolean(options.refresh)),
    })
    return request<MarketData>(`/market/bars?${params.toString()}`, { signal: options.signal })
  },
  runBacktest(payload: Record<string, unknown>) {
    return request<BacktestResult>('/backtests', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  runPortfolio(payload: Record<string, unknown>) {
    return request<PortfolioResult>('/portfolio/backtests', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  listRuns() {
    return request<RunSummary[]>('/runs')
  },
  getRun<T extends BacktestResult | PortfolioResult>(id: string) {
    return request<T>(`/runs/${id}`)
  },
  deleteRun(id: string) {
    return request<void>(`/runs/${id}`, { method: 'DELETE' })
  },
  createResearchJob(payload: Record<string, unknown>) {
    return request<ResearchJob>('/research/jobs', { method: 'POST', body: JSON.stringify(payload) })
  },
  getResearchJob(id: string, signal?: AbortSignal) {
    return request<ResearchJob>(`/research/jobs/${id}`, { signal })
  },
  cancelResearchJob(id: string) {
    return request<ResearchJob>(`/research/jobs/${id}`, { method: 'DELETE' })
  },
  listCustomStrategies() {
    return request<CustomStrategyRecord[]>('/custom-strategies')
  },
  saveCustomStrategy(spec: CustomStrategySpec) {
    return request<CustomStrategyRecord>(`/custom-strategies/${encodeURIComponent(spec.id)}`, { method: 'PUT', body: JSON.stringify(spec) })
  },
  deleteCustomStrategy(id: string) {
    return request<void>(`/custom-strategies/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
  listAlerts() {
    return request<AlertRule[]>('/alerts')
  },
  createAlert(payload: AlertRuleInput) {
    return request<AlertRule>('/alerts', { method: 'POST', body: JSON.stringify(payload) })
  },
  updateAlert(id: string, payload: AlertRuleInput) {
    return request<AlertRule>(`/alerts/${id}`, { method: 'PUT', body: JSON.stringify(payload) })
  },
  deleteAlert(id: string) {
    return request<void>(`/alerts/${id}`, { method: 'DELETE' })
  },
  evaluateAlerts() {
    return request<AlertNotification[]>('/alerts/evaluate', { method: 'POST' })
  },
  listNotifications() {
    return request<AlertNotification[]>('/notifications')
  },
  markNotificationsRead() {
    return request<void>('/notifications/read', { method: 'POST' })
  },
}
