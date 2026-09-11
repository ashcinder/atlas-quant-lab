import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BookOpen, ChevronDown, ChevronUp, Pause, Play, RefreshCw, Square, Wallet } from 'lucide-react'
import { request, RUNTIME_CHANGED_EVENT } from '../request'
import type { Interval, RuntimeAccount, RuntimeEnvironment, RuntimeMarket, StrategyRelease, StrategyRun, StrategySubscription } from '../types'
import DemoAccountSetup from './DemoAccountSetup'
import './trading.css'

type Venue = 'binance' | 'okx'
type Capabilities = { authorized: boolean; user_id: string; venues: { venue: Venue; mode: string; configured: boolean; can_trade: boolean }[] }
type Trade = { id: string; accounting_status?: string; order: { venue: Venue; symbol: string; side: string; quantity: string; price: string; strategy_run_id?: string; strategy_signal_id?: string }; mode: string; expires: number; state: string; result: { exchange_status?: string; filled_quantity?: string; message?: string; checked_market_price?: string } }
const names = { binance: '币安 Binance', okx: '欧易 OKX' }
const marketNames: Record<RuntimeMarket, string> = { CRYPTO: '加密货币', US: '美股', CN: 'A 股' }
const environmentNames: Record<RuntimeEnvironment, string> = { platform_sim: '平台模拟', exchange_test: '交易所测试', live: '实盘' }
const states: Record<string, string> = { cancel_rejected: '撤单被拒绝，请查询', rejected: '交易所已拒单', cancel_unknown: '撤单结果未知，请查询', cancel_submitting: '撤单处理中／待核实', preview: '待确认', preview_expired: '预览已过期', submitting: '提交中／待核实', submitted: '交易所已受理', unknown: '结果未知，请核实', reconciled: '已查询', cancel_requested: '撤单已请求，请查询' }
const post = <T,>(path: string, body = {}) => request<T>(`/trading${path}`, { method: 'POST', body: JSON.stringify(body) })
const money = (value: string | number, currency: string) => `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`
const pct = (value: string) => `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`
const intervalNames: Record<Interval, string> = { '15m': '15 分钟', '1h': '1 小时', '4h': '4 小时', '1d': '日线', '1wk': '周线' }
const signalStates: Record<string, string> = { queued: '待执行', filled: '已成交', partially_filled: '部分成交', recommendation: '待人工确认' }
const runCurrency = (run: StrategyRun) => run.currency ?? (run.market === 'CN' ? 'CNY' : run.market === 'US' || run.symbol.endsWith('-USD') ? 'USD' : 'USDT')
const moment = (value: number | string) => new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(typeof value === 'number' ? value * 1000 : value))

function EquityCurve({ run }: { run: StrategyRun }) {
  const points = run.curve ?? []
  if (!points.length) return <p className="trade-detail-empty">首个已完成 K 线处理后，这里会显示净值曲线。</p>
  const values = points.map((point) => Number(point.equity))
  const low = Math.min(...values); const high = Math.max(...values); const spread = high - low || Math.max(Math.abs(high) * 0.01, 1)
  const path = values.map((value, index) => {
    const x = values.length === 1 ? 320 : 12 + (index / (values.length - 1)) * 616
    const y = 142 - ((value - low) / spread) * 124
    return `${index ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`
  }).join(' ')
  return <div className="trade-equity-chart">
    <svg viewBox="0 0 640 160" role="img" aria-label={`${run.strategy_name} 净值曲线，共 ${points.length} 个快照`}>
      <line x1="12" x2="628" y1="142" y2="142" />
      <path d={path} />
    </svg>
    <div><span>{moment(points[0].bar_time)}</span><strong>{money(values.at(-1) ?? run.equity, runCurrency(run))}</strong><span>{moment(points.at(-1)?.bar_time ?? points[0].bar_time)}</span></div>
  </div>
}

