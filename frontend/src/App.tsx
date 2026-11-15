import { chartHistorySource, supportsHuggingFaceHistory, supportsMinuteBars } from './marketSupport'
import { ArchiveRunSettings, SavedLabStrategyPicker, SavedProjectRunResult, type SavedLabSelection } from './components/SavedLabBacktest'
import type { ProjectReport } from './compute/pythonProject'
import { runSavedMulti } from './lab-multi-api'
import type { LabMultiJob, LabStrategy } from './lab-strategy-types'
import './components/lab-workbench.css'
import { guardLabHashChange, pushAtlasHash, requestLabNavigation, trackAtlasHistoryEntry } from './lab-navigation'
import { SubscribedStrategyPicker } from './components/SubscribedStrategyPicker'
import { retainChartHistory } from './backtestChart'
import type { LoadChartHistory } from './useChartHistory'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'
import { api } from './api'
import { AlertDrawer } from './components/AlertDrawer'
import { HistoryDrawer } from './components/HistoryDrawer'
import { IntegrityRail } from './components/IntegrityRail'
import { MarketSidebar } from './components/MarketSidebar'
import { PortfolioWorkspace } from './components/PortfolioWorkspace'
import { ResultsPanel } from './components/ResultsPanel'
import { ResizeHandle } from './components/ResizeHandle'
import { BacktestEnginePicker } from './components/BacktestEnginePicker'
import { StrategyPanel } from './components/StrategyPanel'
import { TopBar } from './components/TopBar'
import { WorkspaceNavigation, type WorkspaceMode } from './components/WorkspaceNavigation'
import { SystemStatus } from './components/SystemStatus'
import { WorkspaceErrorBoundary } from './components/WorkspaceErrorBoundary'
import { loadPreferences, savePreferences, sourceForAssetClass } from './storage'
import type { Adjustment, Asset, BacktestResult, DataSource, FundamentalsResponse, Interval, MarketData, PortfolioResult, RunSummary, Strategy } from './types'

const TradingChart = lazy(() => import('./components/TradingChart').then((module) => ({ default: module.TradingChart })))
const RqAlphaLabWorkspace = lazy(() => import('./components/RqAlphaLabWorkspace').then(module => ({ default: module.RqAlphaLabWorkspace })))
const QuantJudgeWorkspace = lazy(() => import('./components/QuantJudgeWorkspace').then((module) => ({ default: module.QuantJudgeWorkspace })))
const SavedStrategyProof = lazy(() => import('./components/SavedStrategyProof').then(module => ({ default: module.SavedStrategyProof })))
const EMPTY_TRADES: BacktestResult['trades'] = []

function initialMode(): WorkspaceMode {
  const route = window.location.hash.slice(1).split('?')[0]
  return route === 'portfolio' || route === 'research' || route === 'quantjudge' ? route : 'single'
}

function defaultsFor(strategy: Strategy | undefined): Record<string, number | string | boolean> {
  return Object.fromEntries(strategy?.parameters.map((parameter) => [parameter.key, parameter.default]) ?? [])
}

function chartFeedLabel(source: string) {
  const provider = source.split(':')[0]
  return provider === 'sina' ? '新浪财经' : provider === 'eastmoney' ? '东方财富' : provider
}

function marketFromResult(result: BacktestResult): MarketData {
  return {
    asset: result.asset,
    interval: result.interval,
    adjustment: result.adjustment ?? 'unknown',
    source: result.data_source,
    source_note: result.source_note,
    fetched_at: Math.floor(Date.parse(result.created_at) / 1000),
    last_bar_time: result.bars.at(-1)?.time ?? 0,
    cache_hit: false,
    is_stale: false,
    bars: result.bars,
    indicators: result.indicators,
  }
}

