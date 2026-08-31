import { lazy, Suspense, useEffect, useState } from 'react'
import {
  Beaker, Braces, FileArchive, FlaskConical, GitBranch, LoaderCircle,
  PackageCheck, ShieldCheck, Sparkles,
} from 'lucide-react'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'
import type { StudioTab } from './QuantStrategyStudio'
import { api } from '../api'
import type {
  CustomStrategyRecord, ResearchJob, StrategyPackageRecord, StrategyProject,
  StrategyProjectArtifactKind, StrategyProjectCreate, StudioWorkflowRecord,
} from '../types'
import { StrategyProjectBar } from './StrategyProjectBar'

const ResearchWorkspace = lazy(() => import('./ResearchWorkspace').then((module) => ({ default: module.ResearchWorkspace })))
const QuantStrategyStudio = lazy(() => import('./QuantStrategyStudio').then((module) => ({ default: module.QuantStrategyStudio })))

export type StrategyLabTab = 'builder' | 'workflow' | 'validate' | 'packages' | 'proof' | 'sdk'

interface Props extends Omit<ResearchWorkspaceProps, 'view' | 'showHeader'> {
  initialTab?: StrategyLabTab
}

const tabs: Array<{ id: StrategyLabTab; label: string; stage: string; icon: typeof Braces }> = [
  { id: 'builder', label: '规则构建', stage: '01 DRAFT', icon: Braces },
  { id: 'workflow', label: 'AI 工作流', stage: '02 COMPOSE', icon: GitBranch },
  { id: 'validate', label: '研究验证', stage: '03 VALIDATE', icon: FlaskConical },
  { id: 'packages', label: '版本包', stage: '04 VERSION', icon: FileArchive },
  { id: 'proof', label: 'ZKP 证明', stage: '05 PROVE', icon: ShieldCheck },
  { id: 'sdk', label: 'SDK 与格式', stage: 'DEVKIT', icon: Beaker },
]

const studioTabFor = (tab: StrategyLabTab): StudioTab => tab === 'packages' ? 'packages' : tab === 'proof' ? 'proof' : tab === 'sdk' ? 'sdk' : 'workflow'
const isStudioTab = (tab: StrategyLabTab) => tab === 'workflow' || tab === 'packages' || tab === 'proof' || tab === 'sdk'

