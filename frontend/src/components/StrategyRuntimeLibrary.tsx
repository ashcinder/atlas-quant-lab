import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Boxes, Check, Play, RefreshCw, Rocket, X } from 'lucide-react'
import { request, RUNTIME_CHANGED_EVENT } from '../request'
import type { CustomStrategyRecord, RuntimeMarket, Strategy, StrategyRelease, StrategySubscription } from '../types'

type View = 'discover' | 'mine' | 'subscriptions'
const marketNames: Record<RuntimeMarket, string> = { CRYPTO: '加密货币', US: '美股', CN: 'A 股' }

export default function StrategyRuntimeLibrary() {
  const [view, setView] = useState<View>('discover')
  const [releases, setReleases] = useState<StrategyRelease[]>([])
  const [subscriptions, setSubscriptions] = useState<StrategySubscription[]>([])
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [custom, setCustom] = useState<CustomStrategyRecord[]>([])
  const [selected, setSelected] = useState('')
  const [markets, setMarkets] = useState<RuntimeMarket[]>(['CRYPTO', 'US', 'CN'])
  const [publishPublicly, setPublishPublicly] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const [nextReleases, nextSubscriptions, nextStrategies, nextCustom] = await Promise.all([
      request<StrategyRelease[]>('/strategy-releases'), request<StrategySubscription[]>('/strategy-subscriptions'),
      request<Strategy[]>('/strategies?mode=single'), request<CustomStrategyRecord[]>('/custom-strategies'),
    ])
    setReleases(nextReleases); setSubscriptions(nextSubscriptions); setStrategies(nextStrategies); setCustom(nextCustom)
    setSelected((current) => current || (nextCustom[0] ? `custom:${nextCustom[0].id}` : nextStrategies[0] ? `builtin:${nextStrategies[0].id}` : ''))
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => void load().catch((cause: Error) => setError(cause.message)), 0)
    const refresh = () => { if (document.visibilityState === 'visible') void load().catch((cause: Error) => setError(cause.message)) }
    window.addEventListener(RUNTIME_CHANGED_EVENT, refresh)
    window.addEventListener('hashchange', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener(RUNTIME_CHANGED_EVENT, refresh)
      window.removeEventListener('hashchange', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [load])
  const visible = useMemo(() => releases.filter((item) => view === 'mine' ? item.owned : view === 'discover' ? !item.owned : false), [releases, view])

  async function act(work: () => Promise<void>) {
    if (busy) return; setBusy(true); setError('')
    try { await work(); await load() } catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  async function publish() {
    const [kind, id] = selected.split(':')
    const customRecord = custom.find((item) => item.id === id)
    const builtin = strategies.find((item) => item.id === id)
    if (!customRecord && !builtin) return
    await request('/strategy-releases', { method: 'POST', body: JSON.stringify({
      published: publishPublicly, name: customRecord?.spec.name ?? builtin?.name, source_kind: kind, strategy_id: id,
      params: builtin ? Object.fromEntries(builtin.parameters.map((item) => [item.key, item.default])) : {},
      custom_strategy: customRecord?.spec ?? null, markets, description: customRecord?.spec.description ?? builtin?.description ?? '',
    }) })
    setView('mine')
  }
  return <section className="runtime-library">
    <header><div><em>EXECUTABLE LIBRARY</em><h2>策略从这里进入真实运行链路</h2><p>发布版本一经创建不可修改；订阅免费，并锁定到具体版本。</p></div><button disabled={busy} onClick={() => void act(load)}><RefreshCw size={15} />刷新</button></header>
    <nav aria-label="可运行策略"><button className={view === 'discover' ? 'is-active' : ''} onClick={() => setView('discover')}><Boxes size={15} />发现策略</button><button className={view === 'mine' ? 'is-active' : ''} onClick={() => setView('mine')}><Rocket size={15} />我的策略</button><button className={view === 'subscriptions' ? 'is-active' : ''} onClick={() => setView('subscriptions')}><Check size={15} />我的订阅</button></nav>
    {error && <p className="runtime-error" role="alert">{error}</p>}
    {view === 'mine' && <form className="runtime-publisher" onSubmit={(event) => { event.preventDefault(); void act(publish) }}>
      <label>选择可运行规则<select value={selected} onChange={(event) => setSelected(event.target.value)}>{custom.map((item) => <option key={item.id} value={`custom:${item.id}`}>{item.spec.name} · 自定义规则</option>)}{strategies.map((item) => <option key={item.id} value={`builtin:${item.id}`}>{item.name} · 内置</option>)}</select></label>
      <fieldset><legend>适用市场</legend>{(['CRYPTO', 'US', 'CN'] as RuntimeMarket[]).map((market) => <label key={market}><input type="checkbox" checked={markets.includes(market)} onChange={() => setMarkets((current) => current.includes(market) ? current.filter((item) => item !== market) : [...current, market])} />{marketNames[market]}</label>)}</fieldset>
      <label><input type="checkbox" checked={publishPublicly} onChange={(event) => setPublishPublicly(event.target.checked)} />同时公开为免费订阅</label>
      <button className="runtime-primary" disabled={busy || !selected || !markets.length}><Rocket size={15} />保存不可变版本</button>
    </form>}
    {view === 'subscriptions' ? <div className="runtime-release-grid">{subscriptions.map((item) => <article key={item.id}><span className="runtime-version">v{item.version}</span><h3>{item.name}</h3><p>{item.markets.map((market) => marketNames[market]).join(' · ')}</p><small>版本指纹 {item.content_hash.slice(0, 10)}…</small>{item.upgrade_release_id && <p>作者已发布 v{item.upgrade_version}，当前运行实例仍锁定 v{item.version}。</p>}<footer><em className={item.status === 'active' ? 'is-active' : ''}>{item.status === 'active' ? '运行授权有效' : '已取消'}</em>{item.status === 'active' && <><a href={`#/trading?release=${item.release_id}&subscription=${item.id}`}><Play size={14} />去运行</a>{item.upgrade_release_id && <button onClick={() => void act(() => request('/strategy-subscriptions', { method: 'POST', body: JSON.stringify({ release_id: item.upgrade_release_id }) }))}>订阅 v{item.upgrade_version}</button>}<button aria-label={`取消订阅 ${item.name}`} onClick={() => void act(() => request(`/strategy-subscriptions/${item.id}`, { method: 'DELETE' }))}><X size={14} /></button></>}</footer></article>)}{!subscriptions.length && <p className="runtime-empty">还没有可运行订阅。</p>}</div> : <div className="runtime-release-grid">{visible.map((item) => <article key={item.id}><span className="runtime-version">v{item.version}</span><h3>{item.name}</h3><p>{item.description || '规则策略版本'}</p><small>{item.markets.map((market) => marketNames[market]).join(' · ')} · {item.source_kind === 'custom' ? '自定义规则' : '内置规则'}</small><footer><code>{item.content_hash.slice(0, 10)}…</code>{item.owned ? <><a href={`#/trading?release=${item.id}`}><Play size={14} />运行</a>{!item.published && <button disabled={busy} onClick={() => void act(() => request(`/strategy-releases/${item.id}/publish`, { method: 'POST' }))}>公开免费订阅</button>}</> : <button className="runtime-primary" disabled={busy || subscriptions.some((sub) => sub.release_id === item.id && sub.status === 'active')} onClick={() => void act(() => request('/strategy-subscriptions', { method: 'POST', body: JSON.stringify({ release_id: item.id }) }))}>{subscriptions.some((sub) => sub.release_id === item.id && sub.status === 'active') ? <><Check size={14} />已订阅</> : <><ArrowUpRight size={14} />免费订阅</>}</button>}</footer></article>)}{!visible.length && <p className="runtime-empty">这里还没有策略版本。</p>}</div>}
  </section>
}
