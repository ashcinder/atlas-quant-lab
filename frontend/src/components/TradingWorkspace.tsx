import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, ArrowRight, Layers3, ListOrdered, Plus, ShieldCheck, X, Activity, BookOpen, CheckCircle2, CircleHelp, Link2, LoaderCircle, ChevronDown, ChevronUp, Pause, Play, RefreshCw, Square, Wallet } from 'lucide-react'
import { request, RUNTIME_CHANGED_EVENT } from '../request'
import type { Interval, RuntimeAccount, RuntimeEnvironment, RuntimeMarket, StrategyRelease, StrategyRun, StrategySubscription } from '../types'
import { Dialog } from '@base-ui/react/dialog'
import DemoAccountSetup from './DemoAccountSetup'
import './trading.css'
import './trading-refinement.css'
import TradingEquityChart from './TradingEquityChart'

type Venue = 'binance' | 'okx'
type Capabilities = { authorized: boolean; user_id: string; venues: { venue: Venue; mode: string; configured: boolean; can_trade: boolean }[] }
type Trade = { id: string; accounting_status?: string; order: { venue: Venue; symbol: string; side: string; quantity: string; price: string; strategy_run_id?: string; strategy_signal_id?: string }; mode: string; expires: number; state: string; result: { exchange_status?: string; filled_quantity?: string; message?: string; checked_market_price?: string } }
const names = { binance: '币安 Binance', okx: '欧易 OKX' }
const marketNames: Record<RuntimeMarket, string> = { CRYPTO: '加密货币', US: '美股', CN: 'A 股' }
const environmentNames: Record<RuntimeEnvironment, string> = { platform_sim: '平台模拟', exchange_test: '交易所测试', live: '实盘' }
const states: Record<string, string> = { cancel_rejected: '撤单被拒绝，请查询', rejected: '交易所已拒单', cancel_unknown: '撤单结果未知，请查询', cancel_submitting: '撤单处理中／待核实', preview: '待确认', preview_expired: '预览已过期', submitting: '提交中／待核实', submitted: '交易所已受理', unknown: '结果未知，请核实', reconciled: '已查询', cancel_requested: '撤单已请求，请查询' }
const post = <T,>(path: string, body = {}) => request<T>(`/trading${path}`, { method: 'POST', body: JSON.stringify(body) })
const money = (value: string | number, currency: string) => `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${currency}`
const balanceAmount = (value: string) => value.replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
const pct = (value: string) => `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`
const intervalNames: Record<Interval, string> = { '15m': '15 分钟', '1h': '1 小时', '4h': '4 小时', '1d': '日线', '1wk': '周线' }
const signalStates: Record<string, string> = { queued: '待执行', filled: '已成交', partially_filled: '部分成交', recommendation: '待人工确认' }
const runCurrency = (run: StrategyRun) => run.currency ?? (run.market === 'CN' ? 'CNY' : run.market === 'US' || run.symbol.endsWith('-USD') ? 'USD' : 'USDT')
const moment = (value: number | string) => new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(typeof value === 'number' ? value * 1000 : value))

