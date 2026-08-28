import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Equal, Plus, Scale, Trash2 } from 'lucide-react'
import { api } from '../api'
import { formatPercent } from '../format'
import type { Asset, BaseCurrency, DataSource, Interval, PortfolioResult, Strategy } from '../types'

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

export function PortfolioWorkspace(props: Props) {
  const [strategyId, setStrategyId] = useState('all_weather')
  const [capital, setCapital] = useState(100_000)
  const [rebalance, setRebalance] = useState('quarterly')
  const [selected, setSelected] = useState<Array<{ asset: Asset; weight: number }>>([])
  const lastRun = useRef(0)

  const activeSelected = useMemo(() => {
    if (selected.length > 0 || props.catalog.length === 0) return selected
    return defaultSymbols.map((symbol, index) => ({
      asset: props.catalog.find((asset) => asset.symbol === symbol) ?? {
        symbol, name: symbol, asset_class: 'etf', exchange: 'GLOBAL', currency: 'USD', timezone: 'UTC', tags: [],
      },
      weight: defaultWeights[index],
    }))
  }, [props.catalog, selected])

  useEffect(() => {
    if (props.runSignal === 0 || props.runSignal === lastRun.current || activeSelected.length < 2) return
    lastRun.current = props.runSignal
    props.onLoading(true)
    props.onError(null)
    api.runPortfolio({
      assets: activeSelected.map((item) => ({
        symbol: item.asset.symbol,
        asset_class: item.asset.asset_class,
        weight: strategyId === 'risk_parity' ? null : item.weight,
      })),
      strategy_id: strategyId,
      interval: props.interval,
      data_source: props.source === 'binance' ? 'auto' : props.source,
      initial_capital: capital,
      rebalance,
      base_currency: props.baseCurrency,
      persist: true,
    }).then(props.onResult).catch((error: Error) => props.onError(error.message)).finally(() => props.onLoading(false))
  }, [activeSelected, capital, props, rebalance, strategyId])

  const updateWeight = (symbol: string, weight: number) => {
    setSelected(activeSelected.map((item) => item.asset.symbol === symbol ? { ...item, weight } : item))
  }
  const remove = (symbol: string) => setSelected(activeSelected.filter((item) => item.asset.symbol !== symbol))
  const addAsset = () => {
    const next = props.catalog.find((asset) => !activeSelected.some((item) => item.asset.symbol === asset.symbol))
    if (next) setSelected([...activeSelected, { asset: next, weight: 0 }])
  }
  const normalize = () => {
    const total = activeSelected.reduce((sum, item) => sum + item.weight, 0)
    if (total > 0) setSelected(activeSelected.map((item) => ({ ...item, weight: item.weight / total })))
  }
  const totalWeight = activeSelected.reduce((sum, item) => sum + item.weight, 0)
  const strategy = props.strategies.find((item) => item.id === strategyId)

  return (
    <div className="portfolio-workspace">
      <section className="portfolio-builder">
        <div className="workspace-title"><div><small>PORTFOLIO LAB</small><h2>多资产组合构建</h2><p>在同一时间轴上再平衡，并拆解每项资产的风险贡献。</p></div><Scale size={30} /></div>
        <div className="portfolio-controls">
          <label><span>组合策略</span><select value={strategyId} onChange={(event) => setStrategyId(event.target.value)}>{props.strategies.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <label><span>初始资金（{props.baseCurrency}）</span><input type="number" value={capital} min={1000} step={10000} onChange={(event) => setCapital(Number(event.target.value))} /></label>
          <label><span>再平衡</span><select value={rebalance} onChange={(event) => setRebalance(event.target.value)}><option value="monthly">每月</option><option value="quarterly">每季度</option><option value="yearly">每年</option></select></label>
        </div>
        {strategy ? <div className="portfolio-strategy-note"><strong>{strategy.name}</strong><span>{strategy.description}</span><em>{strategy.risk_level}风险</em></div> : null}
        <div className="allocation-header"><span>组合成分</span><div><button onClick={normalize}><Equal size={14} />归一化</button><button onClick={addAsset}><Plus size={14} />添加资产</button></div></div>
        <div className="allocation-table">
          <div className="allocation-row header"><span>标的</span><span>市场</span><span>币种</span><span>目标权重</span><span /></div>
          {activeSelected.map((item) => <div className="allocation-row" key={item.asset.symbol}><span><strong>{item.asset.symbol}</strong><small>{item.asset.name}</small></span><span>{item.asset.exchange}</span><span>{item.asset.currency}</span><span><input disabled={strategyId === 'risk_parity'} type="number" min={0} max={100} step={0.5} value={(item.weight * 100).toFixed(1)} onChange={(event) => updateWeight(item.asset.symbol, Number(event.target.value) / 100)} /><em>%</em></span><button onClick={() => remove(item.asset.symbol)} disabled={activeSelected.length <= 2}><Trash2 size={14} /></button></div>)}
        </div>
        <div className={`weight-total ${Math.abs(totalWeight - 1) > 0.001 && strategyId !== 'risk_parity' ? 'invalid' : ''}`}><span>目标权重合计</span><strong>{strategyId === 'risk_parity' ? '由风险平价计算' : formatPercent(totalWeight)}</strong>{Math.abs(totalWeight - 1) > 0.001 && strategyId !== 'risk_parity' ? <em><AlertCircle size={13} />运行前请归一化至100%</em> : null}</div>
        <div className="allocation-bar" aria-label="组合权重">{activeSelected.map((item, index) => <i key={item.asset.symbol} style={{ width: `${item.weight * 100}%`, background: `hsl(${160 + index * 42} 58% 52%)` }} title={`${item.asset.symbol} ${formatPercent(item.weight)}`} />)}</div>
      </section>
      <aside className="portfolio-guide"><h3>组合回测口径</h3><ul><li>各资产在共同交易日期对齐。</li><li>权重在再平衡日确定并计入交易成本。</li><li>风险平价只使用当时可知的滚动协方差。</li><li>混合币种结果会显示汇率口径提示。</li></ul><div className="guide-callout"><Scale size={17} /><p><strong>权重不是风险贡献</strong><span>低波动资产可能权重大，但风险贡献仍较低；结果页会分别展示。</span></p></div></aside>
    </div>
  )
}
