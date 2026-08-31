import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Check, Equal, Plus, Scale, Search, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { formatPercent } from '../format'
import { normalizeWeightValues } from '../portfolio'
import type { Asset, BaseCurrency, DataSource, Interval, PortfolioResult, Strategy } from '../types'
import { PortfolioParametersPanel } from './PortfolioParametersPanel'

interface Props {
  catalog: Asset[]
  strategies: Strategy[]
  interval: Interval
  source: DataSource
  baseCurrency: BaseCurrency
  runSignal: number
  onLoading: (loading: boolean) => void
  onResult: (result: PortfolioResult | null) => void
  onError: (message: string | null) => void
}

const defaultSymbols = ['SPY', 'TLT', 'IEF', 'GLD', 'GC=F']
const defaultWeights = [0.30, 0.40, 0.15, 0.075, 0.075]
const maximumAssets = 12
const assetClasses = [
  { value: 'all', label: '全部' },
  { value: 'equity', label: '股票' },
  { value: 'etf', label: 'ETF' },
  { value: 'crypto', label: '加密货币' },
  { value: 'commodity', label: '商品' },
  { value: 'forex', label: '外汇' },
  { value: 'index', label: '指数' },
]

function normalizeWeights(items: Array<{ asset: Asset; weight: number }>) {
  const weights = normalizeWeightValues(items.map((item) => item.weight))
  return items.map((item, index) => ({ ...item, weight: weights[index] }))
}

function strategyDefaults(strategy?: Strategy) {
  return Object.fromEntries(strategy?.parameters.map((parameter) => [parameter.key, parameter.default]) ?? [])
}

function sixtyFortyWeights(items: Array<{ asset: Asset; weight: number }>, equityTarget: number) {
  const target = Math.min(0.9, Math.max(0.1, equityTarget))
  return items.map((item, index) => ({
    ...item,
    weight: index === 0 ? target : (1 - target) / Math.max(items.length - 1, 1),
  }))
}

interface AssetPickerProps {
  catalog: Asset[]
  excludedSymbols: string[]
  availableSlots: number
  onAdd: (assets: Asset[]) => void
  onClose: () => void
}

function PortfolioAssetPicker({ catalog, excludedSymbols, availableSlots, onAdd, onClose }: AssetPickerProps) {
  const [query, setQuery] = useState('')
  const [assetClass, setAssetClass] = useState('all')
  const [pending, setPending] = useState<Set<string>>(() => new Set())
  const searchRef = useRef<HTMLInputElement>(null)
  const excluded = useMemo(() => new Set(excludedSymbols), [excludedSymbols])
  const candidates = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return catalog.filter((asset) => {
      if (excluded.has(asset.symbol)) return false
      if (assetClass !== 'all' && asset.asset_class !== assetClass) return false
      if (!needle) return true
      return [asset.symbol, asset.name, asset.exchange, asset.asset_class, ...asset.tags]
        .join(' ').toLowerCase().includes(needle)
    })
  }, [assetClass, catalog, excluded, query])

  useEffect(() => {
    searchRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const toggle = (symbol: string) => {
    setPending((current) => {
      const next = new Set(current)
      if (next.has(symbol)) next.delete(symbol)
      else if (next.size < availableSlots) next.add(symbol)
      return next
    })
  }
  const confirm = () => onAdd(catalog.filter((asset) => pending.has(asset.symbol)))

  return <div className="asset-picker-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="asset-picker" role="dialog" aria-modal="true" aria-labelledby="asset-picker-title">
      <header><div><small>ASSET UNIVERSE</small><strong id="asset-picker-title">选择组合标的</strong><span>搜索并批量加入，最多 {maximumAssets} 项资产</span></div><button aria-label="关闭资产选择器" onClick={onClose} title="关闭资产选择器"><X size={16} /></button></header>
      <div className="asset-picker-search"><Search size={15} /><input aria-label="搜索可添加资产" ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索代码、名称、市场或类别" /><kbd>{candidates.length} 项可选</kbd></div>
      <nav aria-label="资产类别">{assetClasses.map((item) => <button key={item.value} aria-pressed={assetClass === item.value} className={assetClass === item.value ? 'is-active' : ''} onClick={() => setAssetClass(item.value)}>{item.label}</button>)}</nav>
      <div className="asset-picker-list">
        {candidates.length ? candidates.map((asset) => {
          const checked = pending.has(asset.symbol)
          const disabled = !checked && pending.size >= availableSlots
          return <label key={asset.symbol} className={`${checked ? 'is-selected' : ''} ${disabled ? 'is-disabled' : ''}`}>
            <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggle(asset.symbol)} />
            <i>{checked ? <Check size={12} /> : asset.asset_class.slice(0, 3).toUpperCase()}</i>
            <span><strong>{asset.symbol}</strong><small>{asset.name}</small></span>
            <em>{asset.exchange}</em><b>{asset.currency}</b>
          </label>
        }) : <div className="asset-picker-empty"><Search size={20} /><strong>没有匹配的可添加资产</strong><span>清除搜索词或切换资产类别。</span></div>}
      </div>
      <footer><span>还可添加 <strong>{availableSlots}</strong> 项 · 已选择 <strong>{pending.size}</strong> 项</span><div><button onClick={onClose}>取消</button><button className="confirm" disabled={pending.size === 0} onClick={confirm}><Plus size={13} />添加所选资产</button></div></footer>
    </section>
  </div>
}