function RunDetail({ run }: { run: StrategyRun }) {
  const [recordTab, setRecordTab] = useState<'fills' | 'signals' | 'orders'>('fills')
  let peak = Number(run.initial_cash); let drawdown = 0
  for (const point of run.curve ?? []) { const equity = Number(point.equity); peak = Math.max(peak, equity); if (peak > 0) drawdown = Math.max(drawdown, (peak - equity) / peak) }
  const fills = run.fills ?? []; const signals = run.signals ?? []; const orders = run.orders ?? []
  return <section className="trade-run-detail" id={`detail-${run.id}`} aria-label={`${run.strategy_name} 运行详情`}>
    <div className="trade-detail-heading"><div><h4>运行详情</h4><p>{run.account_name} · {run.execution_mode === 'private_runner' ? '开发者本地执行' : run.execution_mode === 'quote_probe' ? '10秒报价联调' : intervalNames[run.interval]} · 固定初始资金 {money(run.initial_cash, runCurrency(run))}{run.valuation_complete === false && ' · 费用币种未折算，以下为已知覆盖范围'}</p></div><a href={`#/journal/trading?run=${run.id}`}>在账本中追溯</a></div>
    {run.execution_mode === 'private_runner' && <><p className="trade-probe-note">证据等级：开发者签名信号。源码未上传；尚无ZKP/TEE执行证明。当前为实时报价驱动的平台模拟收益，不是交易所账户收益。</p><details><summary>本地执行连接配置（无源码或私钥）</summary><p>保存以下JSON为run.json，在开发者本地启动runner。持续模式使用 --continuous --interval 12；关闭网页不影响本地进程。暂停或停止实例后信号将被拒绝，恢复时需重新启动本地 runner。没有签名信号时不会自动交易；下方曲线为最后一次成交报价估值。</p><pre>{JSON.stringify({ api_url: window.location.origin, run_id: run.id, release_id: run.release_id, content_hash: run.strategy_hash }, null, 2)}</pre></details></>}
    <div className="trade-detail-layout">
      <section><h5>净值曲线</h5><TradingEquityChart run={run} /></section>
      <section><h5>当前资产</h5><dl className="trade-position-list">
        <div><dt>最大回撤</dt><dd>{run.valuation_complete === false || !run.curve?.length ? '待完整估值' : `${(drawdown * 100).toFixed(2)}%`}</dd></div><div><dt>现金</dt><dd>{money(run.cash, runCurrency(run))}</dd></div><div><dt>持仓数量</dt><dd>{run.quantity}</dd></div>
        <div><dt>持仓成本</dt><dd>{money(run.average_cost, runCurrency(run))}</dd></div><div><dt>最新价格</dt><dd>{run.mark_price ? money(run.mark_price, runCurrency(run)) : '待行情'}</dd></div>
        <div><dt>持仓市值</dt><dd>{money(run.position_value ?? '0', runCurrency(run))}</dd></div><div><dt>已实现收益</dt><dd className={Number(run.realized_pnl) >= 0 ? 'positive' : 'negative'}>{money(run.realized_pnl, runCurrency(run))}</dd></div>
      </dl></section>
    </div>
    {run.latest_error && <div className="trade-run-alert" role="alert"><strong>运行与估值状态</strong><p>{run.latest_error}</p></div>}
    <div className="trade-record-tabs" role="tablist" aria-label="运行记录">{([{ id: 'fills', label: '成交记录', count: fills.length }, { id: 'signals', label: '信号与原因', count: signals.length }, { id: 'orders', label: '模拟委托', count: orders.length }] as const).map(tab => <button key={tab.id} role="tab" aria-selected={recordTab === tab.id} tabIndex={recordTab === tab.id ? 0 : -1} onKeyDown={event => { const ids = ['fills', 'signals', 'orders'] as const; const index = ids.indexOf(tab.id); const next = event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : null; if (next !== null) { event.preventDefault(); setRecordTab(ids[next]); document.getElementById(`${run.id}-${ids[next]}-tab`)?.focus() } }} aria-controls={`${run.id}-${tab.id}`} id={`${run.id}-${tab.id}-tab`} onClick={() => setRecordTab(tab.id)}>{tab.label}<span>{tab.count}</span></button>)}</div>
    <div className="trade-detail-layout trade-detail-records">
      <section role="tabpanel" id={`${run.id}-signals`} aria-labelledby={`${run.id}-signals-tab`} hidden={recordTab !== 'signals'}><h5 className="trade-record-panel-title">信号与原因</h5>{signals.length ? <ol className="trade-signal-list">{signals.map((signal) => <li key={signal.id}><div><strong>{signal.target}</strong><span>{signalStates[signal.status] ?? signal.status}</span></div><p>{signal.reason || '未记录原因'}</p><time>{moment(signal.created_at)}</time></li>)}</ol> : <p className="trade-detail-empty">暂无信号。实例完成首次行情基线后会记录判断原因。</p>}</section>
      <section role="tabpanel" id={`${run.id}-orders`} aria-labelledby={`${run.id}-orders-tab`} hidden={recordTab !== 'orders'}><h5 className="trade-record-panel-title">模拟委托</h5>{orders.length ? <ol className="trade-signal-list">{orders.map((order) => <li key={order.id}><div><strong>{order.side === 'buy' ? '买入' : '卖出'} {order.requested_quantity}</strong><span>{order.status === 'filled' ? '已成交' : order.status === 'partial_expired' ? '部分成交' : order.status}</span></div><p>已成交 {order.filled_quantity}{order.status === 'partial_expired' && ((run.execution_mode === 'quote_probe' || run.execution_mode === 'private_runner') ? '；本次报价余量已作废' : '；本根 K 线余量已作废')}</p><time>{moment(order.created_at)}</time></li>)}</ol> : <p className="trade-detail-empty">暂无模拟委托。信号触发后会记录请求数量和成交结果。</p>}</section>
      <section role="tabpanel" id={`${run.id}-fills`} aria-labelledby={`${run.id}-fills-tab`} hidden={recordTab !== 'fills'}><h5 className="trade-record-panel-title">成交记录</h5>{fills.length ? <div className="trade-table"><table><thead><tr><th>时间</th><th>方向／数量</th><th>价格／费用</th></tr></thead><tbody>{fills.map((fill) => <tr key={fill.id}><td>{moment(fill.executed_at)}</td><td>{fill.side === 'buy' ? '买入' : '卖出'}<small>{fill.quantity} {run.symbol.split('-')[0]}</small></td><td>{money(fill.price, runCurrency(run))}<small>费用 {fill.fee} {fill.fee_currency}</small></td></tr>)}</tbody></table></div> : <p className="trade-detail-empty">暂无成交。历史预热行情不会计入启动后的收益。</p>}</section>
    </div>
  </section>
}

type ConnectionProps = {
  caps: Capabilities | null
  venue: Venue
  accounts: RuntimeAccount[]
  locked: boolean
  onRefresh: () => Promise<void>
  onConnect: () => void
}

