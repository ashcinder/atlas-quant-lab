import { ArrowDown, ArrowRight, Bot, Check, ChevronRight, Database, Layers3, Plus, ShieldCheck, SlidersHorizontal, Wallet, Waypoints } from 'lucide-react'
import { useRef, type ReactNode } from 'react'
import type { StudioAIRole, StudioTemplate, StudioWorkflow, StudioWorkflowNode } from '../types'

const stages: Array<{ title: string; question: string; types: string[]; role?: StudioAIRole; ai: string; icon: typeof Database }> = [
  { title: '观察市场', question: '用哪些信息作判断？', types: ['market_data', 'universe', 'feature_engine'], role: 'regime_detection', ai: '让 AI 识别市场状态', icon: Database },
  { title: '决定买卖', question: '什么条件下入场、退出？', types: ['strategy'], role: 'signal_review', ai: '让 AI 复核交易信号', icon: Waypoints },
  { title: '分配仓位', question: '每次投入多少？', types: ['position_sizer'], role: 'position_management', ai: '让 AI 建议仓位', icon: Wallet },
  { title: '控制风险', question: '什么时候必须停下来？', types: ['risk_gate'], role: 'risk_control', ai: '加入 AI 风险检查', icon: ShieldCheck },
  { title: '模拟成交', question: '交易成本如何计算？', types: ['execution_review', 'execution'], role: 'execution_review', ai: '让 AI 做成交前审查', icon: SlidersHorizontal },
  { title: '复盘与记录', question: '留下什么结果与证据？', types: ['audit', 'output'], ai: '', icon: Layers3 },
]

const explanations: Record<string, string> = {
  market_data: '读取行情，保持价格口径一致', universe: '确定参与研究的标的', feature_engine: '只使用当时已经出现的数据',
  strategy: '设置买入、卖出条件', position_sizer: '设定基础资金分配方式', risk_gate: '为每笔交易设置不可越过的限额',
  execution_review: '检查成交条件', execution: '下一根 K 线成交，计入费用与滑点', audit: '保留决策和版本记录', output: '汇总研究结果',
}

interface Props {
  workflow: StudioWorkflow
  selectedId: string
  templates: StudioTemplate[]
  activeTemplateId: string
  saving: boolean
  availableRoles: StudioAIRole[]
  onTemplate: (template: StudioTemplate) => void
  onSelect: (node: StudioWorkflowNode) => void
  onAddAI: (role: StudioAIRole) => void
  onName: (name: string) => void
  onEditRules?: () => void
  validation: ReactNode
  inspector: ReactNode
  diagnostics: ReactNode
}

