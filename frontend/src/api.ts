import type {
  Asset,
  ChartOverviewPoint,
  Adjustment,
  BacktestResult,
  DataSource,
  FundamentalsResponse,
  Interval,
  MarketData,
  PortfolioResult,
  Strategy,
  AlertNotification,
  AlertRule,
  AlertRuleInput,
  CustomStrategyRecord,
  CustomStrategySpec,
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

import { ApiError, request } from './request'
import { canExtendPublishedChart, extendPublishedChart } from './backtestChart'
import { MarketChunkUnavailableError, MarketPreparingError } from './compute/market'
import * as browserCompute from './compute/client'
import { labOwnerHeaders, type LabDraft, type LabRunSummary, type LabStrategy, type LabStrategySummary } from './lab-strategy-types'
import { evaluateBrowserAlerts } from './compute/alerts'

function markChartFallback(data: MarketData): MarketData {
  return { ...data, chart_feed: { source: data.source, start: data.bars[0]?.time ?? data.last_bar_time,
    has_gap: false, used_as_fallback: true } }
}

export const api = {
  getHealth(signal?: AbortSignal) {
    return request<{ status: string; name: string; version: string }>('/health', { signal }, 8_000)
  },
  searchAssets(query = '') {
    return request<Asset[]>(`/assets/search?q=${encodeURIComponent(query)}&limit=100`)
  },
  getStrategies(mode: 'single' | 'portfolio') {
    return request<Strategy[]>(`/strategies?mode=${mode}`)
  },
  async getMarket(
    symbol: string,
    assetClass: string,
    interval: Interval,
    source: DataSource,
    adjustment: Adjustment,
    options: { signal?: AbortSignal; refresh?: boolean; start?: string; end?: string; provider?: string } = {},
  ): Promise<MarketData> {
    const provider = options.provider
    const crypto = assetClass === 'crypto' && (!provider || provider === 'binance')
      && (source === 'auto' || source === 'binance')
    const mainland = assetClass === 'equity' && /^\d{6}\.(SS|SZ)$/.test(symbol)
      && (adjustment === 'raw' || adjustment === 'auto')
      && (source === 'auto' || source === 'huggingface')
    const published = async () => {
      const market = await browserCompute.getMarket(symbol, assetClass, interval, source, adjustment, options)
      if (!options.start && !options.end && !market.bars.length) {
        throw new MarketPreparingError('所选标的和周期暂无已发布的 K 线')
      }
      return market
    }
    const live = (liveAdjustment: Adjustment) => {
      const params = new URLSearchParams({ symbol, asset_class: assetClass, interval, adjustment: liveAdjustment })
      if (options.end) params.set('before', String(Math.floor(Date.parse(options.end) / 1000) + 1))
      if (provider) params.set('provider', provider)
      return request<MarketData>(`/market/chart?${params}`, { signal: options.signal }, 30_000)
    }
    const retryable = (error: unknown) => !options.signal?.aborted && (
      error instanceof MarketPreparingError || error instanceof MarketChunkUnavailableError
      || error instanceof ApiError && (error.kind === 'network' || error.kind === 'timeout'
        || error.status === 404 || error.status === 429 || (error.status !== null && error.status >= 500))
    )
    if (crypto || (mainland && (provider === 'sina' || provider === 'eastmoney'))) {
      try {
        return await live(adjustment)
      } catch (error) {
        if (options.end || !retryable(error)) throw error
        return published()
      }
    }
    if (!mainland || options.start || options.end) return published()
    if (options.refresh && (source === 'auto' || canExtendPublishedChart(interval))) {
      const [snapshot, recent] = await Promise.allSettled([published(), live(source === 'auto' ? adjustment : 'raw')])
      if (snapshot.status === 'fulfilled') {
        if (recent.status === 'rejected') return snapshot.value
        if (source === 'huggingface') return extendPublishedChart(snapshot.value, recent.value)
        return recent.value.last_bar_time >= snapshot.value.last_bar_time ? recent.value : snapshot.value
      }
      if (!retryable(snapshot.reason)) throw snapshot.reason
      if (recent.status === 'fulfilled') return markChartFallback(recent.value)
      throw recent.reason
    }
    try {
      return await published()
    } catch (error) {
      if (!retryable(error)) throw error
      return markChartFallback(await live(adjustment))
    }
  },
  getChartOverview(datasetId: string, signal: AbortSignal) {
    return request<ChartOverviewPoint[]>(`/market/datasets/${encodeURIComponent(datasetId)}/overview`, { signal })
  },
  getChartWindow: browserCompute.getChartWindow,
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
  backtestEngines(signal?: AbortSignal) {
    return request<Array<{id: import('./types').BacktestEngine; name: string; available: boolean; description: string; version?: string; reason?: string}>>('/backtest-engines', { signal })
  },
  async runBacktest(payload: Record<string, unknown>, signal?:AbortSignal, labOwner?: string) {
    if (payload.backtest_engine && payload.backtest_engine !== 'atlas') {
      if(payload.data_source==='huggingface'&&(!payload.start||!payload.end)){
        const q=new URLSearchParams({symbol:String(payload.symbol),asset_class:String(payload.asset_class),interval:String(payload.interval),adjustment:String(payload.adjustment??'raw'),data_source:'huggingface'})
        const manifest=await request<{status:string;start:number;end:number}>(`/market/manifest?${q}`,{signal})
        if(manifest.status!=='ready')throw new Error('所选历史行情尚未发布')
        payload={...payload,start:payload.start||new Date(manifest.start*1000).toISOString(),end:payload.end||new Date(manifest.end*1000).toISOString()}
      }
      if(payload.strategy_id==='python_portable')payload=await browserCompute.prepareExternalStrategy(payload,signal)
      const options = {method:'POST',headers: labOwner ? { 'X-Atlas-Lab-Owner': labOwner } : undefined,body:JSON.stringify(payload),signal}
      const plan = payload.portable_plan as { targets_gzip?: string } | undefined
      const background = plan?.targets_gzip || (payload.backtest_engine === 'vnpy' && payload.asset_class === 'crypto'
        && (payload.interval === '1m' || payload.interval === '5m'))
      if (!background) return request<BacktestResult>('/backtests/native', options, 660_000)
      const { job_id } = await request<{job_id: string}>('/backtests/native-jobs', options)
      const deadline = Date.now() + 660_000
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 3000))
        signal?.throwIfAborted()
        try {
          const job = await request<{status: 'running' | 'completed' | 'failed'; result?: BacktestResult; error?: string}>(
            `/backtests/native-jobs/${encodeURIComponent(job_id)}`, { signal }, 30_000)
          if (job.status === 'completed' && job.result) return job.result
          if (job.status === 'failed') throw new Error(job.error || '后台回测失败')
        } catch (error) {
          if (!(error instanceof ApiError && (error.kind === 'network' || error.kind === 'timeout'
            || [502, 503, 504].includes(error.status ?? 0)))) throw error
        }
      }
      throw new Error('后台回测仍在运行，完成后可在历史回测查看。')
    }
    return browserCompute.runBacktest(payload,signal,labOwner)
  },
  runPortfolio(payload: Record<string, unknown>) {
    return browserCompute.runPortfolio(payload)
  },
  listRuns() {
    return browserCompute.listRuns()
  },
  listLabStrategies(owner: string, signal?: AbortSignal) {
    return request<LabStrategySummary[]>('/lab-strategies', { headers: labOwnerHeaders(owner), signal })
  },
  getLabStrategy(owner: string, id: string, signal?: AbortSignal) {
    return request<LabStrategy>(`/lab-strategies/${encodeURIComponent(id)}`, { headers: labOwnerHeaders(owner), signal })
  },
  createLabStrategy(owner: string, id: string, draft: LabDraft) {
    return request<LabStrategy>('/lab-strategies', { method: 'POST', headers: labOwnerHeaders(owner), body: JSON.stringify({ ...draft, id }) })
  },
  updateLabStrategy(owner: string, id: string, revision: number, draft: LabDraft) {
    return request<LabStrategy>(`/lab-strategies/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: labOwnerHeaders(owner), body: JSON.stringify({ ...draft, expected_revision: revision }),
    })
  },
  listLabRuns(owner: string, id: string, signal?: AbortSignal) {
    return request<LabRunSummary[]>(`/lab-strategies/${encodeURIComponent(id)}/runs`, { headers: labOwnerHeaders(owner), signal })
  },
  deleteLabRun(owner: string, id: string, runId: string) {
    return request<void>(`/lab-strategies/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE', headers: labOwnerHeaders(owner),
    })
  },
  getRun<T extends BacktestResult | PortfolioResult>(id: string) {
    return browserCompute.getRunHydrated<T>(id)
  },
  deleteRun(id: string) {
    return browserCompute.deleteRun(id)
  },
  syncRun(id:string){return browserCompute.syncLocalRun(id)},
  createResearchJob(payload: Record<string, unknown>) {
    return browserCompute.createResearchJob(payload)
  },
  getResearchJob(id: string, signal?: AbortSignal) {
    return browserCompute.getResearchJob(id, signal)
  },
  getLatestResearchJob(context?:{project_id:string;symbol:string;interval:string}) {
    return browserCompute.getLatestResearchJob(context)
  },
  cancelResearchJob(id: string) {
    return browserCompute.cancelResearchJob(id)
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
    return evaluateBrowserAlerts()
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
  createZkMarketDataset(symbol: string, assetClass: string, interval: Interval, start?: string, end?: string) {
    const params = new URLSearchParams({ symbol, asset_class: assetClass, interval, source: 'auto', adjustment: 'raw' })
    if (start) params.set('start', start)
    if (end) params.set('end', end)
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
