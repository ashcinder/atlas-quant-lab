import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import {
  Beaker, Braces, Check, FileArchive, FlaskConical, GitBranch, LoaderCircle,
  ShieldCheck, LayoutDashboard, ArrowRight, Code2,
} from 'lucide-react'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'
import type { StudioTab } from './QuantStrategyStudio'
import { api } from '../api'
import type {
  CustomStrategyRecord, ResearchJob, StrategyProject,
  StrategyProjectArtifactKind, StrategyProjectCreate, StudioWorkflowRecord,
} from '../types'
import { StrategyProjectBar } from './StrategyProjectBar'
import './code-strategy.css'

const CodeStrategyWorkspace = lazy(() => import('./CodeStrategyWorkspace').then((module) => ({ default: module.CodeStrategyWorkspace })))
const ResearchWorkspace = lazy(() => import('./ResearchWorkspace').then((module) => ({ default: module.ResearchWorkspace })))
const QuantStrategyStudio = lazy(() => import('./QuantStrategyStudio').then((module) => ({ default: module.QuantStrategyStudio })))

export type StrategyLabTab = 'overview' | 'builder' | 'workflow' | 'validate' | 'packages' | 'proof' | 'sdk'

interface Props extends Omit<ResearchWorkspaceProps, 'view' | 'showHeader'> {
  initialTab?: StrategyLabTab
}

const tabs: Array<{ id: StrategyLabTab; label: string; stage: string; icon: typeof Braces }> = [
  { id: 'overview', label: '项目总览', stage: '', icon: LayoutDashboard },
  { id: 'builder', label: '交易规则', stage: '01 DRAFT', icon: Braces },
  { id: 'workflow', label: '策略画布', stage: '02 COMPOSE', icon: GitBranch },
  { id: 'validate', label: '研究验证', stage: '03 VALIDATE', icon: FlaskConical },
  { id: 'packages', label: '历史档案', stage: '04 VERSION', icon: FileArchive },
  { id: 'proof', label: 'ZKP 证明', stage: '05 PROVE', icon: ShieldCheck },
  { id: 'sdk', label: 'SDK 与格式', stage: 'DEVKIT', icon: Beaker },
]

const studioTabFor = (tab: StrategyLabTab): StudioTab => tab === 'packages' ? 'packages' : tab === 'proof' ? 'proof' : tab === 'sdk' ? 'sdk' : 'workflow'
const isStudioTab = (tab: StrategyLabTab) => tab === 'workflow' || tab === 'packages' || tab === 'proof' || tab === 'sdk'

function tabComplete(tab: StrategyLabTab, project: StrategyProject | null) {
  if (!project) return false
  if (tab === 'builder') return Boolean(project.strategy_hash)
  if (tab === 'workflow') return project.workflow_valid
  if (tab === 'validate') return project.research_robust
  if (tab === 'packages') return Boolean(project.package_id || project.commitment)
  if (tab === 'proof') return Boolean(project.quant_report_id)
  return false
}

const descriptions: Record<StrategyLabTab, string> = {
  overview: '从一个投资假设开始，将规则、实验与证据组织成一项完整研究。',
  builder: '组合入场和退出条件，保存规则，再使用真实行情回测。',
  workflow: '编排数据、信号、仓位和风控。当前支持结构校验与保存，AI 执行服务尚未接入。',
  validate: '比较策略与参数，通过留出集和滚动验证，检查样本外表现。',
  packages: '查看已有策略档案。新策略通过图形化规则创建。',
  proof: '验证固定 SMA 策略的执行证明。当前覆盖单资产、只做多回测，不覆盖 TEE 与 AI 推理。',
  sdk: '查看策略契约、格式说明与 Python 示例，了解已有开发协议。',
}