export default function App({ ownerId = '' }: { ownerId?: string } = {}) {
  const shellRef = useRef<HTMLDivElement>(null)
  const marketAbortRef = useRef<AbortController | null>(null)
  const marketRequestRef = useRef(0)
  const fundamentalsAbortRef = useRef<AbortController | null>(null)
  const fundamentalsRequestRef = useRef(0)
  const backtestRequestRef = useRef(0)
  const backtestBusyRef = useRef(false)
  const [preferences, setPreferences] = useState(loadPreferences)
  const [assets, setAssets] = useState<Asset[]>([])
  const [asset, setAsset] = useState<Asset | null>(null)
  const [singleStrategies, setSingleStrategies] = useState<Strategy[]>([])
  const [portfolioStrategies, setPortfolioStrategies] = useState<Strategy[]>([])
  const [executionModel,setExecutionModel] = useState<'native'|'unified'>('unified')
  const [backtestEngine, setBacktestEngine] = useState<import('./types').BacktestEngine>('atlas')
  const [strategyId, setStrategyId] = useState('sma_cross')
  const [params, setParams] = useState<Record<string, number | string | boolean>>({ fast: 20, slow: 60 })
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [capital, setCapital] = useState(100_000)
  const [commission, setCommission] = useState(0.001)
  const [slippage, setSlippage] = useState(0.0005)
  const [spread, setSpread] = useState(0.0005)
  const [maxPosition, setMaxPosition] = useState(0.95)
  const [maxParticipation, setMaxParticipation] = useState(0.01)
  const [stopLoss, setStopLoss] = useState(0)
  const [takeProfit, setTakeProfit] = useState(0)
  const [market, setMarket] = useState<MarketData | null>(null)
  const [fundamentals, setFundamentals] = useState<FundamentalsResponse | null>(null)
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false)
  const [fundamentalsError, setFundamentalsError] = useState<string | null>(null)
  const [releaseId,setReleaseId] = useState('')
  const [savedSelection, setSavedSelection] = useState<SavedLabSelection | null>(null)
  const [projectReport, setProjectReport] = useState<ProjectReport | null>(null)
  const [savedMultiJob, setSavedMultiJob] = useState<LabMultiJob | null>(null)
  const [proofSnapshot, setProofSnapshot] = useState<{ runId: string; record: LabStrategy } | null>(null)
  const savedRunRequest = useRef<AbortController | null>(null)
  const savedArchive = savedSelection?.kind === 'zip' ? savedSelection : null
  const savedStrategy = savedSelection?.kind === 'strategy' ? savedSelection.record : null
  const savedMulti = savedStrategy?.kind === 'multi_python' ? savedStrategy : null
  const savedPython = savedStrategy?.kind !== 'multi_python' ? savedStrategy : null
  const portable = !!savedPython && /\bdef\s+target\s*\(/.test(savedPython.source)
  const standaloneRun = !!savedMulti || savedArchive?.mode === 'script'
  const [singleResult, setSingleResult] = useState<BacktestResult | null>(null)
  const [portfolioResult, setPortfolioResult] = useState<PortfolioResult | null>(null)
  const [mode, setModeState] = useState<WorkspaceMode>(initialMode)
  const [visitedModes, setVisitedModes] = useState<WorkspaceMode[]>(() => [initialMode()])
  const setMode = useCallback((next: WorkspaceMode) => {
    setModeState(next)
    setVisitedModes((current) => current.includes(next) ? current : [...current, next])
  }, [])
  const [navigationCollapsed, setNavigationCollapsed] = useState(() => window.innerWidth < 1400)
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')
  const [marketLoading, setMarketLoading] = useState(true)
  const [singleRunning, setSingleRunning] = useState(false)
  const [portfolioRunning, setPortfolioRunning] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const loading = historyLoading || (mode === 'single' ? marketLoading || singleRunning : mode === 'portfolio' ? portfolioRunning : false)
  const [bootAttempt, setBootAttempt] = useState(0)
  const [bootIssues, setBootIssues] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [marketError, setMarketError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [portfolioRunSignal, setPortfolioRunSignal] = useState(0)
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [unreadAlerts, setUnreadAlerts] = useState(0)
  const [systemStatusOpen, setSystemStatusOpen] = useState(false)
  const closeSystemStatus = useCallback(() => setSystemStatusOpen(false), [])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    marketAbortRef.current = controller
    const requestId = marketRequestRef.current + 1
    marketRequestRef.current = requestId
    const staticRequest = Promise.allSettled([
      api.searchAssets(),
      api.getStrategies('single'),
      api.getStrategies('portfolio'),
      api.listRuns(),
    ])
    const marketRequest = api.getMarket(
      preferences.symbol,
      preferences.assetClass,
      preferences.interval,
      preferences.source,
      preferences.adjustment,
      { signal: controller.signal },
    )
    staticRequest.then(([assetItems, singles, portfolios, history]) => {
      if (!active) return
      if (assetItems.status === 'fulfilled') {
        setAssets(assetItems.value)
        setAsset((current) => current ?? assetItems.value.find((item) => item.symbol === preferences.symbol) ?? null)
      }
      if (singles.status === 'fulfilled') {
        setSingleStrategies(singles.value)
        const selected = singles.value.find((strategy) => strategy.id === strategyId)
        if (selected && bootAttempt === 0) setParams(defaultsFor(selected))
      }
      if (portfolios.status === 'fulfilled') setPortfolioStrategies(portfolios.value)
      if (history.status === 'fulfilled') setRuns(history.value)
      setBootIssues([assetItems, singles, portfolios, history].flatMap((result, index) => result.status === 'rejected' ? [['标的目录', '单标的策略', '组合策略', '回测历史'][index]] : []))
    })
    marketRequest.then((marketData) => {
      if (!active || marketRequestRef.current !== requestId) return
      setMarket(marketData)
      setAsset(marketData.asset)
    }).catch((reason: Error) => {
      if (active && marketRequestRef.current === requestId && reason.name !== 'AbortError') setMarketError(reason.message)
    }).finally(() => { if (active && marketRequestRef.current === requestId) { marketAbortRef.current = null; setMarketLoading(false) } })
    return () => {
      active = false
      controller.abort()
    }
    // Initial boot intentionally uses the versioned stored preferences once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootAttempt])

  useEffect(() => { savePreferences(preferences) }, [preferences])
  useEffect(() => () => savedRunRequest.current?.abort(), [ownerId])

  useEffect(() => {
    const onHash = (event: HashChangeEvent) => {
      if (guardLabHashChange(event)) return
      trackAtlasHistoryEntry()
      const route = window.location.hash.slice(1).split('?')[0]
      if (route === 'single' || route === 'portfolio' || route === 'research' || route === 'quantjudge') setMode(route)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [setMode])

  useEffect(() => {
    // The shell owns Proof, trading and journal routes even when this workspace mounts hidden.
    if (window.location.hash.startsWith('#/')) return
    if (window.location.hash.split('?')[0] !== `#${mode}`) pushAtlasHash(`#${mode}`)
    else trackAtlasHistoryEntry()
    document.title = `${{ single: '行情与回测', portfolio: '投资组合', research: '策略实验室', quantjudge: '策略市场' }[mode]} · Trine`
  }, [mode])

  const loadMarket = useCallback((
    nextAsset: Asset,
    interval: Interval,
    source: DataSource,
    adjustment = preferences.adjustment,
    options: { silent?: boolean; refresh?: boolean } = {},
  ) => {
    if (options.silent && marketAbortRef.current) return
    marketAbortRef.current?.abort()
    const controller = new AbortController()
    marketAbortRef.current = controller
    const requestId = marketRequestRef.current + 1
    marketRequestRef.current = requestId
    if (!options.silent) {
      setMarketLoading(true)
      setError(null)
      setMarketError(null)
    }
    api.getMarket(nextAsset.symbol, nextAsset.asset_class, interval, source, adjustment, {
      signal: controller.signal,
      refresh: options.refresh,
    }).then((data) => {
      if (marketRequestRef.current !== requestId) return
      setMarketError(null)
      setMarket(current => options.silent ? retainChartHistory(current, data, true) : data)
      setAsset((current) => current?.symbol === data.asset.symbol && current.asset_class === data.asset.asset_class ? current : data.asset)
    }).catch((reason: Error) => {
      if (reason.name !== 'AbortError' && !options.silent && marketRequestRef.current === requestId) setMarketError(reason.message)
    }).finally(() => {
      if (marketRequestRef.current === requestId) {
        marketAbortRef.current = null
        if (!options.silent) setMarketLoading(false)
      }
    })
  }, [preferences.adjustment])

  const selectAsset = useCallback((nextAsset: Asset, researchInterval = preferences.interval) => {
    backtestRequestRef.current += 1
    setSingleResult(null)
    setMarket(null)
    fundamentalsAbortRef.current?.abort()
    fundamentalsRequestRef.current += 1
    setFundamentalsLoading(false)
    setFundamentals(null)
    setFundamentalsError(null)
    setAsset(nextAsset)
    const safeInterval = !supportsMinuteBars(nextAsset) && ['1m', '5m'].includes(researchInterval) ? '15m' : researchInterval
    let source = (preferences.source === 'baostock' && nextAsset.symbol !== '300750.SZ')
      || (preferences.source === 'huggingface' && !supportsHuggingFaceHistory(nextAsset, safeInterval))
      ? 'auto' : sourceForAssetClass(preferences.source, nextAsset.asset_class)
    if (source === 'auto' && supportsHuggingFaceHistory(nextAsset, safeInterval)) source = 'huggingface'
    const next = { ...preferences, symbol: nextAsset.symbol, assetClass: nextAsset.asset_class, interval: safeInterval, source, adjustment: source === 'huggingface' ? 'raw' as const : preferences.adjustment }
    setPreferences(next)
    loadMarket(nextAsset, next.interval, next.source, next.adjustment)
  }, [loadMarket, preferences])

  const loadFundamentals = useCallback((refresh = false) => {
    if (!asset) return
    fundamentalsAbortRef.current?.abort()
    const controller = new AbortController()
    fundamentalsAbortRef.current = controller
    const requestId = fundamentalsRequestRef.current + 1
    fundamentalsRequestRef.current = requestId
    setFundamentalsLoading(true)
    setFundamentalsError(null)
    api.getFundamentals(asset.symbol, asset.asset_class, {
      signal: controller.signal,
      refresh,
    }).then((response) => {
      if (fundamentalsRequestRef.current !== requestId) return
      setFundamentals(response)
    }).catch((reason: Error) => {
      if (reason.name !== 'AbortError' && fundamentalsRequestRef.current === requestId) {
        setFundamentalsError(reason.message)
      }
    }).finally(() => {
      if (fundamentalsRequestRef.current === requestId) setFundamentalsLoading(false)
    })
  }, [asset])

  const setInterval = (interval: Interval) => {
    backtestRequestRef.current += 1
    setSingleResult(null)
    setMarket(null)
    const source = (preferences.source === 'baostock' && !['5m', '15m', '1h'].includes(interval))
      || (preferences.source === 'huggingface' && !supportsHuggingFaceHistory(asset, interval))
      ? 'auto' : preferences.source
    const next = { ...preferences, interval, source }
    setPreferences(next)
    if (asset) loadMarket(asset, interval, next.source)
  }
  const setSource = (source: DataSource) => {
    backtestRequestRef.current += 1
    setSingleResult(null)
    setMarket(null)
    const next = { ...preferences, source, adjustment: source === 'huggingface' ? 'raw' as const : preferences.adjustment }
    setPreferences(next)
    if (mode === 'single' && asset) loadMarket(asset, next.interval, source, next.adjustment)
  }
  const setBaseCurrency = (baseCurrency: typeof preferences.baseCurrency) => {
    setPreferences((current) => ({ ...current, baseCurrency }))
  }
  const setAdjustment = (adjustment: typeof preferences.adjustment) => {
    if (preferences.source === 'huggingface' && adjustment !== 'raw') {
      setError('Hugging Face 历史源只有不复权行情；如需复权，请切回自动数据源。')
      return
    }
    backtestRequestRef.current += 1
    setSingleResult(null)
    setMarket(null)
    const next = { ...preferences, adjustment }
    setPreferences(next)
    if (mode === 'single' && asset) loadMarket(asset, next.interval, next.source, adjustment)
  }

  useEffect(() => {
    if (mode !== 'single' || singleRunning || !asset || preferences.source === 'demo' || preferences.source === 'baostock') return
    const refreshMs = ['1m', '5m'].includes(preferences.interval) ? 10_000 : preferences.interval === '15m' ? 20_000 : preferences.interval === '1h' ? 30_000 : 60_000
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadMarket(
          asset,
          preferences.interval,
          preferences.source,
          preferences.adjustment,
          { silent: true, refresh: true },
        )
      }
    }, refreshMs)
    return () => window.clearInterval(timer)
  }, [asset, loadMarket, mode, preferences.adjustment, preferences.interval, preferences.source, singleRunning])
  const chooseStrategy = (id: string) => {
    setStrategyId(id)
    setParams(defaultsFor(singleStrategies.find((strategy) => strategy.id === id)))
  }
  const chooseSavedStrategy = (next: SavedLabSelection | null) => {
    backtestRequestRef.current += 1
    setSavedSelection(next)
    setSingleResult(null)
    setProofSnapshot(null)
    setProjectReport(null)
    setSavedMultiJob(null)
    if (next) setReleaseId('')
    if (next?.kind === 'strategy' && next.record.kind !== 'multi_python') {
      const saved = next.record.settings
      setCapital(saved.initial_capital); setCommission(saved.commission_rate); setSlippage(saved.slippage_rate)
      setSpread(saved.spread_rate); setMaxPosition(saved.max_position); setMaxParticipation(saved.max_participation_rate)
      setStart(saved.start ?? ''); setEnd(saved.end ?? '')
    }
  }
  const runStandalone = async () => {
    const controller = new AbortController()
    savedRunRequest.current = controller
    backtestBusyRef.current = true
    setSingleRunning(true)
    setError(null)
    setProjectReport(null)
    setSavedMultiJob(null)
    try {
      if (savedArchive) {
        const { runPythonProject } = await import('./compute/pythonProject')
        const report = await runPythonProject(savedArchive.project.file, savedArchive.entry, {}, controller.signal)
        if (!controller.signal.aborted) setProjectReport(report)
      } else if (savedMulti) {
        await runSavedMulti(ownerId, savedMulti, controller.signal, job => {
          if (!controller.signal.aborted) setSavedMultiJob(job)
        })
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '已保存策略运行失败。')
    } finally {
      if (savedRunRequest.current === controller) {
        savedRunRequest.current = null
        backtestBusyRef.current = false
        setSingleRunning(false)
      }
    }
  }
  const runSingle = () => {
    if (backtestBusyRef.current) return
    if (standaloneRun) { void runStandalone(); return }
    if (!asset) return
    if (preferences.source === 'baostock') { setError('长历史行情与日线核验存在差异，仅供查看，不能用于回测。'); return }
    if ((start && !Number.isFinite(Date.parse(start))) || (end && !Number.isFinite(Date.parse(end))) || (start && end && Date.parse(start) >= Date.parse(end))) {
      setError('回测开始时间必须早于结束时间'); return
    }
    if (start && end) {
      const intervals = { '1m': { minutes: 1, label: '1分钟' }, '5m': { minutes: 5, label: '5分钟' }, '15m': { minutes: 15, label: '15分钟' }, '1h': { minutes: 60, label: '小时线' }, '4h': { minutes: 240, label: '4小时线' }, '1d': { minutes: 1440, label: '日线' }, '1wk': { minutes: 10080, label: '周线' } }
      const interval = intervals[preferences.interval]
      // Conservative upper bound: missing bars and market closures can only reduce it.
      const maximumBars = Math.ceil((Date.parse(end) - Date.parse(start)) / (interval.minutes * 60_000)) + 1
      if (maximumBars < 40) {
        setError(`所选日期范围按${interval.label}不足40根K线，回测至少需要40根。请延长日期范围${preferences.interval === '15m' ? '' : '，或选择更短的K线周期'}。`); return
      }
    }
    backtestBusyRef.current = true
    const requestId = ++backtestRequestRef.current
    marketAbortRef.current?.abort()
    marketRequestRef.current += 1
    setMarketLoading(false)
    setSingleRunning(true)
    setError(null)
    const controller = new AbortController()
    savedRunRequest.current = controller
    const payload = {
      backtest_engine: backtestEngine,
      execution_model: preferences.source === 'huggingface' && !releaseId ? executionModel : 'native',
      release_id: releaseId || null,
      symbol: asset.symbol,
      asset_class: asset.asset_class,
      start: start ? new Date(start).toISOString() : null,
      end: end ? new Date(end).toISOString() : null,
      interval: preferences.interval,
      data_source: preferences.source,
      strategy_id: savedPython || savedArchive ? portable || savedArchive ? 'python_portable' : 'python_bounded' : strategyId,
      python_source: savedPython && !portable ? savedPython.source : undefined,
      portable_python: savedPython && portable ? savedPython.source : undefined,
      strategy_name: savedPython?.name ?? savedArchive?.project.file.name.replace(/\.zip$/i, '').slice(0, 80),
      lab_strategy_id: savedPython?.id,
      params: savedPython || savedArchive ? {} : params,
      initial_capital: capital,
      commission_rate: commission,
      slippage_rate: slippage,
      spread_rate: spread,
      max_position: maxPosition,
      max_participation_rate: maxParticipation,
      stop_loss: stopLoss > 0 ? stopLoss : null,
      take_profit: takeProfit > 0 ? takeProfit : null,
      adjustment: preferences.adjustment,
      base_currency: preferences.baseCurrency,
      persist: true,
    }
    const execute = async () => {
      if (!savedArchive) return savedPython ? api.runBacktest(payload, controller.signal, ownerId) : api.runBacktest(payload)
      const [{ comparisonMarket }, { prepareProjectPlan }] = await Promise.all([import('./compute/client'), import('./compute/pythonProject')])
      const market = await comparisonMarket(payload, controller.signal)
      if (market.bars.length < 40) throw new Error('回测至少需要 40 根已发布 K 线。')
      const prepared = await prepareProjectPlan(savedArchive.project.file, savedArchive.entry, {}, market.bars, market.datasetId, controller.signal)
      return api.runBacktest({ ...payload, portable_python: prepared.source, portable_plan: prepared.plan,
        start: new Date(prepared.plan.start * 1000).toISOString(), end: new Date(prepared.plan.end * 1000).toISOString() },
      controller.signal, ownerId)
    }
    void execute().then((result) => {
      if (backtestRequestRef.current === requestId) {
        const resolved = { ...result, adjustment: result.adjustment ?? preferences.adjustment }
        setSingleResult(resolved)
        setProofSnapshot(savedPython && !portable ? { runId: result.run_id, record: savedPython } : null)
        setMarket(current => retainChartHistory(current, marketFromResult(resolved)))
      }
      return api.listRuns()
    }).then(setRuns).catch((reason: Error) => { if (backtestRequestRef.current === requestId) setError(reason.message) }).finally(() => {
      if (savedRunRequest.current === controller) { savedRunRequest.current = null; backtestBusyRef.current = false; setSingleRunning(false) }
    })
  }
  const run = () => mode === 'single' ? runSingle() : mode === 'portfolio' ? setPortfolioRunSignal((value) => value + 1) : undefined
  const changeMode = (nextMode: typeof mode) => {
    if (mode === nextMode) return
    requestLabNavigation(() => {
      setMode(nextMode)
      if (nextMode === 'single' && !market && asset) loadMarket(asset, preferences.interval, preferences.source)
    })
  }
  const refreshRunHistory = () => { void api.listRuns().then(setRuns).catch(() => undefined) }
  const acceptPortfolioResult = useCallback((result: PortfolioResult | null) => {
    setPortfolioResult(result)
    if (result) api.listRuns().then(setRuns).catch(() => undefined)
  }, [])
  const activeResult = mode === 'single' ? singleResult : mode === 'portfolio' ? portfolioResult : null
  const chartBars = singleResult?.bars ?? market?.bars ?? []
  const chartIndicators = singleResult?.indicators ?? market?.indicators ?? {}
  const chartLastBarTime = singleResult ? singleResult.bars.at(-1)?.time : market?.last_bar_time
  const chartIsStale = singleResult ? singleResult.data_source.endsWith(':stale-cache') : market?.is_stale
  const chartSource = singleResult?.data_source ?? market?.source
  const chartAdjustment = singleResult ? singleResult.adjustment : market?.adjustment ?? preferences.adjustment
  const historyAdjustment = chartAdjustment && ['auto', 'raw', 'forward', 'backward'].includes(chartAdjustment) ? chartAdjustment as Adjustment : undefined
  const loadChartHistory = useCallback<LoadChartHistory>(async (before, signal) => {
    if (!asset || !historyAdjustment) return []
    const provider = chartSource?.split(':')[0]
    const data = await api.getMarket(asset.symbol, asset.asset_class, preferences.interval,
      chartHistorySource(preferences.source, provider), historyAdjustment, {
        end: new Date((before - 1) * 1000).toISOString(), signal, provider,
      })
    if (data.asset.symbol !== asset.symbol || data.interval !== preferences.interval || data.adjustment !== historyAdjustment || data.source.split(':')[0] !== provider) {
      throw new Error('更早行情的来源或时效与当前图表不一致，未拼接数据。')
    }
    return data.bars
  }, [asset, chartSource, historyAdjustment, preferences.interval, preferences.source])

  const layoutStyle = useMemo(() => ({
    '--market-sidebar-width': `${preferences.marketSidebarWidth}px`,
    '--strategy-panel-width': `${preferences.strategyPanelWidth}px`,
    '--results-panel-height': `${preferences.bottomPanelHeight}px`,
  }) as CSSProperties, [
    preferences.bottomPanelHeight,
    preferences.marketSidebarWidth,
    preferences.strategyPanelWidth,
  ])

  const commitLayout = useCallback((key: 'marketSidebarWidth' | 'strategyPanelWidth' | 'bottomPanelHeight', value: number) => {
    setPreferences((current) => ({ ...current, [key]: value }))
  }, [])

  const integrity = useMemo(() => ({
    source: mode === 'single' ? (singleResult?.data_source ?? market?.source) : portfolioResult?.data_source,
    trades: activeResult?.trades.length ?? 0,
    warnings: activeResult?.warnings.length ?? 0,
  }), [activeResult, market?.source, mode, portfolioResult?.data_source, singleResult?.data_source])

  const openHistoryRun = async (run: RunSummary) => {
    backtestRequestRef.current += 1
    marketAbortRef.current?.abort()
    marketRequestRef.current += 1
    setMarketLoading(false)
    setHistoryLoading(true)
    setError(null)
    try {
      if (run.mode === 'single') {
        const result = await api.getRun<BacktestResult>(run.id)
        setStart(''); setEnd('')
        setSingleResult(result); setMarket(current => retainChartHistory(current, marketFromResult(result))); setAsset(result.asset); setMode('single')
        setPreferences((current) => ({ ...current, symbol: result.asset.symbol, assetClass: result.asset.asset_class, interval: result.interval, source: sourceForAssetClass(current.source, result.asset.asset_class) }))
      } else {
        const result = await api.getRun<PortfolioResult>(run.id)
        setPortfolioResult(result); setMode('portfolio')
      }
      setHistoryOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取回测记录')
    } finally { setHistoryLoading(false) }
  }
  const syncHistoryRun = async (run:RunSummary) => {
    try {
      const saved=await api.syncRun(run.id)
      setRuns(await api.listRuns())
      if('asset'in saved)setSingleResult(current=>current?.run_id===run.id?{...saved,bars:current.bars,indicators:current.indicators}:current)
      else setPortfolioResult(current=>current?.run_id===run.id?saved:current)
    }catch(reason){setError(reason instanceof Error?reason.message:'报告同步失败，完整结果仍在当前浏览器中')}
  }
  const deleteHistoryRun = async (run: RunSummary) => {
    if (!window.confirm(`删除 ${run.symbol} 的这条回测记录？此操作无法撤销。`)) return
    try { await api.deleteRun(run.id); setRuns(await api.listRuns()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '删除失败，请重试') }
  }


  return (
    <div className={`app-shell mode-${mode} ${navigationCollapsed ? 'navigation-is-collapsed' : ''}`} ref={shellRef} style={layoutStyle}>
      <a className="skip-link" href="#workspace-content" onClick={(event) => { event.preventDefault(); document.getElementById('workspace-content')?.focus() }}>跳到工作区</a>
      <WorkspaceNavigation mode={mode} onMode={changeMode} collapsed={navigationCollapsed} onCollapse={() => setNavigationCollapsed((current) => !current)} />
      <TopBar asset={asset} interval={preferences.interval} source={preferences.source} chartType={chartType} mode={mode} loading={loading} baseCurrency={preferences.baseCurrency} adjustment={preferences.adjustment} onInterval={setInterval} onSource={setSource} onChartType={setChartType} onHistory={() => setHistoryOpen(true)} onRun={run} onBaseCurrency={setBaseCurrency} onAdjustment={setAdjustment} onAlerts={() => setAlertsOpen(true)} onSystemStatus={() => setSystemStatusOpen(true)} unreadAlerts={unreadAlerts} />
      {mode === 'quantjudge' ? <div className="qj-global-rail"><strong>PRIVACY MODEL</strong><span><b>默认私有</b>源码与参数（公开测试样本除外）</span><span><b>作者控制</b>原始投资决策的公开范围</span><span className="is-public"><b>公开</b>验算收益与证明回执</span></div> : mode === 'research' ? null : <IntegrityRail dataSource={integrity.source} tradeCount={integrity.trades} hasResult={Boolean(activeResult)} warningCount={integrity.warnings} isStale={mode === 'portfolio' ? portfolioResult?.data_source.includes(':stale-cache') : chartIsStale} lastBarTime={mode === 'portfolio' ? undefined : chartLastBarTime} />}
      {error || (mode === 'single' && marketError) || bootIssues.length ? <div className="error-banner" role="alert"><AlertCircle size={15} /><span>{error ?? (mode === 'single' ? marketError : null) ?? `暂时无法加载：${bootIssues.join('、')}。其他已加载功能仍可使用。`}</span>{bootIssues.length ? <button onClick={() => { setError(null); setMarketLoading(true); setBootAttempt((current) => current + 1) }}>重新连接</button> : null}<button onClick={() => setSystemStatusOpen(true)}>系统状态</button><button onClick={() => { setError(null); setMarketError(null); setBootIssues([]) }}>关闭</button></div> : null}
      <div className="workspace-content" id="workspace-content" tabIndex={-1}>
      {mode === 'single' ? <WorkspaceErrorBoundary>
        <main className="terminal-grid">
          <MarketSidebar assets={assets} selectedSymbol={asset?.symbol ?? ''} onSelect={selectAsset} />
          <ResizeHandle rootRef={shellRef} side="left" cssVariable="--market-sidebar-width" oppositeCssVariable="--strategy-panel-width" centerMinimum={460} value={preferences.marketSidebarWidth} minimum={150} maximum={360} defaultValue={178} label="调整市场列表宽度" onCommit={(value) => commitLayout('marketSidebarWidth', value)} />
          <div className={`center-stack results-${standaloneRun ? 'normal' : preferences.resultsPanelMode}`}>
            <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载图表组件…</div>}>
              <TradingChart notice={<>
              {mode === 'single' && preferences.source === 'baostock' ? <div className="chart-source-notice" role="status"><AlertCircle size={15} /><span>长历史数据与本地日线对账存在差异，仅供查看，不能用于回测；2018—2019 年暂无数据。</span></div> : null}
              {mode === 'single' && !singleResult && preferences.source !== 'huggingface' && supportsHuggingFaceHistory(asset, preferences.interval) ? <div className="chart-source-notice" role="status"><span>当前来源为近期行情；更早的本地分钟数据需切换来源查看，数据截至 2026-08-07。</span><button onClick={() => setSource('huggingface')}>切换本地长历史与回测</button></div> : null}
              </>}
                sourceDetail={!singleResult && market?.chart_feed ? `${chartFeedLabel(market.chart_feed.source)} · ${market.chart_feed.used_as_fallback ? '近期行情' : '接续历史快照'}${market.chart_feed.has_gap ? ' · 数据之间有缺口' : ''}${market.is_stale ? ' · 缓存行情' : ''}。回测使用已发布的行情。` : undefined}
                highlightStart={singleResult?.bars[0]?.time ?? (start ? Date.parse(start) / 1000 : undefined)} highlightEnd={singleResult?.bars.at(-1)?.time ?? (end ? Date.parse(end) / 1000 : undefined)} bars={chartBars} indicators={chartIndicators} trades={singleResult?.trades ?? EMPTY_TRADES} chartType={chartType} interval={preferences.interval} source={chartSource} datasetKey={`${asset?.symbol ?? 'none'}:${preferences.interval}:${singleResult?.run_id ?? 'market'}:${chartSource?.split(':')[0]}:${preferences.source}:${chartAdjustment ?? 'unknown'}`} onLoadHistory={(singleResult?.backtest_engine !== 'rqalpha' || chartSource === 'hf-ohlcv') && historyAdjustment && chartSource && !chartSource.startsWith('demo') ? loadChartHistory : undefined} lastBarTime={chartLastBarTime} isStale={chartIsStale} showVolume={preferences.showVolume} showMacd={preferences.showMacd} onShowVolume={(showVolume) => setPreferences((current) => ({ ...current, showVolume }))} onShowMacd={(showMacd) => setPreferences((current) => ({ ...current, showMacd }))} />
            </Suspense>
            {preferences.resultsPanelMode === 'normal' || standaloneRun ? <ResizeHandle rootRef={shellRef} side="bottom" cssVariable="--results-panel-height" centerMinimum={260} value={preferences.bottomPanelHeight} minimum={180} maximum={520} defaultValue={270} label="调整回测结果高度" onCommit={(value) => commitLayout('bottomPanelHeight', value)} /> : <div className="panel-divider-spacer" />}
            {standaloneRun && savedSelection ? <SavedProjectRunResult key={savedSelection.key} selection={savedSelection} report={projectReport} job={savedMultiJob} busy={singleRunning} ownerId={ownerId} />
              : <ResultsPanel result={singleResult} loading={singleRunning} panelMode={preferences.resultsPanelMode}
                onPanelMode={(resultsPanelMode) => setPreferences((current) => ({ ...current, resultsPanelMode }))}
                proofAction={proofSnapshot && proofSnapshot.runId === singleResult?.run_id
                  ? <Suspense fallback={null}><SavedStrategyProof key={proofSnapshot.runId} record={proofSnapshot.record} ownerId={ownerId} /></Suspense>
                  : savedSelection && singleResult ? <small>生成 ZKP 需要受限 Python 策略。</small> : null} />}
          </div>
          <ResizeHandle rootRef={shellRef} side="right" cssVariable="--strategy-panel-width" oppositeCssVariable="--market-sidebar-width" centerMinimum={460} value={preferences.strategyPanelWidth} minimum={230} maximum={520} defaultValue={264} label="调整策略参数宽度" onCommit={(value) => commitLayout('strategyPanelWidth', value)} />
          <StrategyPanel sweepContext={{ symbol: asset?.symbol, asset_class: asset?.asset_class, interval: preferences.interval,
            data_source: preferences.source, initial_capital: capital, commission_rate: commission, slippage_rate: slippage,
            spread_rate: spread, max_position: maxPosition, max_participation_rate: maxParticipation,
            stop_loss: stopLoss || null, take_profit: takeProfit || null, adjustment: preferences.adjustment,
            base_currency: preferences.baseCurrency }} enginePicker={<BacktestEnginePicker executionModel={executionModel} onExecutionModel={setExecutionModel} unifiedAvailable={preferences.source === 'huggingface' && !releaseId} value={backtestEngine} onChange={engine => { setBacktestEngine(engine); if (engine !== 'atlas') setReleaseId('') }} result={singleResult} />} externalEngine={backtestEngine !== 'atlas'} standaloneRun={standaloneRun}
            savedPicker={<SavedLabStrategyPicker ownerId={ownerId} selected={savedSelection} disabled={singleRunning} onSelect={chooseSavedStrategy} />}
            codeContext={savedArchive ? <ArchiveRunSettings selection={savedArchive} disabled={singleRunning} onChange={chooseSavedStrategy} />
              : savedStrategy ? <section className="trine-code-context"><strong>{savedStrategy.name}</strong>
                <small>{savedMulti ? '使用策略保存的股票池和回测设置。' : '使用已保存的源码和当前所选行情。'} · 修订 {savedStrategy.revision}</small>
                <a href={`#research?strategy=${encodeURIComponent(savedStrategy.id)}`}>在策略实验室编辑</a>
              </section> : undefined}
            releasePicker={<SubscribedStrategyPicker value={releaseId} onChange={id => { chooseSavedStrategy(null); setReleaseId(id) }}/>}
            releaseSelected={!!releaseId || !!savedSelection} start={start} end={end} onStart={setStart} onEnd={setEnd} asset={asset} strategies={singleStrategies} selectedId={strategyId} values={params} capital={capital} commission={commission} slippage={slippage} spread={spread} maxPosition={maxPosition} maxParticipation={maxParticipation} stopLoss={stopLoss} takeProfit={takeProfit} onStrategy={chooseStrategy} onValue={(key, value) => setParams((current) => ({ ...current, [key]: value }))} onCapital={setCapital} onCommission={setCommission} onSlippage={setSlippage} onSpread={setSpread} onMaxPosition={setMaxPosition} onMaxParticipation={setMaxParticipation} onStopLoss={setStopLoss} onTakeProfit={setTakeProfit} onReset={() => { setParams(defaultsFor(singleStrategies.find((strategy) => strategy.id === strategyId))); setStart(''); setEnd(''); setCapital(100_000); setCommission(0.001); setSlippage(0.0005); setSpread(0.0005); setMaxPosition(0.95); setMaxParticipation(0.01); setStopLoss(0); setTakeProfit(0) }} fundamentals={fundamentals} fundamentalsLoading={fundamentalsLoading} fundamentalsError={fundamentalsError} onFundamentals={loadFundamentals} />
        </main>
      </WorkspaceErrorBoundary> : null}
      {visitedModes.includes('portfolio') ? <div className="retained-workspace" hidden={mode !== 'portfolio'} inert={mode !== 'portfolio'}><WorkspaceErrorBoundary>
        <main className="portfolio-mode"><PortfolioWorkspace catalog={assets} strategies={portfolioStrategies} interval={preferences.interval} source={preferences.source} baseCurrency={preferences.baseCurrency} runSignal={portfolioRunSignal} onLoading={setPortfolioRunning} onResult={acceptPortfolioResult} onError={setError} /><ResultsPanel result={portfolioResult} loading={portfolioRunning} panelMode="normal" onPanelMode={() => undefined} controls={false} /></main>
      </WorkspaceErrorBoundary></div> : null}
        {visitedModes.includes('research') ? <section className="retained-workspace trine-strategy-lab" hidden={mode !== 'research'} inert={mode !== 'research'}>
          <WorkspaceErrorBoundary>
            <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载策略实验室…</div>}>
              <div className="trine-lab-pane"><RqAlphaLabWorkspace ownerId={ownerId} assets={assets} active={mode === 'research'} onRunSaved={refreshRunHistory} defaults={{
                  symbol: asset?.symbol ?? preferences.symbol, asset_class: asset?.asset_class ?? preferences.assetClass,
                  interval: preferences.interval, data_source: preferences.source === 'baostock' ? 'auto' : preferences.source,
                  adjustment: preferences.adjustment, start: null, end: null, initial_capital: capital,
                  commission_rate: commission, slippage_rate: slippage, spread_rate: spread,
                  max_position: maxPosition, max_participation_rate: maxParticipation,
                }} /></div>
            </Suspense>
          </WorkspaceErrorBoundary>
        </section> : null}
      {mode === 'quantjudge' ? <WorkspaceErrorBoundary><Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载策略市场…</div>}><QuantJudgeWorkspace onError={setError} onOpenLab={() => setMode('research')} /></Suspense></WorkspaceErrorBoundary> : null}
      </div>
      <HistoryDrawer open={historyOpen} runs={runs} onClose={() => setHistoryOpen(false)} onOpen={openHistoryRun} onDelete={deleteHistoryRun} onSync={syncHistoryRun} />
      <AlertDrawer open={alertsOpen} asset={asset} interval={preferences.interval} source={preferences.source} onClose={() => setAlertsOpen(false)} onUnread={setUnreadAlerts} onError={setError} />
      {systemStatusOpen ? <SystemStatus onClose={closeSystemStatus} /> : null}
    </div>
  )
}
