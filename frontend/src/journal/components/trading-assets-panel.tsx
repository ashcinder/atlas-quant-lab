import { useCallback, useEffect, useState } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, RefreshCw, Wallet } from 'lucide-react'
import { request, RUNTIME_CHANGED_EVENT } from '../../request'
import type { RuntimeEnvironment, RuntimeMarket, TradingLedgerSnapshot } from '../../types'

const marketNames: Record<RuntimeMarket, string> = { CRYPTO: '加密货币', US: '美股', CN: 'A 股' }
const environmentNames: Record<RuntimeEnvironment, string> = { platform_sim: '平台模拟', exchange_test: '交易所测试', live: '实盘' }

export default function TradingAssetsPanel() {
  const deepLink = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
  const [market, setMarket] = useState('')
  const [environment, setEnvironment] = useState('')
  const [runId, setRunId] = useState(deepLink.get('run') ?? '')
  const [accountId, setAccountId] = useState(deepLink.get('account') ?? '')
  const [releaseId, setReleaseId] = useState(deepLink.get('release') ?? '')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<TradingLedgerSnapshot | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const params = new URLSearchParams({ market, environment, run_id: runId, account_id: accountId, release_id: releaseId, date_from: dateFrom, date_to: dateTo, limit: '50', offset: String(offset) })
      setData(await request<TradingLedgerSnapshot>(`/ledger/trades?${params}`))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '交易账本读取失败') }
    finally { setBusy(false) }
  }, [accountId, dateFrom, dateTo, environment, market, offset, releaseId, runId])
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    const refresh = () => { if (document.visibilityState === 'visible') void load() }
    window.addEventListener(RUNTIME_CHANGED_EVENT, refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener(RUNTIME_CHANGED_EVENT, refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [load])
  useEffect(() => {
    const refresh = () => {
      if (!window.location.hash.startsWith('#/journal/trading')) return
      const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
      setRunId(query.get('run') ?? ''); setAccountId(query.get('account') ?? '')
      setReleaseId(query.get('release') ?? ''); setOffset(0)
      void load()
    }
    window.addEventListener('hashchange', refresh)
    return () => window.removeEventListener('hashchange', refresh)
  }, [load])
  return <section className="linked-ledger">
    <div className="linked-ledger-toolbar"><div><strong>自动交易事实</strong><small>独立于手工账本保存，成交不会被账本编辑覆盖。</small></div><label>市场<select value={market} onChange={(event) => { setMarket(event.target.value); setOffset(0) }}><option value="">全部</option><option value="CRYPTO">加密货币</option><option value="US">美股</option><option value="CN">A 股</option></select></label><label>环境<select value={environment} onChange={(event) => { setEnvironment(event.target.value); setOffset(0) }}><option value="">全部</option><option value="platform_sim">平台模拟</option><option value="exchange_test">交易所测试</option><option value="live">实盘</option></select></label><label>账户<select value={accountId} onChange={(event) => { setAccountId(event.target.value); setOffset(0) }}><option value="">全部账户</option>{data?.accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label><label>策略<select value={releaseId} onChange={(event) => { setReleaseId(event.target.value); setRunId(''); setOffset(0) }}><option value="">全部策略</option>{Array.from(new Map(data?.runs.map((run) => [run.release_id, run]) ?? []).values()).map((run) => <option key={run.release_id} value={run.release_id}>{run.strategy_name} v{run.strategy_version}</option>)}</select></label><label>开始日期<input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setOffset(0) }} /></label><label>结束日期<input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setOffset(0) }} /></label><button disabled={busy} onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>
    {error && <p className="linked-ledger-error" role="alert">{error}</p>}
    <div className="linked-ledger-totals">{data && Object.entries(data.totals).map(([currency, value]) => <article key={currency}><span>{environmentNames[value.environment]} · {value.currency} 策略实例</span><strong>{Number(value.equity).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</strong><small className={Number(value.profit) >= 0 ? 'positive' : 'negative'}>{value.valuation_complete === false ? '净收益不可完整计算' : `${Number(value.profit) >= 0 ? '+' : ''}${Number(value.profit).toFixed(2)} 净收益`}</small></article>)}{data && !Object.keys(data.totals).length && <article><Wallet size={20} /><span>还没有自动交易资产</span></article>}</div>
    {data?.account_assets?.map((account) => <section className="linked-account-assets" key={account.account_id}>
      <header><div><h3>{account.name} · {environmentNames[account.environment]}</h3><small>{account.synced_at ? `最后同步 ${new Date(account.synced_at).toLocaleString('zh-CN')}` : '尚未同步账户余额'}</small></div><button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await request(`/trading/accounts/${account.account_id}/sync`, { method: 'POST' }); await load() } catch (cause) { setError(cause instanceof Error ? cause.message : '账户同步失败') } finally { setBusy(false) } }}>同步账户</button></header>
      <p role={account.status === 'reconciliation_required' ? 'alert' : undefined}>{account.message}</p>
      {account.environment === 'live' && <label>关联已有手工账户<select disabled={busy} value={account.manual_account_id ?? ''} onChange={async (event) => { const manualId = event.target.value; setBusy(true); setError(''); try { await request(`/trading/accounts/${account.account_id}/manual-link`, { method: 'PUT', body: JSON.stringify({ manual_account_id: manualId || null }) }); await load() } catch (cause) { setError(cause instanceof Error ? cause.message : '关联失败') } finally { setBusy(false) } }}><option value="">保持独立</option>{data.manual_accounts?.map((manual) => <option value={manual.id} key={manual.id}>{manual.name} · {manual.currency}</option>)}</select></label>}
      {account.manual_account_id && <p>此账户已在手工资产总览中计算；本页展示交易所余额，不再次叠加到手工总资产。不同原币金额不自动换算。</p>}
      <div className="linked-ledger-table"><table><thead><tr><th>原币资产</th><th>可用</th><th>冻结</th><th>策略归属</th><th>未归属</th><th>待核实缺口</th></tr></thead><tbody>{account.balances.map((balance) => <tr key={balance.asset}><td>{balance.asset}</td><td>{balance.available}</td><td>{balance.locked}</td><td>{balance.attributed_quantity}</td><td>{balance.unattributed_quantity}</td><td>{balance.reconciliation_shortfall}</td></tr>)}</tbody></table></div>
    </section>)}
    <div className="linked-run-list">{data?.runs.map((run) => <button className={runId === run.id ? 'is-active' : ''} key={run.id} onClick={() => setRunId(runId === run.id ? '' : run.id)}><Activity size={16} /><span><strong>{run.strategy_name} · {run.symbol}</strong><small>{marketNames[run.market]} · {environmentNames[run.environment]} · v{run.strategy_version}</small></span><em>{run.valuation_complete === false ? '不可完整计算' : `${(Number(run.return_rate) * 100).toFixed(2)}%`}</em></button>)}</div>
    {!!data?.positions?.length && <div className="linked-position-grid">{data.positions?.map((position) => <article key={position.run_id}><span>{position.symbol} · {position.strategy_name} v{position.strategy_version}</span><strong>{position.quantity} 股/币</strong><small>成本 {position.average_cost} · 市值 {position.market_value}</small><em className={Number(position.unrealized_pnl) >= 0 ? 'positive' : 'negative'}>未实现 {position.unrealized_pnl ?? '不可计算'}</em></article>)}</div>}
    <div className="linked-ledger-table"><table><thead><tr><th>成交时间</th><th>策略 / 标的</th><th>方向</th><th>数量 × 成交价</th><th>手续费</th><th>已实现收益</th></tr></thead><tbody>{data?.fills.map((fill) => <tr key={fill.id}><td>{new Date(fill.executed_at).toLocaleString('zh-CN')}</td><td>{fill.run_id ? <a href={`#/trading?run=${fill.run_id}`}>{fill.strategy_name} v{fill.strategy_version}</a> : <a href={`#/trading?account=${fill.account_id}&order=${fill.order_id}`}>人工订单</a>}<small>{fill.symbol} · {fill.market && marketNames[fill.market]}</small></td><td className={fill.side === 'buy' ? 'positive' : 'negative'}>{fill.side === 'buy' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}{fill.side === 'buy' ? '买入' : '卖出'}</td><td>{fill.quantity} × {fill.price}</td><td>{fill.fee} {fill.fee_currency}</td><td>{fill.realized_pnl === null ? '成本待补全' : `${fill.realized_pnl} ${fill.pnl_currency}`}</td></tr>)}</tbody></table>{data && !data.fills.length && <p>当前筛选范围内还没有成交。</p>}</div>
    {data && (offset > 0 || data.fills.length === data.limit) && <div className="linked-ledger-pages"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button><span>第 {Math.floor(offset / 50) + 1} 页</span><button disabled={busy || data.fills.length < data.limit} onClick={() => setOffset(offset + 50)}>下一页</button></div>}
  </section>
}