function RunDetail({ run }: { run: StrategyRun }) {
  let peak = Number(run.initial_cash); let drawdown = 0
  for (const point of run.curve ?? []) { const equity = Number(point.equity); peak = Math.max(peak, equity); if (peak > 0) drawdown = Math.max(drawdown, (peak - equity) / peak) }
  const fills = run.fills ?? []; const signals = run.signals ?? []; const orders = run.orders ?? []
  return <section className="trade-run-detail" id={`detail-${run.id}`} aria-label={`${run.strategy_name} 运行详情`}>
    <div className="trade-detail-heading"><div><h4>运行详情</h4><p>{run.account_name} · {intervalNames[run.interval]} · 固定初始资金 {money(run.initial_cash, runCurrency(run))}{run.valuation_complete === false && ' · 费用币种未折算，以下为已知覆盖范围'}</p></div><a href={`#/journal/trading?run=${run.id}`}>在账本中追溯</a></div>
    <div className="trade-detail-layout">
      <section><h5>净值曲线</h5><EquityCurve run={run} /></section>
      <section><h5>当前资产</h5><dl className="trade-position-list">
        <div><dt>最大回撤</dt><dd>{run.valuation_complete === false || !run.curve?.length ? '待完整估值' : `${(drawdown * 100).toFixed(2)}%`}</dd></div><div><dt>现金</dt><dd>{money(run.cash, runCurrency(run))}</dd></div><div><dt>持仓数量</dt><dd>{run.quantity}</dd></div>
        <div><dt>持仓成本</dt><dd>{money(run.average_cost, runCurrency(run))}</dd></div><div><dt>最新价格</dt><dd>{run.mark_price ? money(run.mark_price, runCurrency(run)) : '待行情'}</dd></div>
        <div><dt>持仓市值</dt><dd>{money(run.position_value ?? '0', runCurrency(run))}</dd></div><div><dt>已实现收益</dt><dd className={Number(run.realized_pnl) >= 0 ? 'positive' : 'negative'}>{money(run.realized_pnl, runCurrency(run))}</dd></div>
      </dl></section>
    </div>
    {run.latest_error && <div className="trade-run-alert" role="alert"><strong>运行与估值状态</strong><p>{run.latest_error}</p></div>}
    <div className="trade-detail-layout trade-detail-records">
      <section><h5>信号与原因</h5>{signals.length ? <ol className="trade-signal-list">{signals.map((signal) => <li key={signal.id}><div><strong>{signal.target}</strong><span>{signalStates[signal.status] ?? signal.status}</span></div><p>{signal.reason || '未记录原因'}</p><time>{moment(signal.created_at)}</time></li>)}</ol> : <p className="trade-detail-empty">暂无信号。实例完成首次行情基线后会记录判断原因。</p>}</section>
      <section><h5>模拟委托</h5>{orders.length ? <ol className="trade-signal-list">{orders.map((order) => <li key={order.id}><div><strong>{order.side === 'buy' ? '买入' : '卖出'} {order.requested_quantity}</strong><span>{order.status === 'filled' ? '已成交' : order.status === 'partial_expired' ? '部分成交' : order.status}</span></div><p>已成交 {order.filled_quantity}{order.status === 'partial_expired' && '；本根 K 线余量已作废'}</p><time>{moment(order.created_at)}</time></li>)}</ol> : <p className="trade-detail-empty">暂无模拟委托。信号触发后会记录请求数量和成交结果。</p>}</section>
      <section><h5>成交记录</h5>{fills.length ? <div className="trade-table"><table><thead><tr><th>时间</th><th>方向／数量</th><th>价格／费用</th></tr></thead><tbody>{fills.map((fill) => <tr key={fill.id}><td>{moment(fill.executed_at)}</td><td>{fill.side === 'buy' ? '买入' : '卖出'}<small>{fill.quantity} {run.symbol.split('-')[0]}</small></td><td>{money(fill.price, runCurrency(run))}<small>费用 {fill.fee} {fill.fee_currency}</small></td></tr>)}</tbody></table></div> : <p className="trade-detail-empty">暂无成交。历史预热行情不会计入启动后的收益。</p>}</section>
    </div>
  </section>
}

