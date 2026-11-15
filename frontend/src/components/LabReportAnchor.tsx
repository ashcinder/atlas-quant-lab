import { useId, useState } from 'react'
import { Link2 } from 'lucide-react'
import { ChainOrderPanel } from './BkcControls'

export function LabReportAnchor({ choices, multi, preview, saved, dirty, busy, onHistory }: {
  choices: { id: string; engine: string }[]
  multi: boolean
  preview: boolean
  saved: boolean
  dirty: boolean
  busy: boolean
  onHistory: () => void
}) {
  const heading = useId()
  const [choiceId, setChoiceId] = useState('')
  const choice = choices.find(item => item.id === choiceId) ?? choices[0]
  return <section className="lab-report-anchor" aria-labelledby={heading}>
    <header><Link2 size={20} aria-hidden="true" /><h2 id={heading}>回测报告上链存证</h2></header>
    <p>使用 Supervisor 钱包公开所选报告的收益、部分回测配置和报告摘要。策略源码不会上链。报告存证不执行 ZKP 验证。</p>
    {busy ? <p role="status">正在准备回测报告…</p>
      : choice ? <>
        {dirty ? <p className="lab-preview-note">此操作使用已保存的回测报告，不包含编辑器中未保存的修改。</p> : null}
        <label>存证报告<select value={choice.id} onChange={event => setChoiceId(event.target.value)}>
          {choices.map(item => <option key={item.id} value={item.id}>{item.engine} · {item.id.slice(0, 8)}</option>)}
        </select></label>
        <ChainOrderPanel key={choice.id} kind="report" resourceId={choice.id} />
      </> : <p className="lab-preview-note">{multi ? '组合回测任务暂不能通过此入口存证。'
        : !saved ? '先在顶部保存策略，再运行回测，生成可存证的报告。'
        : preview || dirty ? '当前结果是草稿试跑。保存修改并重新回测，或从历史回测打开已保存的报告。'
        : '运行回测或打开一份已保存的历史报告，即可存证。'}</p>}
    {!multi && saved && !choice && !busy ? <button type="button" onClick={onHistory}>打开历史回测</button> : null}
  </section>
}