export function PortfolioWorkspace(props: Props) {
  const {
    catalog, strategies, interval, source, baseCurrency, runSignal,
    onLoading, onResult, onError,
  } = props
  const [strategyId, setStrategyId] = useState('all_weather')
  const [capital, setCapital] = useState(100_000)
  const [rebalance, setRebalance] = useState('quarterly')
  const [commission, setCommission] = useState(0.001)
  const [slippage, setSlippage] = useState(0.0005)
  const [spread, setSpread] = useState(0.0005)
  const [cashBuffer, setCashBuffer] = useState(0)
  const [maxAssetWeight, setMaxAssetWeight] = useState(1)
  const [volatilityTarget, setVolatilityTarget] = useState(0)
  const [strategyValues, setStrategyValues] = useState<Record<string, number | string | boolean>>({})
  const [selected, setSelected] = useState<Array<{ asset: Asset; weight: number }>>([])
  const [assetPickerOpen, setAssetPickerOpen] = useState(false)
  const [allocationNotice, setAllocationNotice] = useState<string | null>(null)
  const lastRun = useRef(0)

  const activeSelected = useMemo(() => {
    if (selected.length > 0 || catalog.length === 0) return selected
    return defaultSymbols.map((symbol, index) => ({
      asset: catalog.find((asset) => asset.symbol === symbol) ?? {
        symbol, name: symbol, asset_class: 'etf', exchange: 'GLOBAL', currency: 'USD', timezone: 'UTC', tags: [],
      },
      weight: defaultWeights[index],
    }))
  }, [catalog, selected])

  const strategy = strategies.find((item) => item.id === strategyId)
  const effectiveStrategyValues = useMemo(
    () => ({ ...strategyDefaults(strategy), ...strategyValues }),
    [strategy, strategyValues],
  )

  useEffect(() => {
    if (runSignal === 0 || runSignal === lastRun.current || activeSelected.length < 2) return
    lastRun.current = runSignal
    onLoading(true)
    onError(null)
    api.runPortfolio({
      assets: activeSelected.map((item) => ({
        symbol: item.asset.symbol,
        asset_class: item.asset.asset_class,
        weight: strategyId === 'risk_parity' ? null : item.weight,
      })),
      strategy_id: strategyId,
      params: effectiveStrategyValues,
      interval,
      data_source: source === 'binance' ? 'auto' : source,
      initial_capital: capital,
      rebalance,
      commission_rate: commission,
      slippage_rate: slippage,
      spread_rate: spread,
      cash_buffer: cashBuffer,
      max_asset_weight: maxAssetWeight,
      volatility_target: volatilityTarget > 0 ? volatilityTarget : null,
      base_currency: baseCurrency,
      persist: true,
    }).then(onResult).catch((error: Error) => onError(error.message)).finally(() => onLoading(false))
  }, [
    activeSelected, baseCurrency, capital, cashBuffer, commission, interval, maxAssetWeight,
    onError, onLoading, onResult, rebalance, runSignal, slippage, source, spread,
    effectiveStrategyValues, strategyId, volatilityTarget,
  ])

  const selectStrategy = (id: string) => {
    const nextStrategy = strategies.find((item) => item.id === id)
    const defaults = strategyDefaults(nextStrategy)
    setStrategyId(id)
    setStrategyValues(defaults)
    if (id === 'sixty_forty') {
      setSelected(sixtyFortyWeights(activeSelected, Number(defaults.equity_target ?? 0.6)))
    }
    setAllocationNotice(null)
  }

  const updateStrategyValue = (key: string, value: number | string | boolean) => {
    setStrategyValues((current) => ({ ...current, [key]: value }))
    if (strategyId === 'sixty_forty' && key === 'equity_target') {
      setSelected(sixtyFortyWeights(activeSelected, Number(value)))
    }
  }

  const resetParameters = () => {
    const defaults = strategyDefaults(strategy)
    setCapital(100_000)
    setRebalance('quarterly')
    setCommission(0.001)
    setSlippage(0.0005)
    setSpread(0.0005)
    setCashBuffer(0)
    setMaxAssetWeight(1)
    setVolatilityTarget(0)
    setStrategyValues(defaults)
    if (strategyId === 'sixty_forty') {
      setSelected(sixtyFortyWeights(activeSelected, Number(defaults.equity_target ?? 0.6)))
    }
  }

  const updateWeight = (symbol: string, weight: number) => {
    const boundedWeight = Math.min(1, Math.max(0, Number.isFinite(weight) ? weight : 0))
    setSelected(activeSelected.map((item) => item.asset.symbol === symbol ? { ...item, weight: boundedWeight } : item))
    setAllocationNotice(null)
  }
  const remove = (symbol: string) => {
    const next = activeSelected.filter((item) => item.asset.symbol !== symbol)
    setSelected(strategyId === 'sixty_forty' ? sixtyFortyWeights(next, Number(effectiveStrategyValues.equity_target ?? 0.6)) : next)
    setMaxAssetWeight((current) => Math.max(current, (1 - cashBuffer) / next.length))
    setAllocationNotice(`已移除 ${symbol}，请检查并归一化剩余权重。`)
  }
  const addAssets = (assets: Asset[]) => {
    const next = [...activeSelected, ...assets.map((asset) => ({ asset, weight: 0 }))]
    setSelected(strategyId === 'sixty_forty' ? sixtyFortyWeights(next, Number(effectiveStrategyValues.equity_target ?? 0.6)) : next)
    setAssetPickerOpen(false)
    setAllocationNotice(`已添加 ${assets.map((asset) => asset.symbol).join('、')}；请设置目标权重后归一化。`)
  }
  const normalize = () => {
    if (strategyId === 'risk_parity') {
      setAllocationNotice('风险平价会根据滚动协方差自动计算权重，无需手动归一化。')
      return
    }
    const normalized = normalizeWeights(activeSelected)
    const changed = normalized.some((item, index) => Math.abs(item.weight - activeSelected[index].weight) > 0.000_001)
    setSelected(normalized)
    setAllocationNotice(changed ? '已按当前比例归一化，显示权重合计为 100.0%。' : '当前权重已经是 100.0%，无需调整。')
  }
  const totalWeight = activeSelected.reduce((sum, item) => sum + item.weight, 0)
  const minimumMaxAssetWeight = (1 - cashBuffer) / Math.max(activeSelected.length, 1)

  return (
    <div className="portfolio-workspace">
      <section className="portfolio-builder">
        <div className="workspace-title"><div><small>PORTFOLIO LAB</small><h2>多资产组合构建</h2><p>在同一时间轴上再平衡，并拆解每项资产的风险贡献。</p></div><Scale size={30} /></div>
        <div className="portfolio-controls portfolio-strategy-control">
          <label><span>组合策略</span><select value={strategyId} onChange={(event) => selectStrategy(event.target.value)}>{strategies.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <div><strong>参数已在右侧展开</strong><span>成本、再平衡、风险约束与当前策略参数均可编辑。</span></div>
        </div>
        <div className="allocation-header"><span>组合成分</span><div><button onClick={normalize} title="保持各资产相对比例，将合计权重调整为100%"><Equal size={14} />归一化至100%</button><button disabled={activeSelected.length >= maximumAssets} onClick={() => setAssetPickerOpen(true)}><Plus size={14} />选择资产</button></div></div>
        {allocationNotice ? <div className="allocation-feedback" role="status"><Check size={13} /><span>{allocationNotice}</span><button onClick={() => setAllocationNotice(null)} title="关闭提示"><X size={12} /></button></div> : null}
        <div className="allocation-table">
          <div className="allocation-row header"><span>标的</span><span>市场</span><span>币种</span><span>目标权重</span><span /></div>
          {activeSelected.map((item) => <div className="allocation-row" key={item.asset.symbol}><span><strong>{item.asset.symbol}</strong><small>{item.asset.name}</small></span><span>{item.asset.exchange}</span><span>{item.asset.currency}</span><span>{strategyId === 'risk_parity' ? <b className="automatic-weight">自动计算</b> : <><input aria-label={`${item.asset.symbol} 目标权重`} disabled={strategyId === 'sixty_forty'} type="number" min={0} max={100} step={0.5} value={(item.weight * 100).toFixed(1)} onChange={(event) => updateWeight(item.asset.symbol, Number(event.target.value) / 100)} /><em>%</em></>}</span><button aria-label={`移除 ${item.asset.symbol}`} title={`移除 ${item.asset.symbol}`} onClick={() => remove(item.asset.symbol)} disabled={activeSelected.length <= 2}><Trash2 size={14} /></button></div>)}
        </div>
        <div className={`weight-total ${Math.abs(totalWeight - 1) > 0.001 && strategyId !== 'risk_parity' ? 'invalid' : ''}`}><span>目标权重合计</span><strong>{strategyId === 'risk_parity' ? '由风险平价计算' : formatPercent(totalWeight)}</strong>{Math.abs(totalWeight - 1) > 0.001 && strategyId !== 'risk_parity' ? <em><AlertCircle size={13} />运行前请归一化至100%</em> : null}</div>
        {strategyId === 'risk_parity' ? <div className="allocation-bar automatic-allocation" aria-label="风险平价权重将在回测时自动计算"><span>回测时根据历史协方差生成权重</span></div> : <div className="allocation-bar" aria-label="组合权重">{activeSelected.map((item, index) => <i key={item.asset.symbol} style={{ width: `${item.weight * 100}%`, background: `hsl(${160 + index * 42} 58% 52%)` }} title={`${item.asset.symbol} ${formatPercent(item.weight)}`} />)}</div>}
      </section>
      <PortfolioParametersPanel strategy={strategy ?? null} values={effectiveStrategyValues} capital={capital} baseCurrency={baseCurrency} commission={commission} slippage={slippage} spread={spread} rebalance={rebalance} cashBuffer={cashBuffer} maxAssetWeight={maxAssetWeight} volatilityTarget={volatilityTarget} minimumMaxAssetWeight={minimumMaxAssetWeight} onValue={updateStrategyValue} onCapital={setCapital} onCommission={setCommission} onSlippage={setSlippage} onSpread={setSpread} onRebalance={setRebalance} onCashBuffer={(value) => { setCashBuffer(value); setMaxAssetWeight((current) => Math.max(current, (1 - value) / Math.max(activeSelected.length, 1))) }} onMaxAssetWeight={setMaxAssetWeight} onVolatilityTarget={setVolatilityTarget} onReset={resetParameters} />
      {assetPickerOpen ? <PortfolioAssetPicker catalog={catalog} excludedSymbols={activeSelected.map((item) => item.asset.symbol)} availableSlots={maximumAssets - activeSelected.length} onAdd={addAssets} onClose={() => setAssetPickerOpen(false)} /> : null}
    </div>
  )
}