// The parent keys this panel by venue, environment and permission configuration.
// Unmounting invalidates pending queries so a previous account cannot populate this one.
function AccountConnection({ caps, venue, accounts, locked, onRefresh, onConnect }: ConnectionProps) {
  const selected = caps?.venues.find((item) => item.venue === venue)
  const [result, setResult] = useState<{ balances: { asset: string; available: string; locked: string }[]; checkedAt: Date } | null>(null)
  const [pending, setPending] = useState(false)
  const [connectionError, setConnectionError] = useState('')
  const [guideOpen, setGuideOpen] = useState(false)
  const active = useRef(false)
  const inFlight = useRef(false)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const ready = !!caps?.authorized && !!selected?.configured
  const stateLabel = !caps ? '正在读取接入状态' : !caps.authorized ? '当前用户未绑定' : !selected?.configured ? '账户未配置' : pending ? '正在验证连接' : connectionError ? '连接验证失败' : result ? '连接验证成功' : '已配置，待验证'
  const prefix = venue === 'binance' ? 'ATLAS_BINANCE' : 'ATLAS_OKX'
  const simulated = accounts.filter((account) => account.environment === 'platform_sim')

  async function verify() {
    if (!ready || inFlight.current) return
    inFlight.current = true; setPending(true); setConnectionError(''); setResult(null)
    try {
      const response = await request<{ balances: { asset: string; available: string; locked: string }[] }>(`/trading/${venue}/account`)
      if (active.current) setResult({ balances: response.balances, checkedAt: new Date() })
    } catch (cause) {
      if (active.current) setConnectionError(cause instanceof Error ? cause.message : '无法读取账户余额，请检查配置后重试。')
    } finally {
      inFlight.current = false
      if (active.current) setPending(false)
    }
  }

  async function refreshConfiguration() {
    if (inFlight.current) return
    inFlight.current = true; setPending(true); setConnectionError(''); setResult(null)
    try { await onRefresh() }
    catch (cause) { if (active.current) setConnectionError(cause instanceof Error ? cause.message : '读取配置失败，请重试。') }
    finally { inFlight.current = false; if (active.current) setPending(false) }
  }

  return <>
    <div className="trade-connection-summary">
      <div className="trade-connection-title"><Link2 size={20} aria-hidden="true" /><strong>{venue === 'binance' ? 'Binance' : 'OKX'} 现货账户</strong><span className={selected?.mode === 'live' ? 'trade-mode trade-mode-live' : 'trade-mode'}>{!selected ? '环境待读取' : selected.mode === 'live' ? '实盘' : '测试环境'}</span></div>
      {selected?.mode === 'live' && <p className="trade-live">实盘环境 · 下单将使用真实资金</p>}
      <p className={`trade-connection-state${result ? ' is-connected' : ''}`} role="status">{pending ? <LoaderCircle size={18} className="trade-connection-spinner" aria-hidden="true" /> : result ? <CheckCircle2 size={18} aria-hidden="true" /> : <CircleHelp size={18} aria-hidden="true" />}{stateLabel}</p>
      <p className="trade-connection-hint">{!caps ? '读取完成后将显示配置状态与下一步。' : !caps.authorized ? '接入模拟账户即可开始；实盘账户需在服务端绑定当前用户。' : !selected?.configured ? '可接入个人模拟账户，或按指引配置服务端账户。' : result ? '本次余额查询成功；刷新页面或切换账户后需重新验证。' : '凭据已配置。查询余额成功后，才能确认账户实际连通。'}</p>
      <div className="trade-connection-actions"><button type="button" disabled={locked} onClick={onConnect}>接入模拟账户</button>
        {ready ? <button className="trade-primary" type="button" disabled={pending} onClick={() => void verify()}>{pending ? '正在验证…' : connectionError ? '重试连接' : result ? '刷新余额' : '验证连接'}</button> : <button className="trade-primary" type="button" aria-expanded={guideOpen} aria-controls="trade-connection-guide" onClick={() => setGuideOpen(!guideOpen)}>{guideOpen ? '收起接入指引' : '查看接入指引'}</button>}
        {ready && <button className="trade-guide-button" type="button" aria-expanded={guideOpen} aria-controls="trade-connection-guide" onClick={() => setGuideOpen(!guideOpen)}>{guideOpen ? '收起指引' : '接入指引'}</button>}
      </div>
      <p className="trade-permission">交易权限：{!caps ? '待读取' : selected?.can_trade ? '已启用 · 人工下单需逐笔确认' : '提交未启用'}{ready && !selected?.can_trade && ' · 可验证连接'}</p>
      {connectionError && <div className="trade-connection-error" role="alert"><strong>未能完成连接检查</strong><p>{connectionError}</p><p>检查服务端配置与网络后重试。</p></div>}
    </div>
    {guideOpen && <section className="trade-connection-guide" id="trade-connection-guide" aria-label="接入指引">
      <h3>在服务端完成接入</h3>
      <ol><li><strong>绑定当前平台用户</strong><p>将 <code>ATLAS_TRADING_OWNER_ID</code> 设置为当前用户 ID：</p>{caps?.user_id ? <code className="trade-user-id">{caps.user_id}</code> : <p>尚未读取到用户 ID，请重新检测配置。</p>}</li>
        <li><strong>配置 {names[venue]} 凭据</strong><p>在后端环境中设置 <code>{prefix}_API_KEY</code>、<code>{prefix}_API_SECRET</code>{venue === 'okx' && <> 和 <code>ATLAS_OKX_PASSPHRASE</code></>}。<code>{prefix}_MODE</code> 默认 <code>demo</code>（测试），实盘为 <code>live</code>，凭据必须与环境匹配。</p><p>实盘密钥仅通过服务端环境配置，不要填入页面、聊天或代码仓库；不需要提现权限。模拟密钥可通过“接入模拟账户”保存。</p></li>
        <li><strong>重启后端并验证</strong><p>保存配置、重启后端后，点击下方重新检测，再验证连接。查询余额不需要开启交易提交。</p></li></ol>
      <button type="button" disabled={pending || locked} onClick={() => void refreshConfiguration()}><RefreshCw size={15} aria-hidden="true" />{pending ? '正在检测…' : '重新检测配置'}</button>
      <details className="trade-enable-help"><summary>需要人工下单？</summary><p><code>ATLAS_TRADING_ENABLED=1</code> 允许提交；实盘还需 <code>ATLAS_TRADING_LIVE_ENABLED=1</code>。此处为服务端账户开关；人工下单仍需预览和确认。个人模拟账户验证保存后可用于测试交易，自动执行需在新建运行时单独启用。</p></details>
    </section>}
    {result && <section className="trade-connection-balances" aria-label="账户余额"><div className="trade-balance-heading"><h3>账户余额</h3><time dateTime={result.checkedAt.toISOString()}>查询于 {result.checkedAt.toLocaleTimeString('zh-CN', { hour12: false })}</time></div>{result.balances.length ? <div className="trade-table" tabIndex={0} role="region" aria-label="余额明细"><table><thead><tr><th>资产</th><th>可用</th><th>冻结</th></tr></thead><tbody>{result.balances.map((row) => <tr key={row.asset}><td>{row.asset}</td><td>{balanceAmount(row.available)}</td><td>{balanceAmount(row.locked)}</td></tr>)}</tbody></table></div> : <p>暂无余额记录。连接已验证成功。</p>}</section>}
    {simulated.length > 0 && <details className="trade-secondary-accounts"><summary>平台模拟账户 · {simulated.length}</summary>{simulated.map((account) => <div className="trade-account-row" key={account.id}><Wallet size={16} aria-hidden="true" /><span><strong>{account.name}</strong><small>{marketNames[account.market]} · {account.currency}</small></span><em>平台模拟</em></div>)}</details>}
    <details className="trade-other-markets"><summary>其他市场接入</summary><p><strong>美股</strong> · 券商接口待接入，平台模拟可用。</p><p><strong>A 股</strong> · <strong>miniQMT · 等待客户端接入</strong>，平台模拟可用。</p></details>
  </>
}

