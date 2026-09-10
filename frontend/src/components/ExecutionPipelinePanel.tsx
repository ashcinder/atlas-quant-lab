import { useEffect, useState } from 'react'
import { api } from '../api'
import { request } from '../request'

export interface ExecutionPipeline {
  max_position: number
  commission_rate: number
  slippage_rate: number
  max_participation_rate: number
  ai_stages: Array<{ stage: string; enabled: boolean; authority: 'advisory' | 'veto' | 'reduce_only'; instructions: string; timeout_ms: number; max_reduction: number }>
}
const stages = [
  ['market', '市场判断', '审查市场状态与异常波动'],
  ['entry', '开仓审核', '买入前检查信号与风险'],
  ['buy_size', '买入数量', '在限制范围内减少本次买入量'],
  ['sell_size', '卖出数量', '审核本次卖出量；强制风控退出不受阻拦'],
  ['risk', '风险复核', '对拟提交订单进行风险复核'],
  ['execution', '提交前审核', '模拟成交前的最后一次订单检查'],
] as const
export const defaultPipeline = (): ExecutionPipeline => ({ max_position: .5, commission_rate: .001, slippage_rate: .0005, max_participation_rate: .01,
  ai_stages: stages.map(([stage]) => ({ stage, enabled: false, authority: 'advisory', instructions: '', timeout_ms: 2500, max_reduction: .25 })) })

export function ExecutionPipelinePanel({ value, onChange }: { value: ExecutionPipeline; onChange: (value: ExecutionPipeline) => void }) {
  const [modelStatus, setModelStatus] = useState('检查本地 AI 配置…')
  useEffect(() => {
    let active = true
    Promise.all([api.executionCapabilities(), request<{configured:boolean; provider:string; model:string}>('/ai-settings')]).then(([result, cloud]) => { if (active) setModelStatus(cloud.configured ? `${cloud.provider} · ${cloud.model}（云端审核）` : result.ai.configured ? '本地模型已配置 · 运行时检查连接' : 'AI 未配置 · 在设置中连接；关闭 AI 可正常回测') }).catch(() => { if (active) setModelStatus('无法读取 AI 配置状态') })
    return () => { active = false }
  }, [])
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schema: 'atlas.execution-pipeline/v1', pipeline: value }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'strategy-flow.json'; link.click(); URL.revokeObjectURL(url)
  }
  return <section className="execution-pipeline-panel">
    <div className="pipeline-actions"><span>{modelStatus}</span><button onClick={download}>导出流程</button></div>
    <div className="pipeline-fields">{([
      ['max_position', '仓位上限', 1, 100], ['commission_rate', '手续费', 0, 10], ['slippage_rate', '滑点', 0, 10], ['max_participation_rate', '成交参与率', .01, 100],
    ] as const).map(([key, label, min, max]) => <label key={key}>{label} %<input type="number" min={min} max={max} step="any" value={Number((value[key] * 100).toFixed(6))} onChange={e => onChange({ ...value, [key]: Number(e.target.value) / 100 })} /></label>)}</div>
    <p>用于图形化与模板的单次回测，不下实盘订单。AI 默认关闭；开启使用设置中的云端模型或本地模型，失败会中止回测。批量研究请关闭 AI。</p>
    <details><summary>保存与隐私说明</summary><p>流程设置暂存于当前页面，刷新前请导出。回测会将配置与审核指令发送给后端；这不是对平台保密的 ZKP / TEE 执行，请勿填写密钥或敏感策略秘密。</p></details>
    <div className="pipeline-stages">{stages.map(([id, label, help], index) => {
      const config = value.ai_stages[index]
      const patch = (next: Partial<typeof config>) => onChange({ ...value, ai_stages: value.ai_stages.map((item, i) => i === index ? { ...item, ...next } : item) })
      return <article key={id}><header><span><strong>{index + 1}. {label}</strong><small>{help}</small></span><label><input type="checkbox" checked={config.enabled} onChange={e => patch({ enabled: e.target.checked })} />AI</label></header>
        {config.enabled ? <div className="pipeline-ai-settings"><label>权限<select value={config.authority} onChange={e => patch({ authority: e.target.value as typeof config.authority })}><option value="advisory">仅建议，不改订单</option><option value="veto">可否决本次订单</option><option value="reduce_only">可减少订单数量</option></select></label><label>超时（毫秒）<input type="number" min="100" max="30000" value={config.timeout_ms} onChange={e => patch({ timeout_ms: Number(e.target.value) })} /></label>{config.authority === 'reduce_only' ? <label>最多减量 %<input type="number" min="0" max="100" value={config.max_reduction * 100} onChange={e => patch({ max_reduction: Number(e.target.value) / 100 })} /></label> : null}<label className="pipeline-prompt">审核指令<textarea maxLength={4000} value={config.instructions} placeholder="例如：检查近20根已收盘K线的波动，异常时拒绝加仓。" onChange={e => patch({ instructions: e.target.value })} /></label></div> : null}
      </article>
    })}</div>
  </section>
}
