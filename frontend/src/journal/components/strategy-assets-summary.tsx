import { useCallback, useEffect, useState } from 'react'
import { request, RUNTIME_CHANGED_EVENT } from '../../request'
import type { TradingLedgerSnapshot } from '../../types'

const environments = { platform_sim: '平台模拟', exchange_test: '交易所测试', live: '实盘' }
export default function StrategyAssetsSummary() {
  const [data, setData] = useState<TradingLedgerSnapshot | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try { setData(await request<TradingLedgerSnapshot>('/ledger/trades?limit=5')); setError('') }
    catch { setError('交易资产读取失败，请刷新重试。') }
  }, [])
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible' && window.location.hash.startsWith('#/journal/overview')) void load() }
    const initial = window.setTimeout(() => void load(), 0)
    const timer = window.setInterval(refresh, 30_000)
    window.addEventListener(RUNTIME_CHANGED_EVENT, refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { window.clearTimeout(initial); window.clearInterval(timer); window.removeEventListener(RUNTIME_CHANGED_EVENT, refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [load])
  const accountTotals = (data?.account_assets ?? []).reduce((totals, account) => {
    const group = totals[account.environment] ?? { known: 0, complete: true, count: 0 }
    group.known += Number(account.known_value_usdt ?? 0)
    group.complete &&= account.valuation_complete === true
    group.count += 1; totals[account.environment] = group
    return totals
  }, {} as Record<string, { known: number; complete: boolean; count: number }>)
  return <section className="linked-ledger" aria-label="策略资产概览">
    <div className="linked-ledger-toolbar"><div><strong>策略资产概览</strong><small>按环境与币种分别展示；测试资金不计入个人实盘资产，策略分配资金不重复加到账户余额。</small></div><a href="#/journal/trading">查看账户、持仓与成交</a></div>
    {error && <p role="alert">{error}<button onClick={() => void load()}>刷新</button></p>}
    <p>{data ? `${data.accounts.filter(a => a.environment !== 'platform_sim').length} 个交易所账户 · ${data.runs.length} 个策略实例` : '正在读取交易资产…'}</p>
    <div className="linked-ledger-totals">{Object.entries(accountTotals).map(([environment, value]) => <article key={environment}><span>{environments[environment as keyof typeof environments]} · {value.count} 个账户总资产</span><strong>{value.complete ? `${value.known.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} USDT` : '估值待补全'}</strong>{!value.complete && <small>已知部分 {value.known.toFixed(2)} USDT；请同步余额与价格</small>}<small>基于交易所余额；账户历史收益待完整现金流与成本</small></article>)}</div>
    {(data?.account_assets?.length ?? 0) > 0 && <div className="linked-ledger-table"><table><thead><tr><th>交易所账户</th><th>账户资产（USDT）</th><th>同环境资产占比</th><th>余额时间</th></tr></thead><tbody>{data?.account_assets?.map(account => {
      const group = accountTotals[account.environment]
      const ratio = group.complete && group.known > 0 ? Number(account.total_value_usdt) / group.known : null
      return <tr key={account.account_id}><td><a href={`#/journal/trading?account=${account.account_id}`}>{account.name}</a><small>{environments[account.environment]}</small></td><td>{account.total_value_usdt == null ? '待同步或估值不完整' : Number(account.total_value_usdt).toFixed(2)}</td><td>{ratio === null ? '—' : <><meter min="0" max="1" value={ratio} aria-label={`${account.name} 资产占比`} /> {(ratio * 100).toFixed(1)}%</>}</td><td>{account.synced_at ? new Date(account.synced_at).toLocaleString('zh-CN') : '尚未同步'}</td></tr>
    })}</tbody></table></div>}
    <div className="linked-ledger-totals">{data && Object.entries(data.totals).map(([key, value]) => {
      const capital = Number(value.equity) - Number(value.profit)
      return <article key={key}><span>{environments[value.environment]} · {value.currency} 策略资金</span><strong>{Number(value.equity).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</strong><small>{value.valuation_complete === false ? '费用或估值待补全，收益率不可计算' : `净收益 ${Number(value.profit).toFixed(2)} · 收益率 ${capital > 0 ? (Number(value.profit) / capital * 100).toFixed(2) + '%' : '—'}`}</small></article>
    })}</div>
    {data && !data.runs.length && <p>尚无策略资产。先在策略中心订阅，再到策略交易启动测试。</p>}
    {data && data.runs.length > 0 && <div className="linked-ledger-table"><table><thead><tr><th>策略／账户</th><th>环境</th><th>资产净值</th><th>收益率</th></tr></thead><tbody>{data.runs.map(run => <tr key={run.id}><td><a href={`#/trading?run=${run.id}`}>{run.strategy_name}</a><small>{run.account_name}</small></td><td>{environments[run.environment]}</td><td>{Number(run.equity).toFixed(2)} {run.currency}</td><td>{run.valuation_complete === false ? '待补全' : `${(Number(run.return_rate) * 100).toFixed(2)}%`}</td></tr>)}</tbody></table></div>}
  </section>
}
