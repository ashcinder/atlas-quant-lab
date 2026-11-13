import { useEffect, useState } from 'react'
import { api } from '../api'
import type { BacktestEngine, BacktestResult } from '../types'

export function BacktestEnginePicker({ value, onChange, result, executionModel='native', onExecutionModel, unifiedAvailable=false }: {executionModel?:'native'|'unified';onExecutionModel?:(value:'native'|'unified')=>void;unifiedAvailable?:boolean;value: BacktestEngine; onChange: (value: BacktestEngine) => void; result: BacktestResult | null}) {
  const [engines, setEngines] = useState<Array<{id: BacktestEngine; name: string; available: boolean; description: string; version?: string; reason?: string}>>([])
  const [error, setError] = useState('')
  useEffect(() => { let active = true; api.backtestEngines().then(data => { if (active) setEngines(data) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [])
  const selected = engines.find(engine => engine.id === value)
  return <div className="form-section">
    <label className="field-stack"><span>回测框架</span><select aria-label="回测框架" value={value} onChange={e => onChange(e.target.value as BacktestEngine)}>
      {!engines.length && <option value="atlas">当前引擎 · 浏览器</option>}
      {engines.map(engine => <option key={engine.id} value={engine.id} disabled={!engine.available}>{engine.name}{engine.available ? '' : '（未就绪）'}</option>)}
    </select></label>
    <small>{selected?.description}</small>
    {onExecutionModel && unifiedAvailable && <label className="field-stack"><span>成交与账户口径</span><select aria-label="成交与账户口径" value={executionModel} onChange={e=>onExecutionModel(e.target.value as 'native'|'unified')}><option value="unified">统一研究口径（三框架对账）</option><option value="native">框架默认口径（保留原生规则）</option></select></label>}
    {unifiedAvailable && executionModel==='unified' && <small>各框架事件回放，共用策略信号与研究成交账本：下一根开盘、相同费用及数量规则。允许零股，不模拟T+1、涨跌停、印花税或分红送转；不使用原生股票撮合。</small>}

    {engines.filter(e => !e.available).map(e => <small key={e.id}>{e.name}：{e.reason}</small>)}
    {error && <small role="alert">框架状态获取失败：{error}</small>}
    {value !== 'atlas' && <p>外部框架在本机后端执行，支持内置、图形与Python仓位策略。Hugging Face日期留空会回放完整已发布历史，其他来源请指定日期；参数研究、订阅策略、代码策略和 Proof 继续使用当前引擎。默认口径保留各框架规则；统一研究口径用于逐根对账。</p>}
    {value === 'rqalpha' && (!unifiedAvailable || executionModel==='native') && <small>Hugging Face支持A股全部已发布周期与不复权价格；自动来源仍使用bundle日线。当根收盘撮合，费用含原生最低佣金与印花税。其许可证对商业使用有额外授权要求。</small>}
    {result && <small>当前结果：{result.execution_model==='unified'?'统一研究口径 · ':'框架默认 · '}{result.backtest_engine ?? 'atlas'}{result.engine_version ? ` ${result.engine_version}` : ''}</small>}
  </div>
}
