import { BacktestPeriod } from './BacktestPeriod'
import { ParameterSweep } from './ParameterSweep'
import { useEffect, useState } from 'react'
import { AlertTriangle, BarChart3, ChevronDown, Info, RotateCcw, SlidersHorizontal } from 'lucide-react'
import type { Asset, FundamentalsResponse, Strategy } from '../types'
import { FundamentalsPanel } from './FundamentalsPanel'

interface Props {
  codeContext?: React.ReactNode
  releasePicker?: React.ReactNode
  releaseSelected?: boolean
  sweepContext?: Record<string, unknown>
  asset: Asset | null
  strategies: Strategy[]
  selectedId: string
  values: Record<string, number | string | boolean>
  start?: string
  end?: string
  onStart?: (value: string) => void
  onEnd?: (value: string) => void
  capital: number
  commission: number
  slippage: number
  spread: number
  maxPosition: number
  maxParticipation: number
  stopLoss: number
  takeProfit: number
  onStrategy: (id: string) => void
  onValue: (key: string, value: number | string | boolean) => void
  onCapital: (value: number) => void
  onCommission: (value: number) => void
  onSlippage: (value: number) => void
  onSpread: (value: number) => void
  onMaxPosition: (value: number) => void
  onMaxParticipation: (value: number) => void
  onStopLoss: (value: number) => void
  onTakeProfit: (value: number) => void
  onReset: () => void
  fundamentals: FundamentalsResponse | null
  fundamentalsLoading: boolean
  fundamentalsError: string | null
  onFundamentals: (refresh?: boolean) => void
}

function riskClass(risk: Strategy['risk_level']): string {
  return risk === '低' ? 'low' : risk === '中' ? 'medium' : 'high'
}

