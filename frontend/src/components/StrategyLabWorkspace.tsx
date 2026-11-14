import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { LoaderCircle, Settings2 } from 'lucide-react'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'
import { api } from '../api'
import type { Asset, Interval, StrategyProject, StrategyProjectCreate } from '../types'
import { StrategyProjectBar } from './StrategyProjectBar'
import './code-strategy.css'
import './lab-compact.css'

const CodeStrategyWorkspace = lazy(() => import('./CodeStrategyWorkspace').then(module => ({ default: module.CodeStrategyWorkspace })))

// Kept for callers reading existing project gate metadata. The lab renders code only.
export type StrategyLabTab = 'overview' | 'builder' | 'workflow' | 'validate' | 'packages' | 'proof' | 'sdk'
interface Props extends Omit<ResearchWorkspaceProps, 'view' | 'showHeader'> {
  initialTab?: StrategyLabTab
  onOpenMarket?: () => void
  assets?: Asset[]
  onResearchContextChange?: (asset: Asset, interval: Interval) => void
}

export function StrategyLabWorkspace({ assets = [], onResearchContextChange, ...researchProps }: Props) {
  const [projects, setProjects] = useState<StrategyProject[]>([])
  const [projectId, setProjectId] = useState('')
  const [pendingProjectRequests, setPendingProjectRequests] = useState(0)
  const projectBusy = pendingProjectRequests > 0
  const projectSelection = useRef(0)
  const initialContext=useRef({symbol:researchProps.asset?.symbol,interval:researchProps.interval})
  const project = projects.find((item) => item.id === projectId) ?? null
  const reportError = researchProps.onError

  useEffect(() => {
    let active = true
    api.listStrategyProjects().then((items) => {
      if (!active) return
      setProjects(items)
      setProjectId((current) => items.some((item) => item.id === current) ? current : (items.find(item=>item.asset_symbol===initialContext.current.symbol&&item.interval===initialContext.current.interval)?.id??''))
    }).catch((reason) => { if (active) reportError(reason instanceof Error ? reason.message : '策略项目加载失败') })
    return () => { active = false }
  }, [reportError])

  const acceptProject = (next: StrategyProject) => {
    // A completed request updates its originating project without changing selection.
    setProjects((current) => {
      const existing = current.find((item) => item.id === next.id)
      if (existing && existing.revision > next.revision) return current
      return existing ? current.map((item) => item.id === next.id ? next : item) : [next, ...current]
    })
  }
  const syncProjectContext = (next: StrategyProject) => {
    if (!onResearchContextChange || (researchProps.asset?.symbol === next.asset_symbol && researchProps.asset?.asset_class === next.asset_class && researchProps.interval === next.interval)) return
    const selected = assets.find(item => item.symbol === next.asset_symbol) ?? (researchProps.asset?.symbol === next.asset_symbol ? researchProps.asset : null)
    onResearchContextChange(selected ? { ...selected, asset_class: next.asset_class } : {
      symbol: next.asset_symbol, name: next.asset_symbol, asset_class: next.asset_class,
      exchange: 'UNKNOWN', currency: 'USD', timezone: 'UTC', tags: [],
    }, next.interval)
  }
  const selectProject = (id: string, selected = projects.find(item => item.id === id)) => {
    projectSelection.current += 1
    setProjectId(id)
    if (selected) syncProjectContext(selected)
  }
  const createProject = async (payload: StrategyProjectCreate) => {
    const selection = projectSelection.current
    setPendingProjectRequests((current) => current + 1)
    try {
      const created = await api.createStrategyProject(payload)
      acceptProject(created)
      if (selection === projectSelection.current) selectProject(created.id, created)
    }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目创建失败'); throw reason }
    finally { setPendingProjectRequests((current) => current - 1) }
  }
  const updateProject = async (payload: Partial<StrategyProjectCreate>) => {
    if (!project) return
    const selection = projectSelection.current
    setPendingProjectRequests((current) => current + 1)
    try {
      const updated = await api.updateStrategyProject(project.id, project.revision, payload)
      acceptProject(updated)
      if (selection === projectSelection.current) syncProjectContext(updated)
    }
    catch (reason) { researchProps.onError(reason instanceof Error ? reason.message : '策略项目更新失败'); throw reason }
    finally { setPendingProjectRequests((current) => current - 1) }
  }

  const draftConfiguration = <div className="lab-command-bar" aria-label="草稿配置">
    <div className="lab-code-heading"><Settings2 size={14} /><span>草稿配置</span></div>
    <StrategyProjectBar codeOnly projects={projects} project={project} asset={researchProps.asset} assets={assets}
      interval={researchProps.interval} busy={projectBusy} onSelect={selectProject} onCreate={createProject} onUpdate={updateProject} />
  </div>

  return <div className="strategy-lab-modules">
    <div className="lab-module-content">
      <Suspense fallback={<div className="chart-loading"><LoaderCircle className="spin" size={20} />加载代码策略编辑器…</div>}>
        <CodeStrategyWorkspace research={researchProps} assets={assets} onResearchContextChange={onResearchContextChange}
          draftConfiguration={draftConfiguration} />
      </Suspense>
    </div>
  </div>
}
