import { useEffect, useState } from 'react'
import { api } from '../api'
import type { LabBacktestSettings } from '../lab-strategy-types'
import { sourceForAssetClass } from '../storage'
import type { Asset } from '../types'

const intervals = { '15m': '15 分钟', '1h': '1 小时', '4h': '4 小时', '1d': '日线', '1wk': '周线' } as const
const intervalLabels: Partial<Record<LabBacktestSettings['interval'], string>> = intervals
const costs = [
  ['commission_rate', '手续费', 10], ['slippage_rate', '滑点', 10], ['spread_rate', '价差', 10],
  ['max_position', '最大仓位', 100], ['max_participation_rate', '最大成交参与率', 100],
] as const

function localDate(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function assetKey(symbol: string | null, assetClass: string | null) {
  return symbol && assetClass ? JSON.stringify([symbol, assetClass]) : ''
}

export function LabBacktestForm({ value, assets, onChange }: {
  value: LabBacktestSettings
  assets: Asset[]
  onChange: (patch: Partial<LabBacktestSettings>) => void
}) {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Asset[]>([])
  const [searchStatus, setSearchStatus] = useState('')
  useEffect(() => {
    const text = query.trim()
    if (!text) return
    let active = true
    const timer = window.setTimeout(() => {
      api.searchAssets(text).then(items => {
        if (!active) return
        setMatches(items)
        setSearchStatus(items.length ? '' : '没有匹配的标的')
      }).catch(() => { if (active) setSearchStatus('标的搜索暂不可用，可以选择目录中的标的。') })
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query])

  const selected = assetKey(value.symbol, value.asset_class)
  const choices = new Map([...assets, ...matches].map(asset => [assetKey(asset.symbol, asset.asset_class), asset]))
  const selectAsset = (key: string) => {
    const asset = choices.get(key)
    if (asset) onChange({ symbol: asset.symbol, asset_class: asset.asset_class, data_source: sourceForAssetClass(value.data_source, asset.asset_class) })
    else if (!key) onChange({ symbol: null, asset_class: null })
  }
  return <section className="lab-settings" aria-labelledby="lab-settings-title">
    <h2 id="lab-settings-title">回测设置</h2>
    <div className="lab-settings-grid">
      <label>回测标的<select value={selected} onChange={event => selectAsset(event.target.value)}>
        <option value="">请选择标的</option>
        {selected && !choices.has(selected) ? <option value={selected}>{value.symbol}</option> : null}
        {[...choices].map(([key, asset]) => <option key={key} value={key}>{asset.symbol} · {asset.name}</option>)}
      </select></label>
      <label>搜索标的<input type="search" value={query} placeholder="代码或名称" onChange={event => { setQuery(event.target.value); setMatches([]); setSearchStatus('') }} /></label>
      {searchStatus ? <p className="lab-form-note" role="status">{searchStatus}</p> : null}
      <label>开始时间<input type="datetime-local" value={localDate(value.start)} onChange={event => onChange({ start: event.target.value ? new Date(event.target.value).toISOString() : null })} /></label>
      <label>结束时间<input type="datetime-local" value={localDate(value.end)} onChange={event => onChange({ end: event.target.value ? new Date(event.target.value).toISOString() : null })} /></label>
      <label>行情周期<select value={value.interval} onChange={event => onChange({ interval: event.target.value as LabBacktestSettings['interval'] })}>
        {Object.entries(intervals).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
      <label>初始资金<input type="number" min="0.01" step="any" value={value.initial_capital || ''} onChange={event => onChange({ initial_capital: Number(event.target.value) })} /></label>
      <label>行情源<select value={value.data_source} onChange={event => onChange({ data_source: event.target.value as LabBacktestSettings['data_source'] })}>
        <option value="auto">自动选择</option><option value="yahoo">Yahoo Finance</option><option value="binance" disabled={value.asset_class !== 'crypto'}>Binance</option><option value="demo">演示数据</option>
      </select></label>
      <p className="lab-form-note">时间按本地时区输入。留空时使用已发布行情的可用范围。</p>
    </div>
    <details className="lab-advanced">
      <summary>高级设置</summary>
      <div className="lab-settings-grid">
        <label>复权方式<select value={value.adjustment} onChange={event => onChange({ adjustment: event.target.value as LabBacktestSettings['adjustment'] })}>
          <option value="auto">自动</option><option value="raw">不复权</option><option value="forward">前复权</option><option value="backward">后复权</option>
        </select></label>
        {costs.map(([key, label, max]) => <label key={key}>{label}（%）<input type="number" min={max === 100 ? 0.0001 : 0} max={max} step="any" value={Number((value[key] * 100).toFixed(8))} onChange={event => onChange({ [key]: Number(event.target.value) / 100 })} /></label>)}
      </div>
    </details>
  </section>
}

export function LabRunSettings({ settings }: { settings: LabBacktestSettings }) {
  const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '按行情覆盖范围'
  return <dl className="lab-run-settings">
    <div><dt>标的</dt><dd>{settings.symbol}</dd></div>
    <div><dt>周期</dt><dd>{intervalLabels[settings.interval] ?? settings.interval}</dd></div>
    <div><dt>开始</dt><dd>{time(settings.start)}</dd></div>
    <div><dt>结束</dt><dd>{time(settings.end)}</dd></div>
    <div><dt>行情源</dt><dd>{settings.data_source}</dd></div>
    <div><dt>初始资金</dt><dd>{settings.initial_capital.toLocaleString('zh-CN')}</dd></div>
    <div><dt>复权</dt><dd>{({ auto: '自动', raw: '不复权', forward: '前复权', backward: '后复权' })[settings.adjustment]}</dd></div>
    {costs.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{Number((settings[key] * 100).toFixed(8))}%</dd></div>)}
  </dl>
}
