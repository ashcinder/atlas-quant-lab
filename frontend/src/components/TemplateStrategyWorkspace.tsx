import { useRef, useState } from 'react'
import { api } from '../api'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'
import type { ExecutionPipeline } from './ExecutionPipelinePanel'

interface Preset { name: string; strategy_id: string; params: Record<string, unknown> }
export function TemplateStrategyWorkspace({ pipeline, storageKey, ...props }: ResearchWorkspaceProps & { pipeline: ExecutionPipeline; storageKey: string }) {
  const [id, setId] = useState(props.strategies[0]?.id ?? '')
  const [name, setName] = useState('我的模板策略')
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({})
  const [presets, setPresets] = useState<Preset[]>(() => {
    try { const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '[]'); return Array.isArray(saved) ? saved.filter(item => item && typeof item.name === 'string' && typeof item.strategy_id === 'string' && item.params && typeof item.params === 'object') : [] }
    catch { return [] }
  })
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  const strategy = props.strategies.find(item => item.id === id) ?? props.strategies[0]
  if (!strategy) return <p>等待策略模板加载…</p>
  const params = { ...Object.fromEntries(strategy.parameters.map(p => [p.key, p.default])), ...drafts[strategy.id] }
  const update = (key: string, value: unknown) => setDrafts(current => ({ ...current, [strategy.id]: { ...params, [key]: value } }))
  const save = () => {
    if (!name.trim()) { setNotice('请填写策略名称'); return }
    const next = [{ name: name.trim(), strategy_id: strategy.id, params }, ...presets.filter(item => item.name !== name.trim())]
    try { localStorage.setItem(storageKey, JSON.stringify(next)); setPresets(next); setNotice('参数副本已保存到当前浏览器，可从“我的参数副本”载入。') }
    catch { setNotice('浏览器存储不可用，请导出策略保存。') }
  }
  const exportStrategy = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schema: 'atlas.template-strategy/v1', name, strategy_id: strategy.id, params, execution_pipeline: pipeline }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `${strategy.id}.json`; link.click(); URL.revokeObjectURL(url)
  }
  const run = async () => {
    if (!props.asset || running.current) return
    running.current = true; setBusy(true); props.onLoading(true)
    try { props.onCustomResult(await api.runBacktest({ symbol: props.asset.symbol, asset_class: props.asset.asset_class, interval: props.interval, data_source: props.source, strategy_id: strategy.id, params, initial_capital: props.initialCapital, commission_rate: props.commission, slippage_rate: props.slippage, spread_rate: props.spread, max_position: props.maxPosition, max_participation_rate: props.maxParticipation, execution_pipeline: pipeline })) }
    catch (error) { props.onError(error instanceof Error ? error.message : '模板回测失败') }
    finally { running.current = false; setBusy(false); props.onLoading(false) }
  }
  return <form className="template-strategy-workspace" onSubmit={event => { event.preventDefault(); void run() }}>
    <header>
      <label>策略模板<select value={strategy.id} onChange={e => setId(e.target.value)}>{props.strategies.map(item => <option key={item.id} value={item.id}>{item.category} · {item.name}</option>)}</select></label>
      <label>策略名称<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
      <button type="button" onClick={save}>保存副本</button><button type="button" onClick={exportStrategy}>导出</button>
      <button type="submit" disabled={busy || !props.asset}>{busy ? '回测中…' : '运行模板回测'}</button>
    </header>
    {notice ? <p role="status">{notice}</p> : null}<p>{strategy.description}</p>
    <details><summary>我的参数副本（{presets.length}）</summary>{presets.map(item => <button type="button" key={item.name} onClick={() => { setId(item.strategy_id); setName(item.name); setDrafts(current => ({ ...current, [item.strategy_id]: item.params })); setNotice(`已载入“${item.name}”参数，流程设置沿用当前配置。`) }}>{item.name}</button>)}</details>
    <div className="template-parameter-grid">{strategy.parameters.map(p => <label key={p.key}><span>{p.label}</span>
      {p.kind === 'select' ? <select value={String(params[p.key])} onChange={e => update(p.key, e.target.value)}>{p.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
        : p.kind === 'boolean' ? <input type="checkbox" checked={Boolean(params[p.key])} onChange={e => update(p.key, e.target.checked)} />
        : <input required type="number" min={p.minimum ?? undefined} max={p.maximum ?? undefined} step={p.step ?? (p.kind === 'integer' ? 1 : 'any')} value={Number(params[p.key])} onChange={e => update(p.key, Number(e.target.value))} />}
      {p.help ? <small>{p.help}</small> : null}
    </label>)}</div>
    <button type="button" onClick={() => setDrafts(current => ({ ...current, [strategy.id]: {} }))}>恢复当前模板默认参数</button>
  </form>
}
