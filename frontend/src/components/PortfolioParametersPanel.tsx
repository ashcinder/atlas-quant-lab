import { Info, RotateCcw, Scale, SlidersHorizontal } from 'lucide-react'
import type { BaseCurrency, Strategy } from '../types'

interface Props {
  strategy: Strategy | null
  values: Record<string, number | string | boolean>
  capital: number
  baseCurrency: BaseCurrency
  commission: number
  slippage: number
  spread: number
  rebalance: string
  cashBuffer: number
  maxAssetWeight: number
  volatilityTarget: number
  minimumMaxAssetWeight: number
  onValue: (key: string, value: number | string | boolean) => void
  onCapital: (value: number) => void
  onCommission: (value: number) => void
  onSlippage: (value: number) => void
  onSpread: (value: number) => void
  onRebalance: (value: string) => void
  onCashBuffer: (value: number) => void
  onMaxAssetWeight: (value: number) => void
  onVolatilityTarget: (value: number) => void
  onReset: () => void
}

const percentParameters = new Set([
  'rebalance_band', 'min_trade_rate', 'covariance_shrinkage', 'equity_target',
])

function riskClass(risk?: Strategy['risk_level']) {
  return risk === '低' ? 'low' : risk === '中' ? 'medium' : 'high'
}

export function PortfolioParametersPanel(props: Props) {
  const strategy = props.strategy
  return <aside className="portfolio-parameters" aria-label="组合回测参数">
    <div className="panel-heading">
      <span><SlidersHorizontal size={15} />组合参数</span>
      <button className="icon-button" aria-label="恢复组合默认参数" onClick={props.onReset} title="恢复默认参数"><RotateCcw size={14} /></button>
    </div>

    {strategy ? <div className="strategy-description portfolio-parameter-summary">
      <div><strong>{strategy.name}</strong><span className={`risk-badge ${riskClass(strategy.risk_level)}`}>{strategy.risk_level}风险</span></div>
      <p>{strategy.description}</p>
      <small><Info size={12} />适用：{strategy.suitable_for}</small>
    </div> : null}

    <div className="form-section">
      <h3>资金与成本</h3>
      <label className="field-row"><span>初始资金 <small>{props.baseCurrency}</small></span><input type="number" min={1000} step={10000} value={props.capital} onChange={(event) => props.onCapital(Number(event.target.value))} /></label>
      <label className="field-row"><span>手续费率</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.commission * 100} onChange={(event) => props.onCommission(Number(event.target.value) / 100)} /><em>%</em></div></label>
      <label className="field-row"><span>滑点率</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.slippage * 100} onChange={(event) => props.onSlippage(Number(event.target.value) / 100)} /><em>%</em></div></label>
      <label className="field-row"><span>买卖价差</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.spread * 100} onChange={(event) => props.onSpread(Number(event.target.value) / 100)} /><em>%</em></div></label>
    </div>

    <div className="form-section">
      <h3>再平衡与风控</h3>
      <label className="field-stack"><span>再平衡频率</span><select value={props.rebalance} onChange={(event) => props.onRebalance(event.target.value)}><option value="monthly">每月</option><option value="quarterly">每季度</option><option value="yearly">每年</option></select></label>
      <label className="field-row"><span>现金缓冲</span><div className="input-suffix"><input type="number" min={0} max={49} step={1} value={props.cashBuffer * 100} onChange={(event) => props.onCashBuffer(Number(event.target.value) / 100)} /><em>%</em></div></label>
      <label className="field-row"><span>单资产上限</span><div className="input-suffix"><input type="number" min={props.minimumMaxAssetWeight * 100} max={100} step={1} value={props.maxAssetWeight * 100} onChange={(event) => props.onMaxAssetWeight(Number(event.target.value) / 100)} /><em>%</em></div></label>
      <label className="field-row"><span>目标年化波动 <small>0=关闭</small></span><div className="input-suffix"><input type="number" min={0} max={100} step={1} value={props.volatilityTarget * 100} onChange={(event) => props.onVolatilityTarget(Number(event.target.value) / 100)} /><em>%</em></div></label>
    </div>

    <div className="form-section portfolio-strategy-params">
      <h3>当前策略参数</h3>
      {strategy?.parameters.map((parameter) => {
        const isPercent = percentParameters.has(parameter.key)
        const raw = props.values[parameter.key] ?? parameter.default
        const value = isPercent ? Number(raw) * 100 : raw
        const minimum = parameter.minimum == null ? undefined : isPercent ? parameter.minimum * 100 : parameter.minimum
        const maximum = parameter.maximum == null ? undefined : isPercent ? parameter.maximum * 100 : parameter.maximum
        const step = parameter.step == null ? undefined : isPercent ? parameter.step * 100 : parameter.step
        return <label className="field-stack" key={parameter.key}>
          <span>{parameter.label}{parameter.help ? <i title={parameter.help}>?</i> : null}</span>
          {parameter.kind === 'boolean' ? <input type="checkbox" checked={Boolean(raw)} onChange={(event) => props.onValue(parameter.key, event.target.checked)} />
            : parameter.kind === 'select' ? <select value={String(raw)} onChange={(event) => props.onValue(parameter.key, event.target.value)}>{parameter.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
              : <div className={isPercent ? 'input-suffix full-width' : ''}><input type="number" value={Number(value)} min={minimum} max={maximum} step={step} onChange={(event) => props.onValue(parameter.key, isPercent ? Number(event.target.value) / 100 : Number(event.target.value))} />{isPercent ? <em>%</em> : null}</div>}
        </label>
      })}
      {!strategy?.parameters.length ? <div className="empty-inline">该策略使用组合成分中的目标权重</div> : null}
    </div>

    <details className="portfolio-methodology">
      <summary><Scale size={13} />回测计算口径</summary>
      <ul><li>各资产按共同交易日期对齐。</li><li>交易在再平衡日开盘价成交。</li><li>风险平价只使用当时可知的历史数据。</li><li>目标波动率只降低暴露，不加杠杆。</li></ul>
    </details>
  </aside>
}