export function GuidedWorkflow({ workflow, selectedId, templates, activeTemplateId, saving, availableRoles, onTemplate, onSelect, onAddAI, onName, onEditRules, validation, inspector, diagnostics }: Props) {
  const settingsRef = useRef<HTMLElement>(null)
  const canvasRef = useRef<HTMLElement>(null)
  const revealSettings = () => {
    if (window.matchMedia?.('(max-width: 820px)').matches) {
      requestAnimationFrame(() => settingsRef.current?.scrollIntoView?.({ block: 'start' }))
    }
  }
  const aiCount = workflow.nodes.filter((node) => node.type === 'ai_guard').length
  return <div className="guided-studio">
    <div className="guided-heading">
      <div><h1>搭建你的交易逻辑</h1><p>沿着交易的每一步，定义规则，加入 AI，再检验想法。</p></div>
      <div className="guided-mode"><Bot size={16} /><span>AI 编排预览<small>可配置与保存 · 尚未接入执行</small></span></div>
    </div>
    <div className="guided-start">
      <label><span>工作流名称</span><input aria-label="工作流名称" value={workflow.name} onChange={(event) => onName(event.target.value)} /></label>
      <details className="guided-templates"><summary>选择起步模板 <ChevronRight size={14} /></summary><div>{templates.map((template) => <button key={template.id} aria-label={`载入工作流模板 ${template.name}`} aria-pressed={activeTemplateId === template.id} disabled={saving} onClick={() => onTemplate(template)}><span><strong>{template.name === '专业基线树干' ? '基础交易流程' : template.name === 'AI 风险官树干' ? '带 AI 风控的流程' : template.name}</strong><small>{template.description}</small></span>{activeTemplateId === template.id ? <Check size={16} /> : <ArrowRight size={16} />}</button>)}</div></details>
      <div className="guided-count">{aiCount === 0 ? '从基础规则开始，AI 可随时加入' : `已加入 ${aiCount} 个 AI 积木`}</div>
    </div>
    <nav className="guided-outline" aria-label="交易步骤">{stages.map((stage, index) => <button key={stage.title} onClick={() => canvasRef.current?.querySelectorAll('li')[index]?.scrollIntoView?.({ block: 'start' })}><span>{index + 1}</span>{stage.title}</button>)}</nav>
    <div className="guided-workbench">
      <section ref={canvasRef} className="guided-canvas" aria-label="引导式策略画布">
        <div className="guided-canvas-caption"><span>交易流程</span><span>点击积木配置 <ChevronRight size={13} /></span></div>
        <ol className="guided-stages">{stages.map((stage, index) => {
          const Icon = stage.icon
          const nodes = workflow.nodes.filter((node) => stage.types.includes(node.type))
          const aiNodes = workflow.nodes.filter((node) => node.type === 'ai_guard' && node.config.role === stage.role)
          return <li key={stage.title} className={nodes.some((node) => node.id === selectedId) || aiNodes.some((node) => node.id === selectedId) ? 'is-current' : ''}>
            <div className="guided-stage-number">{index + 1}</div>
            <div className="guided-stage-body"><header><Icon size={18} /><h2>{stage.title}</h2><span>{stage.question}</span></header>
              <div className="guided-blocks">{workflow.nodes.filter((node) => stage.types.includes(node.type) || (node.type === 'ai_guard' && node.config.role === stage.role)).map((node) => node.type === 'ai_guard'
                ? <button key={node.id} className={`guided-ai-block ${selectedId === node.id ? 'is-selected' : ''}`} aria-label={`配置 ${node.label} #${node.id}`} aria-pressed={selectedId === node.id} onClick={() => { onSelect(node); revealSettings() }}><Bot size={17} /><span><strong>{node.label}</strong><small>{node.config.authority === 'veto' ? '可以拦截交易' : node.config.authority === 'bounded_adjustment' ? '在限定范围内调整' : '只提供建议'} · 待接入执行</small></span><ChevronRight size={16} /></button>
                : <button key={node.id} className={`guided-block ${selectedId === node.id ? 'is-selected' : ''}`} aria-label={`配置 ${node.label} #${node.id}`} aria-pressed={selectedId === node.id} onClick={() => { onSelect(node); revealSettings() }}><span><strong>{node.label}</strong><small>{explanations[node.type]}</small></span><ChevronRight size={16} /></button>)}
                {!nodes.length ? <p className="guided-missing">此模板未包含该步骤</p> : null}
              </div>
              {stage.role && availableRoles.includes(stage.role) ? <button className="guided-add-ai" onClick={() => { onAddAI(stage.role!); revealSettings() }}><Plus size={14} />{stage.ai}</button> : null}
              {index === 5 ? <p className="guided-audit-note">记录由系统确定性生成，AI 不能修改审计证据。</p> : null}
            </div>
            {index < stages.length - 1 ? <ArrowDown className="guided-stage-arrow" size={14} /> : null}
          </li>
        })}</ol>
        <div className="guided-validation">{validation}{diagnostics}</div>
        {onEditRules ? <div className="guided-next"><div><strong>准备检验你的想法？</strong><p>先配置可回测的买卖规则。AI 编排暂不参与回测。</p></div><button onClick={onEditRules}>配置交易规则 <ArrowRight size={16} /></button></div> : null}
      </section>
      <aside ref={settingsRef} className="guided-settings" aria-label="积木设置"><button className="guided-back" onClick={() => canvasRef.current?.scrollIntoView?.({ block: 'start' })}>返回策略画布</button>{inspector}</aside>
    </div>
  </div>
}
