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
import { StrategyPanel } from './components/StrategyPanel'
import { TopBar } from './components/TopBar'
import { loadPreferences, savePreferences } from './storage'
import type { Asset, BacktestResult, DataSource, FundamentalsResponse, Interval, MarketData, PortfolioResult, RunSummary, Strategy } from './types'
import type { StrategyLabTab } from './components/StrategyLabWorkspace'

const TradingChart = lazy(() => import('./components/TradingChart').then((module) => ({ default: module.TradingChart })))
const StrategyLabWorkspace = lazy(() => import('./components/StrategyLabWorkspace').then((module) => ({ default: module.StrategyLabWorkspace })))
const QuantJudgeWorkspace = lazy(() => import('./components/QuantJudgeWorkspace').then((module) => ({ default: module.QuantJudgeWorkspace })))
const EMPTY_TRADES: BacktestResult['trades'] = []

function defaultsFor(strategy: Strategy | undefined): Record<string, number | string | boolean> {
  return Object.fromEntries(strategy?.parameters.map((parameter) => [parameter.key, parameter.default]) ?? [])
}

function marketFromResult(result: BacktestResult): MarketData {
  return {
    asset: result.asset,
    interval: result.interval,
    adjustment: 'auto',
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

export default function App() {
  const shellRef = useRef<HTMLDivElement>(null)
  const marketAbortRef = useRef<AbortController | null>(null)
  const marketRequestRef = useRef(0)
  const fundamentalsAbortRef = useRef<AbortController | null>(null)
  const fundamentalsRequestRef = useRef(0)
  const [preferences, setPreferences] = useState(loadPreferences)
  const [assets, setAssets] = useState<Asset[]>([])
  const [asset, setAsset] = useState<Asset | null>(null)
  const [singleStrategies, setSingleStrategies] = useState<Strategy[]>([])
  const [portfolioStrategies, setPortfolioStrategies] = useState<Strategy[]>([])
  const [strategyId, setStrategyId] = useState('sma_cross')
  const [params, setParams] = useState<Record<string, number | string | boolean>>({ fast: 20, slow: 60 })
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
  const [singleResult, setSingleResult] = useState<BacktestResult | null>(null)
  const [portfolioResult, setPortfolioResult] = useState<PortfolioResult | null>(null)
  const [mode, setMode] = useState<'single' | 'portfolio' | 'research' | 'quantjudge'>('single')
  const [strategyLabInitialTab, setStrategyLabInitialTab] = useState<StrategyLabTab>('validate')
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [portfolioRunSignal, setPortfolioRunSignal] = useState(0)
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [unreadAlerts, setUnreadAlerts] = useState(0)

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    marketAbortRef.current = controller
    const requestId = marketRequestRef.current + 1
    marketRequestRef.current = requestId
    const staticRequest = Promise.all([
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
      setAssets(assetItems)
      setSingleStrategies(singles)
      setPortfolioStrategies(portfolios)
      setRuns(history)
      const selected = singles.find((strategy) => strategy.id === strategyId)
      if (selected) setParams(defaultsFor(selected))
    }).catch((reason: Error) => active && setError(reason.message))
    marketRequest.then((marketData) => {
      if (!active || marketRequestRef.current !== requestId) return
      setMarket(marketData)
      setAsset(marketData.asset)
    }).catch((reason: Error) => {
      if (active && reason.name !== 'AbortError') setError(reason.message)
    }).finally(() => active && setLoading(false))
    return () => {
      active = false
      controller.abort()
    }
    // Initial boot intentionally uses the versioned stored preferences once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { savePreferences(preferences) }, [preferences])

  const loadMarket = useCallback((
    nextAsset: Asset,
    interval: Interval,
    source: DataSource,
    adjustment = preferences.adjustment,
    options: { silent?: boolean; refresh?: boolean } = {},
  ) => {
    marketAbortRef.current?.abort()
    const controller = new AbortController()
    marketAbortRef.current = controller
    const requestId = marketRequestRef.current + 1
    marketRequestRef.current = requestId
    if (!options.silent) {
      setLoading(true)
      setError(null)
    }
    api.getMarket(nextAsset.symbol, nextAsset.asset_class, interval, source, adjustment, {
      signal: controller.signal,
      refresh: options.refresh,
    }).then((data) => {
      if (marketRequestRef.current !== requestId) return
      setMarket(data)
      setAsset((current) => current?.symbol === data.asset.symbol && current.asset_class === data.asset.asset_class ? current : data.asset)
    }).catch((reason: Error) => {
      if (reason.name !== 'AbortError' && !options.silent) setError(reason.message)
    }).finally(() => {
      if (!options.silent && marketRequestRef.current === requestId) setLoading(false)
    })
  }, [preferences.adjustment])

  const selectAsset = useCallback((nextAsset: Asset) => {
    setSingleResult(null)
    fundamentalsAbortRef.current?.abort()
    setFundamentals(null)
    setFundamentalsError(null)
    setAsset(nextAsset)
    const next = { ...preferences, symbol: nextAsset.symbol, assetClass: nextAsset.asset_class }
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
    const next = { ...preferences, interval }
    setPreferences(next)
    if (asset) loadMarket(asset, interval, next.source)
  }
  const setSource = (source: DataSource) => {
    const next = { ...preferences, source }
    setPreferences(next)
    if (mode === 'single' && asset) loadMarket(asset, next.interval, source)
  }
  const setBaseCurrency = (baseCurrency: typeof preferences.baseCurrency) => {
    setPreferences((current) => ({ ...current, baseCurrency }))
  }
  const setAdjustment = (adjustment: typeof preferences.adjustment) => {
    const next = { ...preferences, adjustment }
    setPreferences(next)
    if (mode === 'single' && asset) loadMarket(asset, next.interval, next.source, adjustment)
  }

  useEffect(() => {
    if (mode !== 'single' || !asset || preferences.source === 'demo') return
    const refreshMs = preferences.interval === '15m' ? 20_000 : preferences.interval === '1h' ? 30_000 : 60_000
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
  }, [asset, loadMarket, mode, preferences.adjustment, preferences.interval, preferences.source])
  const chooseStrategy = (id: string) => {
    setStrategyId(id)
    setParams(defaultsFor(singleStrategies.find((strategy) => strategy.id === id)))
  }
  const runSingle = () => {
    if (!asset) return
    setLoading(true)
    setError(null)
    api.runBacktest({
      symbol: asset.symbol,
      asset_class: asset.asset_class,
      interval: preferences.interval,
      data_source: preferences.source,
      strategy_id: strategyId,
      params,
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
    }).then((result) => {
      setSingleResult(result)
      setMarket({ ...marketFromResult(result), adjustment: preferences.adjustment })
      return api.listRuns()
    }).then(setRuns).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false))
  }
  const run = () => mode === 'single' ? runSingle() : mode === 'portfolio' ? setPortfolioRunSignal((value) => value + 1) : undefined
  const changeMode = (nextMode: typeof mode) => {
    if (nextMode === 'research' && mode !== 'research') setStrategyLabInitialTab('validate')
    setMode(nextMode)
  }
  const acceptPortfolioResult = useCallback((result: PortfolioResult | null) => {
    setPortfolioResult(result)
    if (result) api.listRuns().then(setRuns).catch(() => undefined)
  }, [])
  const activeResult = mode === 'single' ? singleResult : mode === 'portfolio' ? portfolioResult : null
  const chartBars = market?.bars ?? singleResult?.bars ?? []
  const chartIndicators = market?.indicators ?? singleResult?.indicators ?? {}

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
    source: mode === 'single' || mode === 'research' ? (singleResult?.data_source ?? market?.source) : portfolioResult?.data_source,
    trades: activeResult?.trades.length ?? 0,
    warnings: activeResult?.warnings.length ?? 0,
  }), [activeResult, market?.source, mode, portfolioResult?.data_source, singleResult?.data_source])

  const openHistoryRun = async (run: RunSummary) => {
    setLoading(true)
    setError(null)
    try {
      if (run.mode === 'single') {
        const result = await api.getRun<BacktestResult>(run.id)
        setSingleResult(result); setMarket(marketFromResult(result)); setAsset(result.asset); setMode('single')
      } else {
        const result = await api.getRun<PortfolioResult>(run.id)
        setPortfolioResult(result); setMode('portfolio')
      }
      setHistoryOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取回测记录')
    } finally { setLoading(false) }
  }
  const deleteHistoryRun = async (run: RunSummary) => {
    if (!window.confirm(`删除 ${run.symbol} 的这条回测记录？此操作无法撤销。`)) return
    await api.deleteRun(run.id)
    setRuns(await api.listRuns())
  }

  return (
    <div className="app-shell" ref={shellRef} style={layoutStyle}>
      <TopBar asset={asset} interval={preferences.interval} source={preferences.source} chartType={chartType} mode={mode} loading={loading} baseCurrency={preferences.baseCurrency} adjustment={preferences.adjustment} onInterval={setInterval} onSource={setSource} onChartType={setChartType} onMode={changeMode} onHistory={() => setHistoryOpen(true)} onRun={run} onBaseCurrency={setBaseCurrency} onAdjustment={setAdjustment} onAlerts={() => setAlertsOpen(true)} unreadAlerts={unreadAlerts} />
      {mode === 'quantjudge' ? <div className="qj-global-rail"><strong>PRIVACY MODEL</strong><span><b>私密</b>策略源码与 Agent 参数</span><span><b>私密</b>原始投资决策</span><span className="is-public"><b>公开</b>验算收益与证明回执</span></div> : <IntegrityRail dataSource={integrity.source} tradeCount={integrity.trades} hasResult={Boolean(activeResult)} warningCount={integrity.warnings} isStale={market?.is_stale} lastBarTime={market?.last_bar_time} />}
      {error ? <div className="error-banner"><AlertCircle size={15} /><span>{error}</span><button onClick={() => setError(null)}>关闭</button></div> : null}
      {mode === 'single' ? (
        <main className="terminal-grid">
          <MarketSidebar assets={assets} selectedSymbol={asset?.symbol ?? ''} onSelect={selectAsset} />
          <ResizeHandle rootRef={shellRef} side="left" cssVariable="--market-sidebar-width" oppositeCssVariable="--strategy-panel-width" centerMinimum={460} value={preferences.marketSidebarWidth} minimum={150} maximum={360} defaultValue={178} label="调整市场列表宽度" onCommit={(value) => commitLayout('marketSidebarWidth', value)} />
          <div className={`center-stack results-${preferences.resultsPanelMode}`}>
            <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载图表组件…</div>}>
              <TradingChart bars={chartBars} indicators={chartIndicators} trades={singleResult?.trades ?? EMPTY_TRADES} chartType={chartType} interval={preferences.interval} source={market?.source ?? singleResult?.data_source} datasetKey={`${asset?.symbol ?? 'none'}:${preferences.interval}`} lastBarTime={market?.last_bar_time} isStale={market?.is_stale} showVolume={preferences.showVolume} showMacd={preferences.showMacd} onShowVolume={(showVolume) => setPreferences((current) => ({ ...current, showVolume }))} onShowMacd={(showMacd) => setPreferences((current) => ({ ...current, showMacd }))} />
            </Suspense>
            {preferences.resultsPanelMode === 'normal' ? <ResizeHandle rootRef={shellRef} side="bottom" cssVariable="--results-panel-height" centerMinimum={260} value={preferences.bottomPanelHeight} minimum={180} maximum={520} defaultValue={270} label="调整回测结果高度" onCommit={(value) => commitLayout('bottomPanelHeight', value)} /> : <div className="panel-divider-spacer" />}
            <ResultsPanel result={singleResult} loading={loading && Boolean(singleResult)} panelMode={preferences.resultsPanelMode} onPanelMode={(resultsPanelMode) => setPreferences((current) => ({ ...current, resultsPanelMode }))} />
          </div>
          <ResizeHandle rootRef={shellRef} side="right" cssVariable="--strategy-panel-width" oppositeCssVariable="--market-sidebar-width" centerMinimum={460} value={preferences.strategyPanelWidth} minimum={230} maximum={520} defaultValue={264} label="调整策略参数宽度" onCommit={(value) => commitLayout('strategyPanelWidth', value)} />
          <StrategyPanel asset={asset} strategies={singleStrategies} selectedId={strategyId} values={params} capital={capital} commission={commission} slippage={slippage} spread={spread} maxPosition={maxPosition} maxParticipation={maxParticipation} stopLoss={stopLoss} takeProfit={takeProfit} onStrategy={chooseStrategy} onValue={(key, value) => setParams((current) => ({ ...current, [key]: value }))} onCapital={setCapital} onCommission={setCommission} onSlippage={setSlippage} onSpread={setSpread} onMaxPosition={setMaxPosition} onMaxParticipation={setMaxParticipation} onStopLoss={setStopLoss} onTakeProfit={setTakeProfit} onReset={() => setParams(defaultsFor(singleStrategies.find((strategy) => strategy.id === strategyId)))} fundamentals={fundamentals} fundamentalsLoading={fundamentalsLoading} fundamentalsError={fundamentalsError} onFundamentals={loadFundamentals} />
        </main>
      ) : mode === 'portfolio' ? (
        <main className="portfolio-mode"><PortfolioWorkspace catalog={assets} strategies={portfolioStrategies} interval={preferences.interval} source={preferences.source} baseCurrency={preferences.baseCurrency} runSignal={portfolioRunSignal} onLoading={setLoading} onResult={acceptPortfolioResult} onError={setError} /><ResultsPanel result={portfolioResult} loading={loading && Boolean(portfolioRunSignal)} panelMode="normal" onPanelMode={() => undefined} controls={false} /></main>
      ) : mode === 'research' ? <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载策略实验室…</div>}><StrategyLabWorkspace initialTab={strategyLabInitialTab} asset={asset} strategies={singleStrategies} interval={preferences.interval} source={preferences.source} initialCapital={capital} commission={commission} slippage={slippage} spread={spread} maxPosition={maxPosition} maxParticipation={maxParticipation} onLoading={setLoading} onError={setError} onCustomResult={(result) => { setSingleResult(result); setMarket(marketFromResult(result)); setAsset(result.asset); setMode('single'); api.listRuns().then(setRuns).catch(() => undefined) }} /></Suspense>
      : <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载 QuantJudge…</div>}><QuantJudgeWorkspace onError={(message) => setError(message)} onOpenLab={() => { setStrategyLabInitialTab('workflow'); setMode('research') }} /></Suspense>}
      <HistoryDrawer open={historyOpen} runs={runs} onClose={() => setHistoryOpen(false)} onOpen={openHistoryRun} onDelete={deleteHistoryRun} />
      <AlertDrawer open={alertsOpen} asset={asset} interval={preferences.interval} source={preferences.source} onClose={() => setAlertsOpen(false)} onUnread={setUnreadAlerts} onError={(message) => setError(message)} />
    </div>
  )
}