export function StrategyPanel(props: Props) {
  const [view, setView] = useState<'strategy' | 'fundamentals'>('strategy')
  const selected = props.strategies.find((item) => item.id === props.selectedId)
  const { asset, onFundamentals } = props
  useEffect(() => {
    if (view === 'fundamentals') onFundamentals()
  }, [asset?.asset_class, asset?.symbol, onFundamentals, view])

  return (
    <aside className="strategy-panel">
      <div className="analysis-tabs" role="tablist" aria-label="分析侧栏">
        <button type="button" role="tab" aria-selected={view === 'strategy'} className={view === 'strategy' ? 'is-active' : ''} onClick={() => setView('strategy')}><SlidersHorizontal size={14} />策略参数</button>
        <button type="button" role="tab" aria-selected={view === 'fundamentals'} className={view === 'fundamentals' ? 'is-active' : ''} onClick={() => setView('fundamentals')}><BarChart3 size={14} />金融指标</button>
      </div>
      {view === 'fundamentals' ? (
        <FundamentalsPanel asset={props.asset} data={props.fundamentals} loading={props.fundamentalsLoading} error={props.fundamentalsError} onLoad={props.onFundamentals} />
      ) : <>
      <div className="panel-heading panel-context-heading">
        <span>回测参数</span>
        <button className="icon-button" onClick={props.onReset} title="恢复默认参数"><RotateCcw size={14} /></button>
      </div>
      {props.codeContext}
      <div className="form-section backtest-time-controls">
        <BacktestPeriod start={props.start ?? ''} end={props.end ?? ''} onApply={(start, end) => { props.onStart?.(start); props.onEnd?.(end) }} />
        <small>完整历史 K 线保持显示，所选区间用更鲜明的颜色突出。</small>
      </div>
      {selected && props.sweepContext && !props.releaseSelected && <ParameterSweep key={selected.id} disabled={!asset} fields={selected.parameters.filter(p => p.kind === 'number' || p.kind === 'integer').map(p => ({ key: `params.${p.key}`, label: p.label, value: Number(props.values[p.key] ?? p.default), min: p.minimum ?? undefined, max: p.maximum ?? undefined, integer: p.kind === 'integer' }))} payload={{ ...props.sweepContext, strategy_id: selected.id, params: props.values }} onApply={values => Object.entries(values).forEach(([key, value]) => props.onValue(key.replace(/^params\./, ''), value))} />}
      {!props.codeContext && <div className="strategy-select-wrap">
        {props.releasePicker}
        <label>策略模板{props.releaseSelected ? "（已选版本将覆盖此模板）" : ""}</label>
        <div className="select-shell">
          <select value={props.selectedId} onChange={(event) => props.onStrategy(event.target.value)}>
            {props.strategies.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.category} · {strategy.name}</option>)}
          </select>
          <ChevronDown size={14} />
        </div>
      </div>}
      {selected && !props.codeContext ? (
        <div className="strategy-description">
          <div><strong>{selected.name}</strong><span className={`risk-badge ${riskClass(selected.risk_level)}`}>{selected.risk_level}风险</span></div>
          <p>{selected.description}</p>
          <small><Info size={12} /> 适用：{selected.suitable_for}</small>
          {selected.risk_level === '极高' ? <small className="danger-note"><AlertTriangle size={12} /> 仅用于尾部风险研究</small> : null}
        </div>
      ) : null}
      <div className="form-section">
        <h3>资金与成本</h3>
        <label className="field-row"><span>初始资金</span><input type="number" min={1000} step={10000} value={props.capital} onChange={(event) => props.onCapital(Number(event.target.value))} /></label>
        <label className="field-row"><span>手续费率</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.commission * 100} onChange={(event) => props.onCommission(Number(event.target.value) / 100)} /><em>%</em></div></label>
        <label className="field-row"><span>滑点率</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.slippage * 100} onChange={(event) => props.onSlippage(Number(event.target.value) / 100)} /><em>%</em></div></label>
        <label className="field-row"><span>买卖价差</span><div className="input-suffix"><input type="number" min={0} max={10} step={0.01} value={props.spread * 100} onChange={(event) => props.onSpread(Number(event.target.value) / 100)} /><em>%</em></div></label>
      </div>
      <div className="form-section">
        <h3>仓位与风控</h3>
        <label className="field-row"><span>最大仓位</span><div className="input-suffix"><input type="number" min={1} max={100} step={1} value={props.maxPosition * 100} onChange={(event) => props.onMaxPosition(Number(event.target.value) / 100)} /><em>%</em></div></label>
        <label className="field-row"><span>最大成交量参与率</span><div className="input-suffix"><input type="number" min={0.01} max={100} step={0.1} value={props.maxParticipation * 100} onChange={(event) => props.onMaxParticipation(Number(event.target.value) / 100)} /><em>%</em></div></label>
        <label className="field-row"><span>止损（0=关闭）</span><div className="input-suffix"><input type="number" min={0} max={99} step={0.5} value={props.stopLoss * 100} onChange={(event) => props.onStopLoss(Number(event.target.value) / 100)} /><em>%</em></div></label>
        <label className="field-row"><span>止盈（0=关闭）</span><div className="input-suffix"><input type="number" min={0} max={1000} step={1} value={props.takeProfit * 100} onChange={(event) => props.onTakeProfit(Number(event.target.value) / 100)} /><em>%</em></div></label>
      </div>
      {!props.codeContext && <div className="form-section strategy-params">
        <h3>策略参数</h3>
        {selected?.parameters.map((parameter) => (
          <label className="field-stack" key={parameter.key}>
            <span>{parameter.label}{parameter.help ? <i title={parameter.help}>?</i> : null}</span>
            {parameter.kind === 'boolean' ? (
              <input type="checkbox" checked={Boolean(props.values[parameter.key])} onChange={(event) => props.onValue(parameter.key, event.target.checked)} />
            ) : parameter.kind === 'select' ? (
              <select value={String(props.values[parameter.key])} onChange={(event) => props.onValue(parameter.key, event.target.value)}>
                {parameter.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            ) : (
              <input type="number" value={Number(props.values[parameter.key])} min={parameter.minimum ?? undefined} max={parameter.maximum ?? undefined} step={parameter.step ?? 1} onChange={(event) => props.onValue(parameter.key, Number(event.target.value))} />
            )}
          </label>
        ))}
        {selected?.parameters.length === 0 ? <div className="empty-inline">该策略没有额外参数</div> : null}
      </div>}
      </>}
    </aside>
  )
}
