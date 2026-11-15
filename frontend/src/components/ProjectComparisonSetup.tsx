import { CheckCircle2, CircleHelp, CircleMinus, FlaskConical } from 'lucide-react'
import { useId } from 'react'
import { comparisonLabels, type ComparisonEngineCheck, type ComparisonMethod, type PreparedComparison } from '../compute/compareBacktests'
import { formatDate } from '../format'
import type { LabBacktestSettings } from '../lab-strategy-types'
import type { Asset } from '../types'
import { LabBacktestForm } from './LabBacktestForm'

export function ProjectComparisonSetup({ entry, scriptOnly, method, settings, assets, busy, preparing, error,
  checked, engines, onMethod, onSettings }: {
  entry: string
  scriptOnly: boolean
  method: ComparisonMethod
  settings: LabBacktestSettings
  assets: Asset[]
  busy: boolean
  preparing: boolean
  error?: string
  checked?: PreparedComparison
  engines?: ComparisonEngineCheck[]
  onMethod: (method: ComparisonMethod) => void
  onSettings: (settings: Partial<LabBacktestSettings>) => void
}) {
  const methodInput = useId()
  return <>
    <div className="project-comparison-intro">
      <div><FlaskConical size={15} /><strong>引擎对比</strong></div>
      <code title={entry}>{entry.split('/').at(-1)}</code>
    </div>
    {scriptOnly ? <div className="project-comparison-blocked">
      <strong>此入口使用项目自带的回测</strong>
      <p>点「运行脚本」查看完整组合结果。引擎对比需要从入口导出 <code>target(context)</code>，逐根返回单个标的的目标仓位。</p>
    </div> : <>
      <p className="project-comparison-description">先检查入口、行情和引擎，再用同一批 K 线与仓位信号运行回测。</p>
      {preparing ? <p className="project-check-feedback" role="status">正在检查行情、生成仓位信号和读取引擎状态…</p> : null}
      {error ? <p className="project-check-feedback is-error" role="alert">{error}</p> : null}
      {checked && engines ? <section className="project-check-result" aria-label="引擎检查结果">
        <header><CheckCircle2 size={15} /><strong>信号已准备</strong></header>
        <p>{checked.barCount.toLocaleString('zh-CN')} 根 K 线 · {formatDate(checked.from)} 至 {formatDate(checked.to)}</p>
        <ul>{engines.map(engine => {
          const Icon = engine.state === 'ready' ? CheckCircle2 : engine.state === 'unavailable' ? CircleMinus : CircleHelp
          return <li key={engine.engine} data-state={engine.state}>
            <Icon size={14} aria-hidden="true" />
            <span><strong>{comparisonLabels[engine.engine]}</strong>{engine.version ? <small>{engine.version}</small> : null}</span>
            <span>{engine.state === 'ready' ? '可运行' : engine.state === 'unknown' ? '运行时检查' : '跳过'}</span>
            {engine.reason ? <small>{engine.reason}</small> : null}
          </li>
        })}</ul>
      </section> : null}
      {settings.data_source === 'huggingface' ? <fieldset className="project-comparison-method" disabled={busy}>
        <legend>对比口径</legend>
        <label><input type="radio" name={methodInput} checked={method === 'unified'} onChange={() => onMethod('unified')} />
          <span><strong>统一账本</strong><small>使用统一的成交规则，检查框架回放的一致性。</small></span>
        </label>
        <label><input type="radio" name={methodInput} checked={method === 'native'} onChange={() => onMethod('native')} />
          <span><strong>独立撮合</strong><small>使用各引擎的成交与费用规则，查看差异。</small></span>
        </label>
      </fieldset> : <p className="project-comparison-description">当前行情源使用独立撮合。选择历史快照可切换到统一账本。</p>}
      <fieldset className="project-compare-settings" disabled={busy}>
        <LabBacktestForm compact lockedAdjustment={settings.data_source === 'huggingface' ? 'raw' : 'auto'} value={settings} assets={assets} onChange={onSettings} />
      </fieldset>
    </>}
  </>
}