export function StrategyLabWorkspace({ initialTab = 'workflow', ...researchProps }: Props) {
  const [module, setModule] = useState<'visual' | 'code'>('visual')
  const [codeVisited, setCodeVisited] = useState(false)
  const [tab, setTab] = useState<StrategyLabTab>(initialTab)
  const [researchVisited, setResearchVisited] = useState(initialTab === 'builder' || initialTab === 'validate')
  const [studioVisited, setStudioVisited] = useState(isStudioTab(initialTab))
  const [projects, setProjects] = useState<StrategyProject[]>([])
  const [projectId, setProjectId] = useState('')
  const [pendingProjectRequests, setPendingProjectRequests] = useState(0)
  const projectBusy = pendingProjectRequests > 0
  const projectSelection = useRef(0)
  const project = projects.find((item) => item.id === projectId) ?? null
  const reportError = researchProps.onError

  useEffect(() => {
    let active = true
    api.listStrategyProjects().then((items) => {
      if (!active) return
      setProjects(items)
      setProjectId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id ?? ''))
    }).catch((reason) => { if (active) reportError(reason instanceof Error ? reason.message : '策略项目加载失败') })
    return () => { active = false }
  }, [reportError])

  const chooseTab = (next: StrategyLabTab) => {
    setTab(next)
    if (isStudioTab(next)) setStudioVisited(true)
    else if (next === 'builder' || next === 'validate') setResearchVisited(true)
  }
  const acceptStudioTab = (next: StudioTab) => chooseTab(next === 'workflow' ? 'workflow' : next)
  const acceptProject = (next: StrategyProject) => {
    // A completed request updates its originating project without changing selection.
    setProjects((current) => {
      const existing = current.find((item) => item.id === next.id)
      if (existing && existing.revision > next.revision) return current
      return existing ? current.map((item) => item.id === next.id ? next : item) : [next, ...current]
    })
  }
  const selectProject = (id: string) => {
    projectSelection.current += 1
    setProjectId(id)
  }
  const createProject = async (payload: StrategyProjectCreate) => {
    const selection = projectSelection.current
    setPendingProjectRequests((current) => current + 1)
    try {
      const created = await api.createStrategyProject(payload)
      acceptProject(created)
      if (selection === projectSelection.current) selectProject(created.id)
    }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目创建失败'); throw reason }
    finally { setPendingProjectRequests((current) => current - 1) }
  }
  const updateProject = async (payload: Partial<StrategyProjectCreate>) => {
    if (!project) return
    setPendingProjectRequests((current) => current + 1)
    try { acceptProject(await api.updateStrategyProject(project.id, project.revision, payload)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目更新失败'); throw reason }
    finally { setPendingProjectRequests((current) => current - 1) }
  }
  const linkArtifact = async (kind: StrategyProjectArtifactKind, artifactId: string, developerToken?: string) => {
    if (!project) { researchProps.onError('先创建或选择策略项目，才能归档开发制品'); return }
    setPendingProjectRequests((current) => current + 1)
    try { acceptProject(await api.linkStrategyProjectArtifact(project.id, project.revision, kind, artifactId, developerToken)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '制品绑定失败') }
    finally { setPendingProjectRequests((current) => current - 1) }
  }
  const freezeProject = async (version: string) => {
    if (!project) return
    setPendingProjectRequests((current) => current + 1)
    try { acceptProject(await api.freezeStrategyProject(project.id, project.revision, version)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '版本冻结失败'); throw reason }
    finally { setPendingProjectRequests((current) => current - 1) }
  }

  return <div className="strategy-lab-modules">
    <nav className="lab-module-switch" aria-label="策略开发方式"><button className={module === 'visual' ? 'is-active' : ''} aria-pressed={module === 'visual'} onClick={() => setModule('visual')}><GitBranch size={16} /><span>图形化策略</span><small>规则与 AI 积木</small></button><button className={module === 'code' ? 'is-active' : ''} aria-pressed={module === 'code'} onClick={() => { setModule('code'); setCodeVisited(true) }}><Code2 size={16} /><span>代码策略</span><small>多语言与 AI 助手</small></button></nav>
    <div className="lab-module-content" hidden={module !== 'visual'} inert={module !== 'visual'}><main className="strategy-lab" data-view={tab}>
    <StrategyProjectBar projects={projects} project={project} asset={researchProps.asset} interval={researchProps.interval} busy={projectBusy} onSelect={selectProject} onCreate={createProject} onUpdate={updateProject} onFreeze={freezeProject} onGoTab={chooseTab} />
    <header className="strategy-lab-header">
      <nav aria-label="策略生命周期">{tabs.filter((item) => !['packages', 'proof', 'sdk'].includes(item.id)).map((item) => { const Icon = item.icon; const complete = tabComplete(item.id, project); return <button key={item.id} aria-current={tab === item.id ? 'step' : undefined} className={`${tab === item.id ? 'is-active' : ''} ${complete ? 'is-complete' : ''}`} onClick={() => chooseTab(item.id)}><span className="strategy-step-icon">{complete ? <Check size={12} /> : <Icon size={13} />}</span><span><small>{item.stage}</small><strong>{item.label}</strong></span></button> })}<details className="lab-tools"><summary>更多工具</summary><div>{tabs.filter((item) => ['packages', 'proof', 'sdk'].includes(item.id)).map((item) => <button key={item.id} onClick={() => chooseTab(item.id)}>{item.label}</button>)}</div></details></nav>
      <div className="strategy-lab-progress" aria-label={project ? `项目完成度 ${Math.round(project.completion * 100)}%` : '尚未创建项目'}>
        <span><ShieldCheck size={14} /><strong>{project ? `${Math.round(project.completion * 100)}%` : '沙盒'}</strong></span>
        <div><i style={{ width: `${project ? project.completion * 100 : 0}%` }} /></div>
        <small>{(project?.next_gate ? `待完成：${project.next_gate.label}` : null) ?? (project ? '发布门禁已完成' : '创建项目后归档版本')}</small>
      </div>
    </header>

    {tab === 'overview' ? <section className="lab-overview">
      <div className="lab-overview-heading"><div><h1>把想法变成可检验的策略。</h1><p>{descriptions.overview}</p></div><button className="primary-action" onClick={() => chooseTab(project?.strategy_hash ? 'validate' : 'workflow')}>{project?.strategy_hash ? '继续研究验证' : '开始构建策略'}<ArrowRight size={16} /></button></div>
      <div className="lab-overview-grid"><div>
        <div className="section-label"><h2>选择你的起点</h2><span>无需代码，从交易逻辑开始</span></div>
        <div className="lab-entry-cards">
          <button onClick={() => chooseTab('builder')}><Braces size={25} /><span className="capability-tag">可回测</span><h3>可视化构建</h3><p>使用价格、均线、动量等指标组合交易规则，无需编写代码。</p><span className="entry-link">打开规则编辑器 <ArrowRight size={15} /></span></button>
          <button onClick={() => chooseTab('workflow')}><GitBranch size={25} /><span className="capability-tag neutral">AI 积木</span><h3>搭建交易流程</h3><p>沿着市场、信号、仓位与风控的顺序，按需加入 AI 建议与审查。</p><span className="entry-link">打开策略画布 <ArrowRight size={15} /></span></button>
        </div>
        <div className="section-label"><h2>研究到发布</h2><span>每一步都有明确的产出</span></div>
        <div className="lab-journey">{tabs.filter((item) => ['workflow', 'builder', 'validate'].includes(item.id)).map((item, index) => <button key={item.id} onClick={() => chooseTab(item.id)}><span className={`journey-number ${tabComplete(item.id, project) ? 'done' : ''}`}>{tabComplete(item.id, project) ? <Check size={16} /> : index + 1}</span><span><strong>{item.label}</strong><small>{descriptions[item.id]}</small></span><ArrowRight size={16} /></button>)}</div>
      </div><aside className="lab-project-summary"><h2>{project?.name ?? '探索工作区'}</h2><p>{project?.thesis ?? '先试用规则编辑器。准备归档研究时，在顶部创建策略项目。'}</p><dl><div><dt>研究标的</dt><dd>{project?.asset_symbol ?? researchProps.asset?.symbol ?? '待选择'}</dd></div><div><dt>时间周期</dt><dd>{project?.interval ?? researchProps.interval}</dd></div><div><dt>已通过门禁</dt><dd>{project ? `${project.gates.filter((gate) => gate.passed).length} / ${project.gates.length}` : '未创建项目'}</dd></div></dl><div className="lab-next-step"><strong>下一步</strong><p>{(project?.next_gate ? `待完成：${project.next_gate.label}` : null) ?? (project ? '查看版本与发布状态' : '在顶部创建项目，将策略与验证结果关联保存。')}</p></div><button onClick={() => chooseTab('sdk')}>查看开发指南 <ArrowRight size={15} /></button><div className="lab-capabilities"><strong>当前能力边界</strong><p>规则可以回测，AI 画布可以编排与保存。AI 执行仍待接入，配置完成不代表验证通过。</p></div></aside></div>
    </section> : tab === 'workflow' ? null : <div className="lab-stage-context"><div><strong>{tabs.find((item) => item.id === tab)?.label}</strong><p>{descriptions[tab]}</p></div><button onClick={() => chooseTab('overview')}>返回总览</button></div>}

    {researchVisited ? <section className={`strategy-lab-pane ${tab === 'builder' || tab === 'validate' ? 'is-active' : ''}`} aria-hidden={tab !== 'builder' && tab !== 'validate'}>
      <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载研究引擎…</div>}>
        <ResearchWorkspace {...researchProps} view={tab === 'builder' ? 'builder' : 'optimize'} showHeader={false} onStrategySaved={(record: CustomStrategyRecord) => void linkArtifact('strategy', record.id)} onResearchCompleted={(job: ResearchJob) => void linkArtifact('research', job.id)} />
      </Suspense>
    </section> : null}
    {studioVisited ? <section className={`strategy-lab-pane ${isStudioTab(tab) ? 'is-active' : ''}`} aria-hidden={!isStudioTab(tab)}>
      <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载私密策略工作室…</div>}>
        <QuantStrategyStudio onError={researchProps.onError} embedded activeTab={studioTabFor(tab)} onTabChange={acceptStudioTab} onWorkflowSaved={(record: StudioWorkflowRecord, token: string) => void linkArtifact('workflow', record.id, token)} onEditRules={() => chooseTab('builder')} assetSymbol={researchProps.asset?.symbol} assetClass={researchProps.asset?.asset_class} interval={researchProps.interval} />
      </Suspense>
    </section> : null}
  </main></div>
    {codeVisited ? <div className="lab-module-content" hidden={module !== 'code'} inert={module !== 'code'}><Suspense fallback={<div className="chart-loading"><LoaderCircle className="spin" size={20} />加载代码策略编辑器…</div>}><CodeStrategyWorkspace /></Suspense></div> : null}
  </div>
}