export default function TradingWorkspace() {
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [venue, setVenue] = useState<Venue>('binance')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('buy')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [preview, setPreview] = useState<Trade | null>(null)
  const [strategyLink, setStrategyLink] = useState<{ runId: string; signalId: string } | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [orders, setOrders] = useState<Trade[]>([])
  const [balances, setBalances] = useState<{ asset: string; available: string; locked: string }[] | null>(null)
  const [accounts, setAccounts] = useState<RuntimeAccount[]>([])
  const [runs, setRuns] = useState<StrategyRun[]>([])
  const [releases, setReleases] = useState<StrategyRelease[]>([])
  const [subscriptions, setSubscriptions] = useState<StrategySubscription[]>([])
  const [runRelease, setRunRelease] = useState(query.get('release') ?? '')
  const [runMarket, setRunMarket] = useState<RuntimeMarket>('CRYPTO')
  const [runEnvironment, setRunEnvironment] = useState<RuntimeEnvironment>('platform_sim')
  const [runAccount, setRunAccount] = useState('')
  const [runSymbol, setRunSymbol] = useState('BTC-USD')
  const [runCash, setRunCash] = useState('10000')
  const [runInterval, setRunInterval] = useState<Interval>('1d')
  const [demoAuto, setDemoAuto] = useState(false)
  const [commissionRate, setCommissionRate] = useState('0.001')
  const [slippageRate, setSlippageRate] = useState('0.0005')
  const [maxPosition, setMaxPosition] = useState('0.95')
  const [maxParticipation, setMaxParticipation] = useState('0.01')
  const [stopLoss, setStopLoss] = useState('0')
  const [takeProfit, setTakeProfit] = useState('0')
  const [marketFilter, setMarketFilter] = useState<'' | RuntimeMarket>('')
  const [environmentFilter, setEnvironmentFilter] = useState<'' | RuntimeEnvironment>('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [focusedRun, setFocusedRun] = useState(query.get('run') ?? '')
  const [expandedRuns, setExpandedRuns] = useState<Record<string, boolean>>({})
  const [runDetails, setRunDetails] = useState<Record<string, StrategyRun>>({})
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({})
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const selected = caps?.venues.find((item) => item.venue === venue)
  const phrase = preview?.mode === 'live' ? '确认实盘下单' : '确认模拟下单'

  const loadRunDetail = useCallback(async (identifier: string) => {
    setDetailLoading((current) => ({ ...current, [identifier]: true }))
    setDetailErrors((current) => ({ ...current, [identifier]: '' }))
    try {
      const detail = await request<StrategyRun>(`/trading/runs/${identifier}`)
      setRunDetails((current) => ({ ...current, [identifier]: detail }))
    } catch (cause) {
      setDetailErrors((current) => ({ ...current, [identifier]: cause instanceof Error ? cause.message : '运行详情读取失败，请重试。' }))
    } finally {
      setDetailLoading((current) => ({ ...current, [identifier]: false }))
    }
  }, [])

  const load = useCallback(async () => {
    const currentQuery = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
    const linkedRunId = currentQuery.get('run') ?? ''
    const linkedReleaseId = currentQuery.get('release') ?? ''
    const next = await request<Capabilities>('/trading/capabilities')
    const [nextRuns, nextAccounts, nextReleases, nextSubscriptions, linkedRun] = await Promise.all([
      request<StrategyRun[]>(`/trading/runs?market=${marketFilter}&environment=${environmentFilter}`),
      request<RuntimeAccount[]>('/trading/accounts'), request<StrategyRelease[]>('/strategy-releases'),
      request<StrategySubscription[]>('/strategy-subscriptions'),
      linkedRunId ? request<StrategyRun>(`/trading/runs/${linkedRunId}`).catch(() => null) : Promise.resolve(null),
    ])
    setCaps(next)
    const listedRuns = Array.isArray(nextRuns) ? nextRuns : []
    const listedReleases = Array.isArray(nextReleases) ? nextReleases : []
    setRuns(linkedRun && !listedRuns.some((item) => item.id === linkedRun.id) ? [linkedRun, ...listedRuns] : listedRuns)
    setAccounts(Array.isArray(nextAccounts) ? nextAccounts : [])
    setReleases(listedReleases)
    setSubscriptions(Array.isArray(nextSubscriptions) ? nextSubscriptions : [])
    if (linkedReleaseId && listedReleases.some((item) => item.id === linkedReleaseId)) setRunRelease(linkedReleaseId)
    else if (listedReleases[0]) setRunRelease((current) => current || listedReleases[0].id)
    setFocusedRun(linkedRunId)
    if (linkedRun) setRunDetails((current) => ({ ...current, [linkedRun.id]: linkedRun }))
    if (next.authorized) setOrders(await request<Trade[]>('/trading/orders'))
    setLoaded(true)
  }, [marketFilter, environmentFilter, setAccounts, setCaps, setFocusedRun, setLoaded, setOrders, setReleases, setRunRelease, setRuns, setSubscriptions])
  useEffect(() => {
    const timer = window.setTimeout(() => void load().catch((cause: Error) => setError(cause.message)), 0)
    const refresh = () => { if (document.visibilityState === 'visible') void load().catch(() => undefined) }
    window.addEventListener(RUNTIME_CHANGED_EVENT, refresh); document.addEventListener('visibilitychange', refresh); window.addEventListener('hashchange', refresh)
    document.title = '策略交易 · Atlas'
    return () => { window.clearTimeout(timer); window.removeEventListener(RUNTIME_CHANGED_EVENT, refresh); document.removeEventListener('visibilitychange', refresh); window.removeEventListener('hashchange', refresh) }
  }, [load])
  useEffect(() => {
    if (!focusedRun || !runs.some((run) => run.id === focusedRun)) return
    const timer = window.setTimeout(() => document.getElementById(focusedRun)?.scrollIntoView({ block: 'center' }), 0)
    setExpandedRuns((current) => current[focusedRun] ? current : { ...current, [focusedRun]: true })
    if (!runDetails[focusedRun] && !detailLoading[focusedRun] && !detailErrors[focusedRun]) void loadRunDetail(focusedRun)
    return () => window.clearTimeout(timer)
  }, [detailErrors, detailLoading, focusedRun, loadRunDetail, runDetails, runs])
  useEffect(() => {
    const identifier = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('order')
    if (identifier && orders.some((order) => order.id === identifier)) {
      document.getElementById(`order-${identifier}`)?.scrollIntoView({ block: 'center' })
    }
  }, [orders])

  async function action(work: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError('')
    try { await work() } catch (cause) { setError(cause instanceof Error ? cause.message : '请求失败') }
    finally { setBusy(false) }
  }
  function invalidate() { setPreview(null); setConfirmation('') }
  function editOrder() { invalidate(); setStrategyLink(null) }
  function prepareRecommendation(run: StrategyRun) {
    if (!run.recommendation) return
    setVenue(run.account_name?.toLowerCase().includes('okx') ? 'okx' : 'binance')
    setSymbol(run.symbol); setSide(run.recommendation.side); setQuantity(run.recommendation.quantity)
    setPrice(run.recommendation.reference_price); setStrategyLink({ runId: run.id, signalId: run.recommendation.id })
    setPreview(null); setConfirmation(''); setNotice('已带入策略建议。预览时会重新核对绑定账户、预算和交易所余额。')
    window.setTimeout(() => document.querySelector('.trade-ticket')?.scrollIntoView({ block: 'center' }), 0)
  }
  const allowedReleases = releases.filter((item) => item.owned || subscriptions.some((sub) => sub.release_id === item.id && sub.status === 'active'))
  const selectedRunCurrency = runMarket === 'CN' ? 'CNY' : runMarket === 'US' || runSymbol.endsWith('-USD') ? 'USD' : 'USDT'
  const availableRunAccounts = accounts.filter((item) => item.market === runMarket && item.environment === runEnvironment && item.currency === selectedRunCurrency)
  const linkedStrategy = strategyLink ? runs.find((run) => run.id === strategyLink.runId) : undefined
  const totals = useMemo(() => runs.reduce((result, run) => {
    const currency = runCurrency(run)
    const key = `${run.environment}:${currency}`
    const item = result[key] ?? { equity: 0, profit: 0, currency, environment: run.environment, valuationComplete: true }
    item.equity += Number(run.equity); item.profit += Number(run.equity) - Number(run.initial_cash)
    item.valuationComplete = item.valuationComplete && run.valuation_complete !== false; result[key] = item
    return result
  }, {} as Record<string, { equity: number; profit: number; currency: string; environment: RuntimeEnvironment; valuationComplete: boolean }>), [runs])

  return <main className="trading-workspace">
    <header className="trade-heading"><div><em>STRATEGY OPERATIONS</em><h1>策略交易</h1><p>订阅策略、运行模拟组合，实盘信号仍由你逐笔确认。</p></div><button disabled={busy} onClick={() => void action(load)}><RefreshCw size={15} />刷新全部数据</button></header>
    {error && <p className="trade-error" role="alert">{error}</p>}{notice && <p className="trade-notice" role="alert">{notice}</p>}
    <DemoAccountSetup onConnected={load} />
    <section className="trade-controlbar"><div>{(['', 'CRYPTO', 'US', 'CN'] as const).map((item) => <button key={item || 'all'} className={marketFilter === item ? 'is-active' : ''} onClick={() => setMarketFilter(item)}>{item ? marketNames[item] : '全部市场'}</button>)}</div><label>环境<select value={environmentFilter} onChange={(event) => setEnvironmentFilter(event.target.value as '' | RuntimeEnvironment)}><option value="">全部环境</option><option value="platform_sim">平台模拟</option><option value="exchange_test">交易所测试</option><option value="live">实盘</option></select></label></section>
    <section className="trade-kpis"><article><span>策略实例净值</span>{Object.entries(totals).length ? Object.entries(totals).map(([key, item]) => <strong key={key}><small>{environmentNames[item.environment]} · </small>{money(item.equity, item.currency)}{!item.valuationComplete && <small>费用覆盖不完整</small>}</strong>) : <strong>—</strong>}</article><article><span>累计净收益</span>{Object.entries(totals).length ? Object.entries(totals).map(([key, item]) => <strong className={item.profit >= 0 ? 'positive' : 'negative'} key={key}><small>{environmentNames[item.environment]} · </small>{item.valuationComplete ? `${item.profit >= 0 ? '+' : ''}${money(item.profit, item.currency)}` : '不可完整计算'}{!item.valuationComplete && <small>已知变动 {item.profit >= 0 ? '+' : ''}{money(item.profit, item.currency)}</small>}</strong>) : <strong>—</strong>}</article><article><span>活动策略</span><strong>{runs.filter((item) => item.status === 'active').length}</strong><small>{runs.length} 个运行实例</small></article><article><span>运行异常</span><strong>{runs.filter((item) => item.status === 'error').length}</strong><small>行情缺失时自动停住</small></article></section>

    <section className="trade-strategies"><header><div><h2>我的运行策略</h2><p>一个实例只负责一个标的；暂停和停止都不会自动清仓。</p></div><a href="#quantjudge"><BookOpen size={15} />策略库</a></header>
      <form className="trade-run-form" onSubmit={(event) => { event.preventDefault(); void action(async () => {
        const release = allowedReleases.find((item) => item.id === runRelease); if (!release) return
        const subscription = subscriptions.find((item) => item.release_id === release.id && item.status === 'active')
        const account = availableRunAccounts.find((item) => item.id === runAccount) ?? availableRunAccounts[0]
        const created = await request<StrategyRun>('/trading/runs', { method: 'POST', body: JSON.stringify({ release_id: release.id, subscription_id: subscription?.id, account_id: account?.id, market: runMarket, environment: runEnvironment, symbol: runSymbol, interval: runInterval, initial_cash: runCash, demo_auto: runEnvironment === 'exchange_test' && demoAuto, commission_rate: commissionRate, slippage_rate: slippageRate, max_position: maxPosition, max_participation: maxParticipation, stop_loss: stopLoss, take_profit: takeProfit }) })
        await request(`/trading/runs/${created.id}/start`, { method: 'POST' }); setNotice('策略实例已启动，首次运行将建立行情基线。'); await load()
      }) }}>
        <label>策略版本<select value={runRelease} onChange={(event) => setRunRelease(event.target.value)}>{allowedReleases.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label>
        <label>市场<select value={runMarket} onChange={(event) => { const market = event.target.value as RuntimeMarket; setRunMarket(market); setRunAccount(''); if (market !== 'CRYPTO') setRunEnvironment('platform_sim'); if (market === 'CN' && !['1d', '1wk'].includes(runInterval)) setRunInterval('1d'); setRunSymbol(market === 'CRYPTO' ? 'BTC-USD' : market === 'US' ? 'AAPL' : '600519.SS') }}>{(['CRYPTO', 'US', 'CN'] as RuntimeMarket[]).map((item) => <option key={item} value={item}>{marketNames[item]}</option>)}</select></label>
        <label>运行环境<select value={runEnvironment} onChange={(event) => { const environment = event.target.value as RuntimeEnvironment; setRunEnvironment(environment); setRunAccount(''); if (runMarket === 'CRYPTO') setRunSymbol(environment === 'platform_sim' ? 'BTC-USD' : 'BTC-USDT') }}><option value="platform_sim">平台模拟</option>{Array.from(new Set(accounts.filter((item) => item.market === runMarket && item.environment !== 'platform_sim').map((item) => item.environment))).map((item) => <option key={item} value={item}>{environmentNames[item]}</option>)}</select></label>
        <label>交易账户<select value={runAccount} onChange={(event) => setRunAccount(event.target.value)}>{availableRunAccounts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>标的<input required value={runSymbol} onChange={(event) => { setRunSymbol(event.target.value.toUpperCase()); setRunAccount('') }} /></label>
        <label>周期<select value={runInterval} onChange={(event) => setRunInterval(event.target.value as Interval)}>{(['15m', '1h', '4h', '1d', '1wk'] as Interval[]).filter((item) => runMarket !== 'CN' || ['1d', '1wk'].includes(item)).map((item) => <option key={item} value={item}>{intervalNames[item]}</option>)}</select></label>
        {runEnvironment === 'exchange_test' && <label><input type="checkbox" checked={demoAuto} onChange={(event) => setDemoAuto(event.target.checked)} />自动执行模拟订单（仅测试资金）</label>}
        <label>分配资金<input required type="number" min="1" value={runCash} onChange={(event) => setRunCash(event.target.value)} /></label>
        <button className="trade-primary" disabled={busy || !runRelease || !availableRunAccounts.length}><Play size={15} />{runEnvironment === 'platform_sim' ? '启动模拟' : runEnvironment === 'exchange_test' && demoAuto ? '启动测试交易' : '启动信号监控'}</button>
        <details className="trade-run-risk"><summary>风控与成交假设</summary><div><label>手续费率<input type="number" min="0" max="0.1" step="0.0001" value={commissionRate} onChange={(event) => setCommissionRate(event.target.value)} /></label><label>滑点率<input type="number" min="0" max="0.1" step="0.0001" value={slippageRate} onChange={(event) => setSlippageRate(event.target.value)} /></label><label>最大仓位<input type="number" min="0.01" max="1" step="0.01" value={maxPosition} onChange={(event) => setMaxPosition(event.target.value)} /></label><label>成交参与率<input type="number" min="0.0001" max="1" step="0.0001" value={maxParticipation} onChange={(event) => setMaxParticipation(event.target.value)} /></label><label>止损比例<input type="number" min="0" max="0.99" step="0.01" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} /></label><label>止盈比例<input type="number" min="0" max="10" step="0.01" value={takeProfit} onChange={(event) => setTakeProfit(event.target.value)} /></label></div></details>
      </form>
      <div className="trade-run-grid">{runs.map((run) => {
        const expanded = !!expandedRuns[run.id]; const detail = runDetails[run.id]
        return <article key={run.id} id={run.id} className={expanded ? 'is-expanded' : ''}><header><span>{marketNames[run.market]} · {environmentNames[run.environment]}</span><em className={`is-${run.status}`}>{run.status === 'active' ? '运行中' : run.status === 'paused' ? '已暂停' : run.status === 'stopped' ? '已停止' : run.status === 'error' ? '待处理' : '待启动'}</em></header><h3>{run.demo_auto === '1' && <small>模拟自动执行 · </small>}{run.strategy_name} <small>v{run.strategy_version}</small></h3><p>{run.symbol} · {intervalNames[run.interval]} · {run.latest_signal ?? '等待首个收盘信号'}</p><div className="trade-run-money"><span><small>净值</small><strong>{money(run.equity, runCurrency(run))}</strong></span><span><small>收益率</small>{run.valuation_complete === false ? <strong>不可完整计算<small>已知 {pct(run.return_rate)}</small></strong> : <strong className={Number(run.return_rate) >= 0 ? 'positive' : 'negative'}>{pct(run.return_rate)}</strong>}</span></div>{run.latest_error && <p className="trade-error">{run.latest_error}</p>}<footer>{run.recommendation && <button className="trade-recommendation" onClick={() => prepareRecommendation(run)}><Activity size={14} />预览策略建议</button>}{run.status === 'active' && <button onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/pause`, { method: 'POST' }); await load(); if (expanded) await loadRunDetail(run.id) })}><Pause size={14} />暂停</button>}{['paused', 'error'].includes(run.status) && <button onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/resume`, { method: 'POST' }); await load(); if (expanded) await loadRunDetail(run.id) })}><Play size={14} />恢复</button>}{run.status !== 'stopped' && <button onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/stop`, { method: 'POST' }); await load(); if (expanded) await loadRunDetail(run.id) })}><Square size={14} />停止</button>}<button disabled={run.status !== 'active'} onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/tick`, { method: 'POST' }); await load(); if (expanded) await loadRunDetail(run.id) })}><RefreshCw size={14} />立即检查</button><button className="trade-detail-toggle" aria-expanded={expanded} aria-controls={`detail-${run.id}`} onClick={() => { setExpandedRuns((current) => ({ ...current, [run.id]: !expanded })); if (!expanded) void loadRunDetail(run.id) }}>{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}{expanded ? '收起详情' : '运行详情'}</button><a href={`#/journal/trading?run=${run.id}`}><Activity size={14} />成交与账本</a></footer>{expanded && (detailLoading[run.id] ? <p className="trade-detail-state" role="status">正在读取净值、持仓和交易记录…</p> : detailErrors[run.id] ? <div className="trade-detail-state trade-run-alert" role="alert"><p>{detailErrors[run.id]}</p><button onClick={() => void loadRunDetail(run.id)}>重新读取</button></div> : detail ? <RunDetail run={detail} /> : null)}</article>
      })}{loaded && !runs.length && <p className="trade-empty">尚未运行策略。先从策略中心发布或订阅一个可运行版本。</p>}</div>
    </section>

    <div className="trade-columns"><section className="trade-ticket"><h2>账户操作 · 现货限价单</h2><form onSubmit={(event) => { event.preventDefault(); void action(async () => { const next = await post<Trade>('/orders/preview', { venue, symbol, side, quantity, price, strategy_run_id: strategyLink?.runId, strategy_signal_id: strategyLink?.signalId }); setPreview(next); setConfirmation(''); await load() }) }}><fieldset disabled={busy || !!preview}><label>交易所<select value={venue} onChange={(event) => { setVenue(event.target.value as Venue); setBalances(null); editOrder() }}><option value="binance">币安 Binance</option><option value="okx">欧易 OKX</option></select></label><p className={selected?.mode === 'live' ? 'trade-live' : 'trade-environment'}>{selected?.mode === 'live' ? '实盘 · 将使用真实资金' : '测试环境 · 不使用真实资金'} · {selected?.configured ? '已配置 · 待验证' : '账户未配置'}</p>{strategyLink && <div className="trade-strategy-attribution" role="status"><span><Activity size={15} /><strong>策略建议</strong> · {linkedStrategy ? `${linkedStrategy.strategy_name} v${linkedStrategy.strategy_version}` : '已关联运行实例'}<small>{strategyLink.runId}</small></span><button type="button" onClick={() => setStrategyLink(null)}>解除关联</button></div>}<label>交易对<input required value={symbol} placeholder="例如 BTC-USDT" pattern="[A-Z0-9]{2,15}-USDT" onChange={(event) => { setSymbol(event.target.value.toUpperCase()); editOrder() }} /></label><label>方向<select value={side} onChange={(event) => { setSide(event.target.value); editOrder() }}><option value="buy">买入</option><option value="sell">卖出</option></select></label><div className="trade-fields"><label>数量（基础币）<input required inputMode="decimal" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidate() }} /></label><label>限价（USDT）<input required inputMode="decimal" value={price} onChange={(event) => { setPrice(event.target.value); invalidate() }} /></label></div><button className="trade-primary" disabled={!selected?.can_trade}>预览订单</button></fieldset></form>
      {preview && <section className="trade-review" aria-label="确认订单"><h3>{preview.mode === 'live' ? '核对实盘订单' : '核对模拟订单'}</h3>{preview.order.strategy_run_id && <p className="trade-review-attribution"><Activity size={15} />策略订单 · {runs.find((run) => run.id === preview.order.strategy_run_id)?.strategy_name ?? preview.order.strategy_run_id}</p>}<p>{names[preview.order.venue]} · {preview.order.symbol} · {preview.order.side === 'buy' ? '买入' : '卖出'}</p><p>数量 {preview.order.quantity} · 限价 {preview.order.price} USDT</p>{preview.result.checked_market_price && <p>交易所最新价 {preview.result.checked_market_price} USDT，限价和数量已通过交易所规则校验。</p>}<p>预览两分钟内有效。请输入“{phrase}”后提交。</p><label>确认文字<input value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></label><div className="trade-actions"><button disabled={busy} onClick={invalidate}>返回修改</button><button className="trade-primary" disabled={busy || confirmation !== phrase} onClick={() => void action(async () => { const result = await post<Trade>(`/orders/${preview.id}/confirm`, { confirmation }); setNotice(['unknown', 'submitting'].includes(result.state) ? `订单 ${result.id} 结果未确认。请查询状态，不要重复下单。` : '订单已提交，成交后请刷新核实。'); invalidate(); setStrategyLink(null); await load() })}>确认提交订单</button></div></section>}
      {!selected?.can_trade && caps?.authorized && <p>订单提交尚未启用，请先配置测试账户。</p>}</section>
      <aside className="trade-account"><h2>账户与连接</h2>{accounts.filter((item) => !marketFilter || item.market === marketFilter).map((account) => <div className="trade-account-row" key={account.id}><Wallet size={16} /><span><strong>{account.name}</strong><small>{marketNames[account.market]} · {account.currency}</small></span><em>{environmentNames[account.environment]}</em></div>)}<button disabled={busy || !selected?.configured} onClick={() => void action(async () => { setBalances(null); const response = await request<{ balances: NonNullable<typeof balances> }>(`/trading/${venue}/account`); setBalances(response.balances) })}>连接并查询余额</button>{balances && <div className="trade-table"><table><thead><tr><th>资产</th><th>可用</th><th>冻结</th></tr></thead><tbody>{balances.map((row) => <tr key={row.asset}><td>{row.asset}</td><td>{row.available}</td><td>{row.locked}</td></tr>)}</tbody></table></div>}<section className="trade-broker"><h2>真实市场连接</h2><p><strong>加密货币</strong> · 币安/欧易现货。</p><p><strong>美股</strong> · 券商接口待接入，平台模拟可用。</p><p><strong>A 股</strong> · <strong>miniQMT · 等待客户端接入</strong>，平台模拟可用。</p></section></aside>
    </div>

    {!caps && !error && <p role="status">正在读取接入状态…</p>}{caps && !caps.authorized && <section className="trade-setup"><h2>先绑定你的交易账户</h2><p>在页面顶部展开“接入模拟交易账户”，验证并保存币安或欧易测试密钥，即可选择账户运行订阅策略。</p></section>}
    <section className="trade-orders"><h2>最近交易所订单</h2><p>受理不等于成交。结果未知时先查询，请勿重复下单。</p><div className="trade-table"><table><thead><tr><th>交易对／环境</th><th>委托</th><th>状态／成交数量</th><th>操作</th></tr></thead><tbody>{orders.map((row) => <tr key={row.id} id={`order-${row.id}`}><td>{row.order.symbol}<small>{names[row.order.venue]} · {row.mode === 'live' ? '实盘' : '模拟'}</small>{row.order.strategy_run_id && <small className="trade-order-attribution">策略 · {runs.find((run) => run.id === row.order.strategy_run_id)?.strategy_name ?? row.order.strategy_run_id}</small>}</td><td>{row.order.side === 'buy' ? '买入' : '卖出'} {row.order.quantity}<small>@ {row.order.price} USDT</small></td><td>{states[row.state] ?? row.state}<small>{row.result.exchange_status ?? row.result.message ?? '尚未发送'}{row.result.filled_quantity && ` · 已成交 ${row.result.filled_quantity}`}</small>{row.accounting_status === 'cost_incomplete' && <small>成交成本待补全 · 收益不可计算</small>}{row.accounting_status === 'pending_sync' && <small>成交明细待同步</small>}</td><td>{!['preview', 'preview_expired', 'rejected'].includes(row.state) && <div className="trade-actions"><button disabled={busy} onClick={() => void action(async () => { await post(`/orders/${row.id}/refresh`); await load() })}>查询状态</button><button disabled={busy || row.state === 'submitting'} onClick={() => { if (window.confirm(`确认撤销 ${row.order.symbol} 的订单？`)) void action(async () => { await post(`/orders/${row.id}/cancel`, { confirmation: '确认撤单' }); await load() }) }}>撤单</button></div>}</td></tr>)}</tbody></table></div>{loaded && !orders.length && <p>暂无交易所订单。</p>}</section>
    {busy && <p role="status">正在处理请求，请稍候…</p>}
  </main>
}