export function StrategyLabWorkspace({ initialTab = 'validate', ...researchProps }: Props) {
  const [tab, setTab] = useState<StrategyLabTab>(initialTab)
  const [researchVisited, setResearchVisited] = useState(!isStudioTab(initialTab))
  const [studioVisited, setStudioVisited] = useState(isStudioTab(initialTab))
  const [projects, setProjects] = useState<StrategyProject[]>([])
  const [projectId, setProjectId] = useState('')
  const [projectBusy, setProjectBusy] = useState(false)
  const project = projects.find((item) => item.id === projectId) ?? null
  const reportError = researchProps.onError

  useEffect(() => {
    api.listStrategyProjects().then((items) => {
      setProjects(items)
      setProjectId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id ?? ''))
    }).catch((reason) => reportError(reason instanceof Error ? reason.message : '策略项目加载失败'))
  }, [reportError])

  const chooseTab = (next: StrategyLabTab) => {
    setTab(next)
    if (isStudioTab(next)) setStudioVisited(true)
    else setResearchVisited(true)
  }
  const acceptStudioTab = (next: StudioTab) => chooseTab(next === 'workflow' ? 'workflow' : next)
  const acceptProject = (next: StrategyProject) => {
    setProjects((current) => [next, ...current.filter((item) => item.id !== next.id)])
    setProjectId(next.id)
  }
  const createProject = async (payload: StrategyProjectCreate) => {
    setProjectBusy(true)
    try { acceptProject(await api.createStrategyProject(payload)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目创建失败'); throw reason }
    finally { setProjectBusy(false) }
  }
  const updateProject = async (payload: Partial<StrategyProjectCreate>) => {
    if (!project) return
    setProjectBusy(true)
    try { acceptProject(await api.updateStrategyProject(project.id, project.revision, payload)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目更新失败'); throw reason }
    finally { setProjectBusy(false) }
  }
  const linkArtifact = async (kind: StrategyProjectArtifactKind, artifactId: string) => {
    if (!project) { researchProps.onError('先创建或选择策略项目，才能归档开发制品'); return }
    setProjectBusy(true)
    try { acceptProject(await api.linkStrategyProjectArtifact(project.id, project.revision, kind, artifactId)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '制品绑定失败') }
    finally { setProjectBusy(false) }
  }
  const freezeProject = async (version: string) => {
    if (!project) return
    setProjectBusy(true)
    try { acceptProject(await api.freezeStrategyProject(project.id, project.revision, version)) }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '版本冻结失败'); throw reason }
    finally { setProjectBusy(false) }
  }

  return <main className="strategy-lab">
    <StrategyProjectBar projects={projects} project={project} asset={researchProps.asset} interval={researchProps.interval} busy={projectBusy} onSelect={setProjectId} onCreate={createProject} onUpdate={updateProject} onFreeze={freezeProject} onGoTab={chooseTab} />
    <header className="strategy-lab-header">
      <div className="strategy-lab-identity"><span><Sparkles size={16} /></span><div><strong>策略实验室</strong><small>{researchProps.asset?.symbol ?? '未选标的'} · 开发→编排→验证→发布</small></div></div>
      <nav aria-label="策略生命周期">{tabs.map((item) => { const Icon = item.icon; return <button key={item.id} className={tab === item.id ? 'is-active' : ''} onClick={() => chooseTab(item.id)}><Icon size={13} /><span><small>{item.stage}</small><strong>{item.label}</strong></span></button> })}</nav>
      <div className="strategy-lab-promotion"><ShieldCheck size={14} /><span><strong>验证后才能晋级</strong><small>保存版本后可绑定跑分回执</small></span></div>
    </header>

    <div className="strategy-lab-lifecycle" aria-label="当前策略生命周期">
      <span className={tab === 'builder' ? 'is-current' : ''}><i />定义逻辑</span><b />
      <span className={tab === 'workflow' ? 'is-current' : ''}><i />组装 AI 与风控</span><b />
      <span className={tab === 'validate' ? 'is-current' : ''}><i />IS / OOS / Walk-forward</span><b />
      <span className={tab === 'packages' || tab === 'sdk' ? 'is-current' : ''}><i />锁定版本</span><b />
      <span className={tab === 'proof' ? 'is-current' : ''}><PackageCheck size={12} />证明并发布</span>
    </div>

    {researchVisited ? <section className={`strategy-lab-pane ${tab === 'builder' || tab === 'validate' ? 'is-active' : ''}`} aria-hidden={tab !== 'builder' && tab !== 'validate'}>
      <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载研究引擎…</div>}>
        <ResearchWorkspace {...researchProps} view={tab === 'builder' ? 'builder' : 'optimize'} showHeader={false} onStrategySaved={(record: CustomStrategyRecord) => void linkArtifact('strategy', record.id)} onResearchCompleted={(job: ResearchJob) => void linkArtifact('research', job.id)} />
      </Suspense>
    </section> : null}
    {studioVisited ? <section className={`strategy-lab-pane ${isStudioTab(tab) ? 'is-active' : ''}`} aria-hidden={!isStudioTab(tab)}>
      <Suspense fallback={<div className="chart-loading"><LoaderCircle size={20} className="spin" />加载私密策略工作室…</div>}>
        <QuantStrategyStudio onError={researchProps.onError} embedded activeTab={studioTabFor(tab)} onTabChange={acceptStudioTab} onWorkflowSaved={(record: StudioWorkflowRecord) => void linkArtifact('workflow', record.id)} onPackageUploaded={(record: StrategyPackageRecord) => void linkArtifact('package', record.id)} assetSymbol={researchProps.asset?.symbol} assetClass={researchProps.asset?.asset_class} interval={researchProps.interval} />
      </Suspense>
    </section> : null}
  </main>
}
