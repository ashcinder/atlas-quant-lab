import type {
  Asset,
  Adjustment,
  BacktestResult,
  DataSource,
  FundamentalsResponse,
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
  QuantAgent,
  QuantChainStatus,
  QuantJudgeOverview,
  QuantReport,
  QuantSubscription,
  QuantVerification,
  StrategyPackageRecord,
  StudioSpec,
  StudioTemplate,
  StudioValidation,
  StudioWorkflow,
  StudioWorkflowRecord,
  StrategyProject,
  StrategyProjectArtifactKind,
  StrategyProjectCreate,
  ZkMarketDataset,
  ZkProfile,
  ZkProofRecord,
} from './types'

import { request } from './request'

export const api = {
  getHealth(signal?: AbortSignal) {
    return request<{ status: string; name: string; version: string }>('/health', { signal }, 8_000)
  },
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
  getFundamentals(
    symbol: string,
    assetClass: string,
    options: { signal?: AbortSignal; refresh?: boolean } = {},
  ) {
    const params = new URLSearchParams({
      symbol,
      asset_class: assetClass,
      refresh: String(Boolean(options.refresh)),
    })
    return request<FundamentalsResponse>(`/market/fundamentals?${params.toString()}`, {
      signal: options.signal,
    })
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
  getQuantJudgeOverview() {
    return request<QuantJudgeOverview>('/quantjudge/overview')
  },
  listQuantAgents(filters: { category?: string; reportType?: string; query?: string } = {}) {
    const params = new URLSearchParams()
    if (filters.category) params.set('category', filters.category)
    if (filters.reportType) params.set('report_type', filters.reportType)
    if (filters.query) params.set('q', filters.query)
    const suffix = params.size ? `?${params.toString()}` : ''
    return request<QuantAgent[]>(`/quantjudge/agents${suffix}`)
  },
  getQuantAgent(id: string) {
    return request<QuantAgent>(`/quantjudge/agents/${encodeURIComponent(id)}`)
  },
  createQuantAgent(payload: Record<string, unknown>) {
    return request<{ agent: QuantAgent; developer_token: string; token_shown_once: boolean }>('/quantjudge/agents', {
      method: 'POST', body: JSON.stringify(payload),
    })
  },
  verifyQuantReport(id: string) {
    return request<QuantVerification>(`/quantjudge/reports/${encodeURIComponent(id)}/verify`)
  },
  listZkProfiles(signal?: AbortSignal) {
    return request<ZkProfile[]>('/quantjudge/zkp/profiles', { signal }, 8_000)
  },
  createZkMarketDataset(symbol: string, assetClass: string, interval: Interval) {
    const params = new URLSearchParams({ symbol, asset_class: assetClass, interval, source: 'auto', adjustment: 'raw' })
    return request<ZkMarketDataset>(`/quantjudge/zkp/market-datasets?${params.toString()}`, { method: 'POST' })
  },
  uploadZkProof(agentId: string, token: string, profile: string, file: File) {
    const body = new FormData()
    body.append('file', file)
    return request<ZkProofRecord>(`/quantjudge/agents/${encodeURIComponent(agentId)}/zk-proofs?proof_profile=${encodeURIComponent(profile)}`, {
      method: 'POST', headers: { 'X-Developer-Token': token }, body,
    })
  },
  publishZkReport(agentId: string, token: string, proofId: string) {
    return request<QuantReport>(`/quantjudge/agents/${encodeURIComponent(agentId)}/reports/zkp`, {
      method: 'POST', headers: { 'X-Developer-Token': token }, body: JSON.stringify({ proof_id: proofId }),
    })
  },
  getQuantChainStatus(signal?: AbortSignal) {
    return request<QuantChainStatus>('/quantjudge/chain/status', { signal }, 8_000)
  },
  subscribeQuantAgent(id: string, payload: { investor_alias: string; billing_cycle: string }) {
    return request<QuantSubscription>(`/quantjudge/agents/${encodeURIComponent(id)}/subscriptions`, {
      method: 'POST', body: JSON.stringify(payload),
    })
  },
  listQuantSubscriptions(investorAlias: string) {
    return request<QuantSubscription[]>(`/quantjudge/subscriptions?investor_alias=${encodeURIComponent(investorAlias)}`)
  },
  getStudioSpec() {
    return request<StudioSpec>('/quantjudge/studio/spec')
  },
  getStudioTemplates() {
    return request<StudioTemplate[]>('/quantjudge/studio/templates')
  },
  validateStudioWorkflow(workflow: StudioWorkflow) {
    return request<StudioValidation>('/quantjudge/studio/workflows/validate', { method: 'POST', body: JSON.stringify(workflow) })
  },
  listStrategyPackages(agentId: string, token: string) {
    return request<StrategyPackageRecord[]>(`/quantjudge/agents/${encodeURIComponent(agentId)}/packages`, { headers: { 'X-Developer-Token': token } })
  },
  listStudioWorkflows(agentId: string, token: string) {
    return request<StudioWorkflowRecord[]>(`/quantjudge/agents/${encodeURIComponent(agentId)}/workflows`, { headers: { 'X-Developer-Token': token } })
  },
  executionCapabilities() {
    return request<{ python: { configured: boolean }; ai: { configured: boolean }; tee: { execution_available: boolean } }>('/quantjudge/studio/execution-capabilities')
  },
  executePrivatePackage(agentId: string, packageId: string, token: string, payload: Record<string, unknown>) {
    return request<{ id: string; metrics: Record<string, number>; final_equity: number; ai_calls: number; ai_failed_closed: number; warnings: string[] }>(`/quantjudge/agents/${encodeURIComponent(agentId)}/packages/${encodeURIComponent(packageId)}/execute`, {
      method: 'POST', headers: { 'X-Developer-Token': token }, body: JSON.stringify(payload),
    }, 210_000)
  },
  saveStudioWorkflow(agentId: string, token: string, workflow: StudioWorkflow, changeNote = '') {
    return request<StudioWorkflowRecord>(`/quantjudge/agents/${encodeURIComponent(agentId)}/workflows/${encodeURIComponent(workflow.id)}`, {
      method: 'PUT', headers: { 'X-Developer-Token': token }, body: JSON.stringify({ workflow, change_note: changeNote }),
    })
  },
  listStrategyProjects() {
    return request<StrategyProject[]>('/strategy-projects')
  },
  createStrategyProject(payload: StrategyProjectCreate) {
    return request<StrategyProject>('/strategy-projects', { method: 'POST', body: JSON.stringify(payload) })
  },
  updateStrategyProject(id: string, revision: number, payload: Partial<StrategyProjectCreate>) {
    return request<StrategyProject>(`/strategy-projects/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify({ expected_revision: revision, ...payload }),
    })
  },
  linkStrategyProjectArtifact(id: string, revision: number, kind: StrategyProjectArtifactKind, artifactId: string, developerToken?: string) {
    return request<StrategyProject>(`/strategy-projects/${encodeURIComponent(id)}/artifacts`, {
      method: 'POST', headers: developerToken ? { 'X-Developer-Token': developerToken } : undefined, body: JSON.stringify({ expected_revision: revision, kind, artifact_id: artifactId }),
    })
  },
  freezeStrategyProject(id: string, revision: number, version: string) {
    return request<StrategyProject>(`/strategy-projects/${encodeURIComponent(id)}/freeze`, {
      method: 'POST', body: JSON.stringify({ expected_revision: revision, version }),
    })
  },
}
