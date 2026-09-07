import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { StrategyPackageRecord } from '../types'

export function PrivateExecutionPanel({ agentId, token, packages, datasetHash, onDataset, preparing }: {
  agentId: string; token: string; packages: StrategyPackageRecord[]; datasetHash?: string
  onDataset: () => void; preparing: boolean
}) {
  const [selected, setSelected] = useState('')
  const [params, setParams] = useState('{}')
  const [consent, setConsent] = useState(false)
  const [ai, setAi] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('先检查执行环境，再选择策略包和已登记的市场数据。')
  const [capabilities, setCapabilities] = useState<Awaited<ReturnType<typeof api.executionCapabilities>> | null>(null)
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.executePrivatePackage>> | null>(null)
  const active = useRef(true)
  const pending = useRef(false)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const check = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    try {
      const state = await api.executionCapabilities()
      if (active.current) { setCapabilities(state); setMessage(state.python.configured ? '已配置。实际运行时会再次检查 gVisor 和镜像，缺失时拒绝执行。' : '尚未配置独立 gVisor 执行器，请按执行环境部署指南准备 Linux Runner。') }
    } catch (error) { if (active.current) setMessage(error instanceof Error ? error.message : '环境检查失败') }
    finally { pending.current = false; if (active.current) setBusy(false) }
  }
  const execute = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true); setResult(null); setMessage('正在隔离执行。关闭页面不会自动取消服务端任务，请勿重复提交。')
    try {
      const parameters: unknown = JSON.parse(params)
      if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('参数必须是 JSON 对象')
      const next = await api.executePrivatePackage(agentId, selected, token, {
        market_data_hash: datasetHash, parameters, acknowledge_host_visibility: consent,
        ai_provider: ai ? 'local' : null, ai_authority: 'reduce_only', max_bars: 256,
      })
      if (active.current) { setResult(next); setMessage('私密研究执行完成。本结果不是 ZKP 或 TEE 证明，不会自动公开发布。') }
    } catch (error) { if (active.current) setMessage(error instanceof Error ? error.message : '执行未完成') }
    finally { pending.current = false; if (active.current) setBusy(false) }
  }
  return <section className="private-execution" aria-labelledby="private-execution-title">
    <header><div><small>PRIVATE RESEARCH · 固定安全流程</small><h3 id="private-execution-title">运行 Python 策略包</h3><p>逐根供数 → 策略提议 → 可选 AI 减仓审查 → 最终硬风控 → 独立记账</p></div><button disabled={busy} onClick={check}>检查执行环境</button></header>
    <div className="private-execution-fields">
      <label>策略包<select aria-label="执行策略包" disabled={busy} value={selected} onChange={(event) => { setSelected(event.target.value); setResult(null); setParams('{}') }}><option value="">请选择 Python 策略包</option>{packages.filter((p) => p.language === 'python').map((p) => <option key={p.id} value={p.id}>{p.name} v{p.version}</option>)}</select></label>
      <label>参数覆盖 · JSON<textarea aria-label="执行参数覆盖" disabled={busy} value={params} onChange={(event) => setParams(event.target.value)} spellCheck={false} /><small>留空对象使用包内默认值。当前固定：资金 100,000、手续费 10 bps、滑点 5 bps、仓位上限 95%、回撤熔断 25%、成交量参与率 1%。</small></label>
    </div>
    <div className="private-execution-data"><button disabled={busy || preparing} onClick={onDataset}>{datasetHash ? '更新市场数据集' : '登记市场数据集'}</button><code>{datasetHash ?? '只使用已登记的真实市场数据，最多最近 256 根 K 线。'}</code></div>
    <label className="private-execution-consent"><input type="checkbox" checked={ai} disabled={busy || !capabilities?.ai.configured} onChange={(event) => setAi(event.target.checked)} />启用本地 AI 风险审查：只能减少或否决仓位；失败时拒绝目标仓位。</label>
    <label className="private-execution-consent"><input type="checkbox" checked={consent} disabled={busy} onChange={(event) => setConsent(event.target.checked)} />我理解：这是单标的研究执行，平台主机能读取策略，不具备对平台保密的 TEE 机密性。可视化 DAG 不会在此自动执行。</label>
    <footer><p role="status">{message}</p><button className="primary-action" disabled={busy || !selected || !token || !consent || !datasetHash || !capabilities?.python.configured} onClick={execute}>{busy ? '处理中…' : '隔离运行策略'}</button></footer>
    {result ? <div className="private-execution-result"><strong>研究结果 · 非证明</strong><dl><div><dt>总收益</dt><dd>{(result.metrics.total_return * 100).toFixed(2)}%</dd></div><div><dt>最大回撤</dt><dd>{(result.metrics.max_drawdown * 100).toFixed(2)}%</dd></div><div><dt>Sharpe</dt><dd>{result.metrics.sharpe.toFixed(2)}</dd></div><div><dt>AI 调用 / 失败拒绝</dt><dd>{result.ai_calls} / {result.ai_failed_closed}</dd></div></dl>{result.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
  </section>
}
