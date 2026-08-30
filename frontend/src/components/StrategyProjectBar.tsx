import { useMemo, useState } from 'react'
import {
  Check, ChevronDown, CircleAlert, FileCheck2, Fingerprint, FlaskConical,
  FolderKanban, GitBranch, LockKeyhole, Pencil, Plus, ShieldCheck, X,
} from 'lucide-react'
import type { Asset, Interval, StrategyProject, StrategyProjectCreate } from '../types'
import type { StrategyLabTab } from './StrategyLabWorkspace'

interface Props {
  projects: StrategyProject[]
  project: StrategyProject | null
  asset: Asset | null
  interval: Interval
  busy: boolean
  onSelect: (id: string) => void
  onCreate: (payload: StrategyProjectCreate) => Promise<void>
  onUpdate: (payload: Partial<StrategyProjectCreate>) => Promise<void>
  onFreeze: (version: string) => Promise<void>
  onGoTab: (tab: StrategyLabTab) => void
}

const stageLabel: Record<StrategyProject['stage'], string> = {
  draft: '草稿', composed: '已编排', validated: '已验证', versioned: '已冻结', published: '已发布',
}
const objectiveLabel: Record<StrategyProject['objective'], string> = {
  sharpe: 'Sharpe', calmar: 'Calmar', cagr: 'CAGR', total_return: '总收益',
}

function gateTab(id: string): StrategyLabTab {
  if (id === 'strategy' || id === 'thesis') return 'builder'
  if (id === 'workflow') return 'workflow'
  if (id === 'version') return 'packages'
  return 'validate'
}