export default function TradingWorkspace() {
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
  const appliedDeepLink = useRef(window.location.hash)
  const loadSequence = useRef(0)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [venue, setVenue] = useState<Venue>('binance')
  const [connectionRevision, setConnectionRevision] = useState(0)
  const [view, setView] = useState<'overview' | 'strategies' | 'orders'>(query.has('order') ? 'orders' : query.has('run') || query.has('release') ? 'strategies' : 'overview')
  const [composer, setComposer] = useState<'run' | 'order' | 'connect' | null>(query.has('release') ? 'run' : null)
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('buy')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [preview, setPreview] = useState<Trade | null>(null)
  const [strategyLink, setStrategyLink] = useState<{ runId: string; signalId: string } | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [orders, setOrders] = useState<Trade[]>([])
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
  const [demoAuto, setDemoAuto] = useState(false)
  const [runInterval, setRunInterval] = useState<Interval>('1d')
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
    const sequence = ++loadSequence.current
    const currentHash = window.location.hash
    const deepLinkChanged = appliedDeepLink.current !== currentHash
    const currentQuery = new URLSearchParams(currentHash.split('?')[1] ?? '')
    const linkedRunId = currentQuery.get('run') ?? ''
    const linkedReleaseId = currentQuery.get('release') ?? ''
    const next = await request<Capabilities>('/trading/capabilities')
    const [nextRuns, nextAccounts, nextReleases, nextSubscriptions, linkedRun] = await Promise.all([
      request<StrategyRun[]>(`/trading/runs?market=${marketFilter}&environment=${environmentFilter}`),
      request<RuntimeAccount[]>('/trading/accounts'), request<StrategyRelease[]>('/strategy-releases'),
      request<StrategySubscription[]>('/strategy-subscriptions'),
      linkedRunId ? request<StrategyRun>(`/trading/runs/${linkedRunId}`).catch(() => null) : Promise.resolve(null),
    ])
    if (sequence !== loadSequence.current || currentHash !== window.location.hash) return
    setCaps(next)
    const listedRuns = Array.isArray(nextRuns) ? nextRuns : []
    const listedReleases = Array.isArray(nextReleases) ? nextReleases : []
    setRuns(linkedRun && !listedRuns.some((item) => item.id === linkedRun.id) ? [linkedRun, ...listedRuns] : listedRuns)
    setAccounts(Array.isArray(nextAccounts) ? nextAccounts : [])
    setReleases(listedReleases)
    setSubscriptions(Array.isArray(nextSubscriptions) ? nextSubscriptions : [])
    if (linkedReleaseId && listedReleases.some((item) => item.id === linkedReleaseId)) setRunRelease((current) => deepLinkChanged ? linkedReleaseId : current || linkedReleaseId)
    else if (listedReleases[0]) setRunRelease((current) => current || listedReleases[0].id)
    setFocusedRun(linkedRunId)
    if (deepLinkChanged) {
      appliedDeepLink.current = currentHash
      if (linkedRunId || linkedReleaseId) setView('strategies')
      else if (currentQuery.has('order')) setView('orders')
      if (linkedReleaseId) setComposer((current) => current === 'order' ? current : 'run')
    }
    if (linkedRun) setRunDetails((current) => ({ ...current, [linkedRun.id]: linkedRun }))
    if (next.authorized) {
      const nextOrders = await request<Trade[]>('/trading/orders')
      if (sequence !== loadSequence.current || currentHash !== window.location.hash) return
      setOrders(nextOrders)
    } else setOrders([])
    setLoaded(true)
  }, [marketFilter, environmentFilter, setAccounts, setCaps, setFocusedRun, setLoaded, setOrders, setReleases, setRunRelease, setRuns, setSubscriptions])
  useEffect(() => {
    const timer = window.setTimeout(() => void load().catch((cause: Error) => setError(cause.message)), 0)
    const refresh = () => { if (document.visibilityState === 'visible') void load().catch(() => undefined) }
    window.addEventListener(RUNTIME_CHANGED_EVENT, refresh); document.addEventListener('visibilitychange', refresh); window.addEventListener('hashchange', refresh)
    const polling = window.setInterval(() => { if (window.location.hash.startsWith('#/trading')) refresh() }, 5000)
    document.title = '策略交易 · Atlas'
    return () => { window.clearTimeout(timer); window.clearInterval(polling); window.removeEventListener(RUNTIME_CHANGED_EVENT, refresh); document.removeEventListener('visibilitychange', refresh); window.removeEventListener('hashchange', refresh) }
  }, [load])
  useEffect(() => {
    if (view !== 'strategies' || !focusedRun || !runs.some((run) => run.id === focusedRun)) return
    const timer = window.setTimeout(() => document.getElementById(focusedRun)?.scrollIntoView({ block: 'center' }), 0)
    setExpandedRuns((current) => current[focusedRun] ? current : { ...current, [focusedRun]: true })
    if (!runDetails[focusedRun] && !detailLoading[focusedRun] && !detailErrors[focusedRun]) void loadRunDetail(focusedRun)
    return () => window.clearTimeout(timer)
  }, [detailErrors, detailLoading, focusedRun, loadRunDetail, runDetails, runs, view])
  useEffect(() => {
    const identifier = new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('order')
    if (view === 'orders' && identifier && orders.some((order) => order.id === identifier)) {
      document.getElementById(`order-${identifier}`)?.scrollIntoView({ block: 'center' })
    }
  }, [orders, view])

  async function action(work: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError('')
    try { await work() } catch (cause) { setError(cause instanceof Error ? cause.message : '请求失败') }
    finally { setBusy(false) }
  }
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible' || !window.location.hash.startsWith('#/trading')) return
      for (const [id, expanded] of Object.entries(expandedRuns)) if (expanded) void loadRunDetail(id)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [expandedRuns, loadRunDetail])
  function invalidate() { setPreview(null); setConfirmation('') }
  function editOrder() { invalidate(); setStrategyLink(null) }
  function prepareRecommendation(run: StrategyRun) {
    if (!run.recommendation) return
    setComposer('order')
    setVenue(run.account_name?.toLowerCase().includes('okx') ? 'okx' : 'binance')
    setSymbol(run.symbol); setSide(run.recommendation.side); setQuantity(run.recommendation.quantity)
    setPrice(run.recommendation.reference_price); setStrategyLink({ runId: run.id, signalId: run.recommendation.id })
    setPreview(null); setConfirmation(''); setNotice('已带入策略建议。预览时会重新核对绑定账户、预算和交易所余额。')

  }
  const allowedReleases = releases.filter((item) => item.owned || subscriptions.some((sub) => sub.release_id === item.id && sub.status === 'active'))
  const selectedExecutionMode = allowedReleases.find(item => item.id === runRelease)?.execution_mode
  const isPrivateRunner = selectedExecutionMode === 'private_runner'
  const isQuoteProbe = selectedExecutionMode === 'quote_probe' || isPrivateRunner
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

  const activeRuns = runs.filter((run) => run.status === 'active').length
  const troubledRuns = runs.filter((run) => run.status === 'error').length
  const uncertainOrders = orders.filter((order) => ['unknown', 'submitting', 'cancel_unknown', 'cancel_submitting'].includes(order.state))
  const selectedName = venue === 'binance' ? '币安' : '欧易'
  return <main className="trading-workspace trading-console">
    <header className="trade-heading">
      <div><h1>策略交易</h1><p>连接账户，运行策略，追踪每一笔成交。</p></div>
      <div className="trade-heading-actions"><button className="trade-refresh" disabled={busy} onClick={() => void action(load)} aria-label="刷新全部数据"><RefreshCw size={17} /></button><button onClick={() => setComposer('order')}><ArrowUpRight size={17} />人工下单</button><button className="trade-primary" onClick={() => setComposer('run')}><Plus size={17} />新建运行</button></div>
    </header>
    {error && <div className="trade-page-alert trade-error" role="alert">{error}</div>}{notice && <div className={notice.includes('结果未确认') ? 'trade-uncertain' : 'trade-notice'} role="status">{notice}</div>}
    {uncertainOrders.length > 0 && <div className="trade-uncertain" role="alert"><ShieldCheck size={19} /><span><strong>{uncertainOrders.length} 笔订单结果待核实</strong>请先查询状态，不要重复下单。</span><button onClick={() => setView('orders')}>查看委托<ArrowRight size={16} /></button></div>}
    <div className="trade-workbench">
      <aside className="trade-sidebar">
        <nav aria-label="交易账户导航">{([{ id: 'overview', label: '账户概览', Icon: Wallet }, { id: 'strategies', label: '策略运行', Icon: Layers3 }, { id: 'orders', label: '委托记录', Icon: ListOrdered }] as const).map(({ id, label, Icon }) => <button key={id} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}><Icon size={18} /><span>{label}</span>{id === 'orders' && uncertainOrders.length > 0 && <small>{uncertainOrders.length}</small>}</button>)}</nav>
        <div className="trade-sidebar-accounts"><h2>交易所账户</h2><div className="trade-venue-switch" role="group" aria-label="选择交易所">{(['binance', 'okx'] as Venue[]).map((item) => {
          const capability = caps?.venues.find((candidate) => candidate.venue === item)
          return <button type="button" key={item} aria-label={names[item]} aria-pressed={item === venue} disabled={busy || !!preview} onClick={() => { if (item !== venue) { setVenue(item); editOrder() } setView('overview') }}><span className={`trade-exchange-mark is-${item}`} aria-hidden="true">{item === 'binance' ? <Layers3 size={19} /> : <Square size={18} />}</span><span><strong>{item === 'binance' ? 'Binance' : 'OKX'}</strong><small>{!capability ? '读取中' : capability.mode === 'live' ? '实盘账户' : '测试账户'}</small></span>{item === venue && <span className="trade-selection-dot" aria-hidden="true" />}</button>
        })}</div></div>
        <div className="trade-sidebar-note"><ShieldCheck size={20} /><p>你掌握交易决定权<small>策略信号不会自动实盘下单</small></p></div>
        <a className="trade-ledger-link" href="#/journal/trading"><BookOpen size={17} />自动交易账本<ArrowUpRight size={15} /></a>
      </aside>
      <div className="trade-main-content">
        <section hidden={view !== 'overview'} aria-label="账户概览">
          <div className="trade-overview-heading"><div><span className="trade-context-label">{selectedName} · 现货账户</span><h2>{!caps ? '正在读取账户' : !caps.authorized || !selected?.configured ? '从连接账户开始' : '账户与资金'}</h2><p>账户资产与策略收益分开记录，测试环境与实盘始终清晰。</p></div><span className={`trade-overview-symbol is-${venue}`} aria-hidden="true"><Wallet size={48} strokeWidth={1.15} /></span></div>
          <div className="trade-overview-grid">
            <section className="trade-account" aria-label="账户与连接"><AccountConnection key={`${connectionRevision}:${venue}:${caps?.authorized}:${selected?.configured}:${selected?.mode}`} caps={caps} venue={venue} accounts={accounts} locked={busy || !!preview} onRefresh={load} onConnect={() => setComposer('connect')} /></section>
            <aside className="trade-activity-summary"><h3>运行概况</h3><p className="trade-summary-scope">{marketFilter ? marketNames[marketFilter] : '全部市场'} · {environmentFilter ? environmentNames[environmentFilter] : '全部环境'}</p>{(marketFilter || environmentFilter) && <button className="trade-filter-reset" onClick={() => { setMarketFilter(''); setEnvironmentFilter('') }}>重置为全部范围</button>}<div className="trade-activity-number"><strong>{activeRuns}</strong><span>个策略正在运行</span></div><div className="trade-activity-line"><span>需要关注</span><strong className={troubledRuns ? 'negative' : ''}>{troubledRuns} 个</strong></div><div className="trade-activity-line"><span>待核实委托（全部）</span><strong className={uncertainOrders.length ? 'negative' : ''}>{uncertainOrders.length} 笔</strong></div><button onClick={() => setView('strategies')}>查看运行策略<ArrowRight size={16} /></button><div className="trade-summary-footnote"><Activity size={16} /><p>平台模拟可持续运行<small>关闭页面后，服务端仍会检查行情。</small></p></div></aside>
          </div>
          <section className="trade-assets"><header className="trade-section-heading"><div><h2>策略资产</h2><p>{marketFilter ? marketNames[marketFilter] : '全部市场'} · {environmentFilter ? environmentNames[environmentFilter] : '全部环境'} · 仅计策略实例，按原币展示。</p></div><button className="trade-text-action" onClick={() => setView('strategies')}>管理策略<ArrowRight size={16} /></button></header>{Object.entries(totals).length ? <div className="trade-asset-lines">{Object.entries(totals).map(([key, item]) => <div key={key}><span className="trade-currency">{item.currency}</span><span>{environmentNames[item.environment]}<small>策略实例净值</small></span><strong>{money(item.equity, item.currency)}<small className={item.profit >= 0 ? 'positive' : 'negative'}>{item.valuationComplete ? `${item.profit >= 0 ? '+' : ''}${money(item.profit, item.currency)} 净收益` : '费用覆盖不完整 · 收益不可完整计算'}</small></strong></div>)}</div> : <div className="trade-assets-empty"><Activity size={24} strokeWidth={1.4} /><div><strong>还没有策略资产</strong><p>启动一个模拟策略，让资金、持仓与成交在这里形成记录。</p></div><button onClick={() => setComposer('run')}>新建运行<ArrowRight size={16} /></button></div>}</section>
        </section>
        <section hidden={view !== 'strategies'} className="trade-strategies" aria-label="策略运行">
          <header className="trade-section-heading"><div><h2>策略运行</h2><p>观察运行中的策略，展开查看净值、持仓和每笔成交。</p></div><a href="#quantjudge"><BookOpen size={16} />发现策略</a></header>
          <div className="trade-controlbar"><div aria-label="市场筛选">{(['', 'CRYPTO', 'US', 'CN'] as const).map((item) => <button key={item || 'all'} aria-pressed={marketFilter === item} className={marketFilter === item ? 'is-active' : ''} onClick={() => setMarketFilter(item)}>{item ? marketNames[item] : '全部市场'}</button>)}</div><label>环境<select value={environmentFilter} onChange={(event) => setEnvironmentFilter(event.target.value as '' | RuntimeEnvironment)}><option value="">全部环境</option><option value="platform_sim">平台模拟</option><option value="exchange_test">交易所测试</option><option value="live">实盘</option></select></label></div>
          <div className="trade-run-grid">{runs.map((run) => {
            const expanded = !!expandedRuns[run.id]; const detail = runDetails[run.id]
            return <article key={run.id} id={run.id} className={expanded ? 'is-expanded' : ''}>
              <div className="trade-run-line"><span className="trade-run-symbol" aria-hidden="true">{run.symbol.slice(0, 2)}</span><div className="trade-run-identity"><h3>{run.strategy_name}{run.demo_auto === '1' && <small>模拟自动执行</small>}<small>v{run.strategy_version}</small></h3><p>{run.symbol} <span>·</span> {run.execution_mode === 'private_runner' ? '开发者本地执行' : run.execution_mode === 'quote_probe' ? '10秒报价联调' : intervalNames[run.interval]} <span>·</span> {environmentNames[run.environment]}</p></div><span className={`trade-run-status is-${run.status}`}>{run.status === 'active' ? '运行中' : run.status === 'paused' ? '已暂停' : run.status === 'stopped' ? '已停止' : run.status === 'error' ? '待处理' : '待启动'}</span><div className="trade-run-valuation"><small>策略净值</small><strong>{money(run.equity, runCurrency(run))}</strong></div><div className="trade-run-return"><small>收益率</small><strong className={run.valuation_complete === false ? '' : Number(run.return_rate) >= 0 ? 'positive' : 'negative'}>{run.valuation_complete === false ? '不可完整计算' : pct(run.return_rate)}</strong></div><button className="trade-detail-toggle" aria-expanded={expanded} aria-controls={`detail-${run.id}`} onClick={() => { setExpandedRuns((current) => ({ ...current, [run.id]: !expanded })); if (!expanded) void loadRunDetail(run.id) }}>{expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}<span>{expanded ? '收起详情' : '运行详情'}</span></button></div>
              <div className="trade-run-signal"><Activity size={14} /><span>{run.latest_signal ?? '等待首个收盘信号'}</span>{run.recommendation && <button onClick={() => prepareRecommendation(run)} disabled={busy || !!preview}>预览策略建议<ArrowUpRight size={14} /></button>}</div>
              {run.latest_error && <p className="trade-run-alert">{run.latest_error}</p>}
              {expanded && <><div className="trade-run-toolbar"><span>暂停或停止不会自动清仓</span>{run.status === 'active' && <button disabled={busy} onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/pause`, { method: 'POST' }); await load(); await loadRunDetail(run.id) })}><Pause size={14} />暂停</button>}{['paused', 'error'].includes(run.status) && <button disabled={busy} onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/resume`, { method: 'POST' }); await load(); await loadRunDetail(run.id) })}><Play size={14} />恢复</button>}{run.status !== 'stopped' && <button disabled={busy} onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/stop`, { method: 'POST' }); await load(); await loadRunDetail(run.id) })}><Square size={14} />停止</button>}<button disabled={busy || run.status !== 'active'} onClick={() => void action(async () => { await request(`/trading/runs/${run.id}/tick`, { method: 'POST' }); await load(); await loadRunDetail(run.id) })}><RefreshCw size={14} />立即检查</button><a href={`#/journal/trading?run=${run.id}`}>成交与账本<ArrowUpRight size={14} /></a></div>{detailLoading[run.id] ? <p className="trade-detail-state" role="status">正在读取净值、持仓和交易记录…</p> : detailErrors[run.id] ? <div className="trade-detail-state trade-run-alert" role="alert"><p>{detailErrors[run.id]}</p><button onClick={() => void loadRunDetail(run.id)}>重新读取</button></div> : detail ? <RunDetail run={detail} /> : null}</>}
            </article>
          })}{loaded && !runs.length && <div className="trade-empty-state"><Layers3 size={36} strokeWidth={1.25} /><h3>让策略开始积累记录</h3><p>选择一个已发布或订阅的版本，分配模拟资金，即可开始追踪表现。</p><button className="trade-primary" onClick={() => setComposer('run')}><Plus size={16} />创建运行实例</button><a href="#quantjudge">先去发现策略<ArrowUpRight size={15} /></a></div>}</div>
        </section>
        <div hidden={view !== 'orders'}>    <section className="trade-orders"><header className="trade-section-heading"><div><h2>委托记录</h2><p>平台发出的最近 100 笔订单，受理状态与成交回执分别追踪。</p></div><span className="trade-count">{orders.length} 笔</span></header>{orders.length > 0 && <div className="trade-table"><table><thead><tr><th>交易对／环境</th><th>委托</th><th>状态／成交数量</th><th>操作</th></tr></thead><tbody>{orders.map((row) => <tr key={row.id} id={`order-${row.id}`}><td>{row.order.symbol}<small>{names[row.order.venue]} · {row.mode === 'live' ? '实盘' : '模拟'}</small>{row.order.strategy_run_id && <small className="trade-order-attribution">策略 · {runs.find((run) => run.id === row.order.strategy_run_id)?.strategy_name ?? row.order.strategy_run_id}</small>}</td><td><span className={row.order.side === 'buy' ? 'trade-side-buy' : 'trade-side-sell'}>{row.order.side === 'buy' ? '买入' : '卖出'}</span> {row.order.quantity}<small>@ {row.order.price} USDT</small></td><td><span className="trade-order-state">{states[row.state] ?? row.state}</span><small>{row.result.exchange_status ?? row.result.message ?? '尚未发送'}{row.result.filled_quantity && ` · 已成交 ${row.result.filled_quantity}`}</small>{row.accounting_status === 'cost_incomplete' && <small>成交成本待补全 · 收益不可计算</small>}{row.accounting_status === 'pending_sync' && <small>成交明细待同步</small>}</td><td>{!['preview', 'preview_expired', 'rejected'].includes(row.state) && <div className="trade-actions"><button disabled={busy} onClick={() => void action(async () => { await post(`/orders/${row.id}/refresh`); await load() })}>查询状态</button><button disabled={busy || row.state === 'submitting' || ['FILLED', 'CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'].includes(row.result.exchange_status ?? '')} onClick={() => { if (window.confirm(`确认撤销 ${row.order.symbol} 的订单？`)) void action(async () => { await post(`/orders/${row.id}/cancel`, { confirmation: '确认撤单' }); await load() }) }}>撤单</button></div>}</td></tr>)}</tbody></table></div>}{loaded && !orders.length && <div className="trade-empty-state"><ListOrdered size={32} strokeWidth={1.3} /><h3>每一笔委托，都有迹可循</h3><p>还没有交易所订单。提交后可在这里查询状态、成交数量与账本记录。</p><button onClick={() => setComposer('order')}>创建第一笔订单<ArrowRight size={16} /></button></div>}</section></div>
      </div>
    </div>
    <footer className="trade-workspace-footer"><span><ShieldCheck size={14} />资金在交易所，决策在你手中</span><span>模拟、测试与实盘独立标识</span></footer>
    <Dialog.Root open={composer !== null} onOpenChange={(open) => { if (!open && !busy) { setComposer(null) } }}>
      <Dialog.Portal><Dialog.Backdrop className="trade-dialog-backdrop" /><Dialog.Popup className="trading-workspace trade-modal" aria-describedby="trade-composer-description">
        <header className="trade-modal-heading"><div><Dialog.Title>{composer === 'connect' ? '接入模拟账户' : composer === 'run' ? '新建策略运行' : '人工下单'}</Dialog.Title><Dialog.Description id="trade-composer-description">{composer === 'connect' ? '连接测试资金账户，验证过程不会下单。' : composer === 'run' ? '选定策略与资金，开始持续记录。' : '核对账户与参数，再逐笔确认提交。'}</Dialog.Description></div><Dialog.Close disabled={busy} aria-label="关闭操作面板"><X size={20} /></Dialog.Close></header>
        {composer === 'connect' ? <DemoAccountSetup initialVenue={venue} defaultOpen onBusyChange={setBusy} onConnected={async () => { setConnectionRevision((value) => value + 1); await load() }} /> : composer === 'run' ? <><div className="trade-run-form-note"><Layers3 size={18} /><p>每个实例只负责一个标的；平台模拟不使用真实资金。</p></div>      {!allowedReleases.length && <p className="trade-composer-empty">还没有可运行策略。<a href="#quantjudge" onClick={() => setComposer(null)}>前往策略库发布或订阅</a>一个版本，再回来创建运行。</p>}
      <form className="trade-run-form" onSubmit={(event) => { event.preventDefault(); void action(async () => {
        const release = allowedReleases.find((item) => item.id === runRelease); if (!release) return
        const subscription = subscriptions.find((item) => item.release_id === release.id && item.status === 'active')
        const account = availableRunAccounts.find((item) => item.id === runAccount) ?? availableRunAccounts[0]
        const created = await request<StrategyRun>('/trading/runs', { method: 'POST', body: JSON.stringify({ release_id: release.id, subscription_id: subscription?.id, account_id: isQuoteProbe ? undefined : account?.id, market: isQuoteProbe ? 'CRYPTO' : runMarket, environment: isQuoteProbe ? 'platform_sim' : runEnvironment, symbol: isQuoteProbe ? 'BTC-USDT' : runSymbol, interval: runInterval, initial_cash: isQuoteProbe ? '200' : runCash, demo_auto: !isQuoteProbe && runEnvironment === 'exchange_test' && demoAuto, commission_rate: commissionRate, slippage_rate: slippageRate, max_position: maxPosition, max_participation: maxParticipation, stop_loss: stopLoss, take_profit: takeProfit }) })
        await request(`/trading/runs/${created.id}/start`, { method: 'POST' }); setNotice(isPrivateRunner ? '策略实例已启动，等待开发者本地签名信号。' : '策略实例已启动，首次运行将建立行情基线。'); await load(); setComposer(null); setView('strategies')
      }) }}>
        {isPrivateRunner && <p className="trade-probe-note">私有策略在开发者本地执行。此实例使用BTC-USDT、200 USDT平台模拟资金；启动后等待签名信号，不会自行读取或执行源码。</p>}
        {isQuoteProbe && !isPrivateRunner && <p className="trade-probe-note">联调固定使用 BTC-USDT、200 USDT 平台模拟资金，每10秒交替买卖。12次执行后自动暂停。价格来自币安现货买卖报价，成交由平台模拟，包含手续费、滑点和盘口数量限制。</p>}
        <label>策略版本<select value={runRelease} onChange={(event) => setRunRelease(event.target.value)}>{!allowedReleases.length && <option value="">暂无可运行版本</option>}{allowedReleases.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label>
        {!isQuoteProbe && <><label>市场<select value={runMarket} onChange={(event) => { const market = event.target.value as RuntimeMarket; setRunMarket(market); setRunAccount(''); if (market !== 'CRYPTO') setRunEnvironment('platform_sim'); if (market === 'CN' && !['1d', '1wk'].includes(runInterval)) setRunInterval('1d'); setRunSymbol(market === 'CRYPTO' ? 'BTC-USD' : market === 'US' ? 'AAPL' : '600519.SS') }}>{(['CRYPTO', 'US', 'CN'] as RuntimeMarket[]).map((item) => <option key={item} value={item}>{marketNames[item]}</option>)}</select></label>
        <label>运行环境<select value={runEnvironment} onChange={(event) => { const environment = event.target.value as RuntimeEnvironment; setRunEnvironment(environment); setRunAccount(''); if (runMarket === 'CRYPTO') setRunSymbol(environment === 'platform_sim' ? 'BTC-USD' : 'BTC-USDT') }}><option value="platform_sim">平台模拟</option>{Array.from(new Set(accounts.filter((item) => item.market === runMarket && item.environment !== 'platform_sim').map((item) => item.environment))).map((item) => <option key={item} value={item}>{environmentNames[item]}</option>)}</select></label>
        <label>交易账户<select value={runAccount} onChange={(event) => setRunAccount(event.target.value)}>{!availableRunAccounts.length && <option value="">当前市场与环境暂无账户</option>}{availableRunAccounts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>标的<input required value={runSymbol} onChange={(event) => { setRunSymbol(event.target.value.toUpperCase()); setRunAccount('') }} /></label>
        <label>周期<select value={runInterval} onChange={(event) => setRunInterval(event.target.value as Interval)}>{(['15m', '1h', '4h', '1d', '1wk'] as Interval[]).filter((item) => runMarket !== 'CN' || ['1d', '1wk'].includes(item)).map((item) => <option key={item} value={item}>{intervalNames[item]}</option>)}</select></label>
        {runEnvironment === 'exchange_test' && <label className="trade-demo-auto"><input type="checkbox" checked={demoAuto} onChange={(event) => setDemoAuto(event.target.checked)} />自动执行模拟订单（仅测试资金）</label>}
        <label>分配资金<input required type="number" min="1" value={runCash} onChange={(event) => setRunCash(event.target.value)} /></label>
        </>}
        <button className="trade-primary" disabled={busy || !runRelease || (!isQuoteProbe && !availableRunAccounts.length)}><Play size={15} />{isPrivateRunner ? '启动并等待本地信号' : isQuoteProbe ? '启动10秒联调' : runEnvironment === 'platform_sim' ? '启动模拟' : runEnvironment === 'exchange_test' && demoAuto ? '启动测试交易' : '启动信号监控'}</button>
        <details className="trade-run-risk"><summary>风控与成交假设</summary><div><label>手续费率<input type="number" min="0" max="0.1" step="0.0001" value={commissionRate} onChange={(event) => setCommissionRate(event.target.value)} /></label><label>滑点率<input type="number" min="0" max="0.1" step="0.0001" value={slippageRate} onChange={(event) => setSlippageRate(event.target.value)} /></label><label>最大仓位<input type="number" min="0.01" max="1" step="0.01" value={maxPosition} onChange={(event) => setMaxPosition(event.target.value)} /></label><label>成交参与率<input type="number" min="0.0001" max="1" step="0.0001" value={maxParticipation} onChange={(event) => setMaxParticipation(event.target.value)} /></label><label>止损比例<input type="number" min="0" max="0.99" step="0.01" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} /></label><label>止盈比例<input type="number" min="0" max="10" step="0.01" value={takeProfit} onChange={(event) => setTakeProfit(event.target.value)} /></label></div></details>
      </form></> : <><div className="trade-order-venue" role="group" aria-label="下单交易所">{(['binance', 'okx'] as Venue[]).map((item) => <button key={item} disabled={busy || !!preview} aria-pressed={venue === item} onClick={() => { if (venue !== item) { setVenue(item); editOrder() } }}>{names[item]}</button>)}</div>      <section className="trade-ticket"><p className="trade-ticket-description">现货限价单 · 每笔订单由你确认</p><div className="trade-ticket-account"><strong>{names[venue]}</strong><span className={selected?.mode === 'live' ? 'trade-live' : 'trade-environment'}>{!selected ? '环境待读取' : selected.mode === 'live' ? '实盘 · 使用真实资金' : '测试环境 · 不使用真实资金'}</span></div><form onSubmit={(event) => { event.preventDefault(); void action(async () => { const next = await post<Trade>('/orders/preview', { venue, symbol, side, quantity, price, strategy_run_id: strategyLink?.runId, strategy_signal_id: strategyLink?.signalId }); setPreview(next); setConfirmation(''); await load() }) }}><fieldset disabled={busy || !!preview}>{strategyLink && <div className="trade-strategy-attribution" role="status"><span><Activity size={15} /><strong>策略建议</strong> · {linkedStrategy ? `${linkedStrategy.strategy_name} v${linkedStrategy.strategy_version}` : '已关联运行实例'}<small>{strategyLink.runId}</small></span><button type="button" onClick={() => setStrategyLink(null)}>解除关联</button></div>}<label>交易对<input required value={symbol} placeholder="例如 BTC-USDT" pattern="[A-Z0-9]{2,15}-USDT" onChange={(event) => { setSymbol(event.target.value.toUpperCase()); editOrder() }} /></label><label>方向<select value={side} onChange={(event) => { setSide(event.target.value); editOrder() }}><option value="buy">买入</option><option value="sell">卖出</option></select></label><div className="trade-fields"><label>数量（基础币）<input required inputMode="decimal" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidate() }} /></label><label>限价（USDT）<input required inputMode="decimal" value={price} onChange={(event) => { setPrice(event.target.value); invalidate() }} /></label></div><button className="trade-primary" disabled={!selected?.can_trade}>预览订单</button></fieldset></form>
      {preview && <section className="trade-review" aria-label="确认订单"><h3>{preview.mode === 'live' ? '核对实盘订单' : '核对模拟订单'}</h3>{preview.order.strategy_run_id && <p className="trade-review-attribution"><Activity size={15} />策略订单 · {runs.find((run) => run.id === preview.order.strategy_run_id)?.strategy_name ?? preview.order.strategy_run_id}</p>}<p>{names[preview.order.venue]} · {preview.order.symbol} · {preview.order.side === 'buy' ? '买入' : '卖出'}</p><p>数量 {preview.order.quantity} · 限价 {preview.order.price} USDT</p>{preview.result.checked_market_price && <p>交易所最新价 {preview.result.checked_market_price} USDT，限价和数量已通过交易所规则校验。</p>}<p>预览两分钟内有效。请输入“{phrase}”后提交。</p><label>确认文字<input value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></label><div className="trade-actions"><button disabled={busy} onClick={invalidate}>返回修改</button><button className="trade-primary" disabled={busy || confirmation !== phrase} onClick={() => void action(async () => { const result = await post<Trade>(`/orders/${preview.id}/confirm`, { confirmation }); setNotice(['unknown', 'submitting'].includes(result.state) ? `订单 ${result.id} 结果未确认。请查询状态，不要重复下单。` : '订单已提交，成交后请刷新核实。'); invalidate(); setStrategyLink(null); await load(); setComposer(null); setView('orders') })}>确认提交订单</button></div></section>}
      {!selected?.can_trade && <p className="trade-ticket-hint">{!caps ? '正在读取交易权限…' : !caps.authorized || !selected?.configured ? '请先在账户概览完成配置，再检查交易权限。' : '交易提交未启用；验证连接仍可查询余额。'}实盘策略信号始终需要人工确认。</p>}</section></>}
        {error && <p className="trade-error trade-modal-error" role="alert">{error}</p>}{busy && <p role="status">正在处理请求，请稍候…</p>}
      </Dialog.Popup></Dialog.Portal>
    </Dialog.Root>
  </main>
}