export function StrategyProjectBar({
  projects, project, asset, interval, busy, onSelect, onCreate, onUpdate, onFreeze, onGoTab,
}: Props) {
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'create' | 'edit'>('create')
  const [gateOpen, setGateOpen] = useState(false)
  const [name, setName] = useState('')
  const [thesis, setThesis] = useState('')
  const [benchmark, setBenchmark] = useState('BTC-USD')
  const [objective, setObjective] = useState<StrategyProject['objective']>('sharpe')
  const [version, setVersion] = useState('1.0.0')

  const openEditor = (mode: 'create' | 'edit') => {
    const existing = mode === 'edit' ? project : null
    setEditorMode(mode)
    setName(existing?.name ?? `${asset?.symbol ?? '新标的'} 策略研究`)
    setThesis(existing?.thesis ?? '当市场出现可解释且可重复的信号时，在真实交易成本后取得稳定的风险调整收益。')
    setBenchmark(existing?.benchmark ?? (asset?.asset_class === 'crypto' ? 'BTC-USD' : 'SPY'))
    setObjective(existing?.objective ?? 'sharpe')
    setEditorOpen(true)
  }

  const passed = project?.gates.filter((gate) => gate.passed).length ?? 0
  const readyToFreeze = useMemo(
    () => Boolean(project && project.gates.every((gate) => gate.id === 'version' || gate.passed)),
    [project],
  )

  const submit = async () => {
    if (!name.trim() || thesis.trim().length < 12 || !asset) return
    try {
      if (editorMode === 'edit' && project) await onUpdate({ name: name.trim(), thesis: thesis.trim(), benchmark, objective })
      else await onCreate({
        name: name.trim(), thesis: thesis.trim(), asset_symbol: asset.symbol,
        asset_class: asset.asset_class, interval, benchmark, objective, deployment_mode: 'research',
      })
      setEditorOpen(false)
    } catch { /* The parent reports API details; keep the editor open for correction. */ }
  }

  return <>
    <section className="strategy-project-bar">
      <div className="project-switcher">
        <FolderKanban size={14} />
        <span><small>STRATEGY PROJECT</small><label><select value={project?.id ?? ''} onChange={(event) => onSelect(event.target.value)} disabled={!projects.length}><option value="">尚未创建项目</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><ChevronDown size={11} /></label></span>
        <button title="新建策略项目" onClick={() => openEditor('create')}><Plus size={12} /></button>
        {project ? <button title="编辑项目定义" onClick={() => openEditor('edit')}><Pencil size={12} /></button> : null}
      </div>
      {project ? <>
        <div className="project-thesis"><span className={`project-stage is-${project.stage}`}>{stageLabel[project.stage]} · r{project.revision}</span><strong>{project.thesis}</strong><small>{project.asset_symbol} · {project.interval} · 对标 {project.benchmark} · 目标 {objectiveLabel[project.objective]}</small></div>
        <div className="project-artifacts" aria-label="项目制品状态">
          <span className={project.strategy_hash ? 'is-ready' : ''}><FileCheck2 size={12} /><small>策略</small></span>
          <span className={project.workflow_valid ? 'is-ready' : ''}><GitBranch size={12} /><small>工作流</small></span>
          <span className={project.research_robust ? 'is-ready' : ''}><FlaskConical size={12} /><small>验证</small></span>
          <span className={project.commitment ? 'is-ready' : ''}><Fingerprint size={12} /><small>版本</small></span>
        </div>
        <button className="project-gate-button" onClick={() => setGateOpen((open) => !open)}><ShieldCheck size={14} /><span><strong>{passed}/{project.gates.length} 门禁</strong><small>{project.next_gate?.label ?? '可发布'}</small></span><ChevronDown size={11} /></button>
      </> : <div className="project-empty-line"><CircleAlert size={13} /><span><strong>尚未建立策略项目主线</strong><small>规则、AI 工作流和验证结果不会自动归档到同一版本。</small></span><button onClick={() => openEditor('create')}>创建项目</button></div>}
    </section>

    {gateOpen && project ? <aside className="project-gate-popover">
      <header><span><ShieldCheck size={15} /><strong>版本晋级门禁</strong></span><button onClick={() => setGateOpen(false)}><X size={13} /></button></header>
      <div className="project-gate-progress"><i style={{ width: `${project.completion * 100}%` }} /></div>
      <p>门禁由后端制品与研究记录计算，前端不能手动勾选。</p>
      <ul>{project.gates.map((gate) => <li key={gate.id} className={gate.passed ? 'is-pass' : ''}><span>{gate.passed ? <Check size={12} /> : <CircleAlert size={12} />}<strong>{gate.label}</strong></span>{gate.passed ? <small>PASS</small> : <button onClick={() => { onGoTab(gateTab(gate.id)); setGateOpen(false) }}>去完成</button>}</li>)}</ul>
      <footer>
        <label><span>冻结版本</span><input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0.0" /></label>
        <button disabled={!readyToFreeze || busy || Boolean(project.commitment)} onClick={async () => { try { await onFreeze(version); setGateOpen(false) } catch { /* Keep gate detail open. */ } }}><LockKeyhole size={12} />{project.commitment ? `已冻结 v${project.version}` : '冻结不可变版本'}</button>
      </footer>
      {project.commitment ? <code title={project.commitment}>COMMIT {project.commitment.slice(0, 24)}…</code> : null}
    </aside> : null}

    {editorOpen ? <div className="project-editor-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditorOpen(false) }}>
      <form className="project-editor" onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <header><div><FolderKanban size={16} /><span><strong>{editorMode === 'edit' ? '编辑策略项目' : '创建策略项目'}</strong><small>先写清楚假设，再进入参数与模型。</small></span></div><button type="button" onClick={() => setEditorOpen(false)}><X size={14} /></button></header>
        <label><span>项目名称</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={100} /></label>
        <label><span>可证伪的投资假设<small>{thesis.length}/800 · 至少 12 字</small></span><textarea value={thesis} onChange={(event) => setThesis(event.target.value)} maxLength={800} rows={5} /></label>
        <div><label><span>研究标的</span><input value={editorMode === 'edit' ? (project?.asset_symbol ?? '') : (asset?.symbol ?? '')} disabled /></label><label><span>研究周期</span><input value={editorMode === 'edit' ? (project?.interval ?? interval) : interval} disabled /></label></div>
        <div><label><span>基准</span><input value={benchmark} onChange={(event) => setBenchmark(event.target.value.toUpperCase())} /></label><label><span>主目标</span><select value={objective} onChange={(event) => setObjective(event.target.value as StrategyProject['objective'])}>{Object.entries(objectiveLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
        <footer><button type="button" onClick={() => setEditorOpen(false)}>取消</button><button className="is-primary" disabled={busy || (editorMode === 'create' && !asset) || thesis.trim().length < 12}>{busy ? '保存中…' : editorMode === 'edit' ? '保存并递增修订' : '创建项目'}</button></footer>
      </form>
    </div> : null}
  </>
}
