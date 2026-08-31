import { useEffect, useMemo, useRef, useState } from 'react'
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
  const [formError, setFormError] = useState('')
  const [freezeArmed, setFreezeArmed] = useState(false)
  const editorRef = useRef<HTMLFormElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const openEditor = (mode: 'create' | 'edit') => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const existing = mode === 'edit' ? project : null
    setEditorMode(mode)
    setName(existing?.name ?? `${asset?.symbol ?? '新标的'} 策略研究`)
    setThesis(existing?.thesis ?? '当市场出现可解释且可重复的信号时，在真实交易成本后取得稳定的风险调整收益。')
    setBenchmark(existing?.benchmark ?? (asset?.asset_class === 'crypto' ? 'BTC-USD' : 'SPY'))
    setObjective(existing?.objective ?? 'sharpe')
    setFormError('')
    setEditorOpen(true)
  }

  useEffect(() => {
    if (!editorOpen && !gateOpen) return undefined
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (editorOpen) setEditorOpen(false)
      else setGateOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [editorOpen, gateOpen])

  useEffect(() => {
    if (!editorOpen) return undefined
    const editor = editorRef.current
    const keepFocusInside = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !editor) return
      const focusable = Array.from(editor.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'))
      const first = focusable[0]
      const last = focusable.at(-1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', keepFocusInside)
    return () => {
      window.removeEventListener('keydown', keepFocusInside)
      returnFocusRef.current?.focus()
    }
  }, [editorOpen])

  const passed = project?.gates.filter((gate) => gate.passed).length ?? 0
  const readyToFreeze = useMemo(
    () => Boolean(project && project.gates.every((gate) => gate.id === 'version' || gate.passed)),
    [project],
  )

  const submit = async () => {
    if (!asset) { setFormError('请先在单标的页面选择研究标的。'); return }
    if (!name.trim()) { setFormError('请输入能够识别这项研究的项目名称。'); return }
    if (thesis.trim().length < 12) { setFormError('投资假设至少需要 12 个字符，并应说明信号、成本和预期结果。'); return }
    setFormError('')
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
        <FolderKanban size={14} aria-hidden="true" />
        <span><small>STRATEGY PROJECT</small><label><select name="strategy-project" autoComplete="off" aria-label="选择策略项目" value={project?.id ?? ''} onChange={(event) => onSelect(event.target.value)} disabled={!projects.length}><option value="">尚未创建项目</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><ChevronDown size={11} aria-hidden="true" /></label></span>
        <button aria-label="新建策略项目" title="新建策略项目" onClick={() => openEditor('create')}><Plus size={12} /></button>
        {project ? <button aria-label="编辑项目定义" title="编辑项目定义" onClick={() => openEditor('edit')}><Pencil size={12} /></button> : null}
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
      </> : <div className="project-empty-line"><CircleAlert size={13} /><span><strong>当前是未归档沙盒</strong><small>可以探索模板；创建项目后，规则、工作流与验证结果才会进入同一审计版本。</small></span><button onClick={() => openEditor('create')}>创建策略项目</button></div>}
    </section>

    {gateOpen && project ? <aside className="project-gate-popover">
      <header><span><ShieldCheck size={15} /><strong>版本晋级门禁</strong></span><button aria-label="关闭版本门禁" onClick={() => setGateOpen(false)}><X size={13} /></button></header>
      <div className="project-gate-progress"><i style={{ width: `${project.completion * 100}%` }} /></div>
      <p>门禁由后端制品与研究记录计算，前端不能手动勾选。</p>
      <ul>{project.gates.map((gate) => <li key={gate.id} className={gate.passed ? 'is-pass' : ''}><span>{gate.passed ? <Check size={12} /> : <CircleAlert size={12} />}<strong>{gate.label}</strong></span>{gate.passed ? <small>PASS</small> : <button onClick={() => { onGoTab(gateTab(gate.id)); setGateOpen(false) }}>去完成</button>}</li>)}</ul>
      <footer>
        <label><span>冻结版本</span><input name="release-version" autoComplete="off" spellCheck={false} value={version} onChange={(event) => { setVersion(event.target.value); setFreezeArmed(false) }} placeholder="例如 1.0.0…" /></label>
        <button className={freezeArmed ? 'is-armed' : ''} disabled={!readyToFreeze || busy || Boolean(project.commitment)} onClick={async () => { if (!freezeArmed) { setFreezeArmed(true); return } try { await onFreeze(version); setGateOpen(false); setFreezeArmed(false) } catch { /* Keep gate detail open. */ } }}><LockKeyhole size={12} />{project.commitment ? `已冻结 v${project.version}` : freezeArmed ? `确认冻结 v${version}` : '冻结不可变版本'}</button>
      </footer>
      {project.commitment ? <code title={project.commitment}>COMMIT {project.commitment.slice(0, 24)}…</code> : null}
    </aside> : null}

    {editorOpen ? <div className="project-editor-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditorOpen(false) }}>
      <form ref={editorRef} className="project-editor" role="dialog" aria-modal="true" aria-labelledby="project-editor-title" onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <header><div><FolderKanban size={16} /><span><strong id="project-editor-title">{editorMode === 'edit' ? '编辑策略项目' : '创建策略项目'}</strong><small>先写清楚假设，再进入参数与模型。</small></span></div><button aria-label="关闭项目编辑器" type="button" onClick={() => setEditorOpen(false)}><X size={14} /></button></header>
        <label><span>项目名称</span><input name="project-name" autoComplete="off" autoFocus value={name} onChange={(event) => { setName(event.target.value); setFormError('') }} maxLength={100} placeholder="例如 BTC 趋势与风险控制…" /></label>
        <label><span>可证伪的投资假设<small>{thesis.length}/800 · 至少 12 字</small></span><textarea name="project-thesis" autoComplete="off" value={thesis} onChange={(event) => { setThesis(event.target.value); setFormError('') }} maxLength={800} rows={5} placeholder="说明信号为何有效、计入哪些成本，以及样本外应达到什么结果…" /></label>
        <div><label><span>研究标的</span><input name="asset-symbol" value={editorMode === 'edit' ? (project?.asset_symbol ?? '') : (asset?.symbol ?? '')} disabled /></label><label><span>研究周期</span><input name="interval" value={editorMode === 'edit' ? (project?.interval ?? interval) : interval} disabled /></label></div>
        <div><label><span>基准</span><input name="benchmark" autoComplete="off" spellCheck={false} value={benchmark} onChange={(event) => setBenchmark(event.target.value.toUpperCase())} /></label><label><span>主目标</span><select name="objective" value={objective} onChange={(event) => setObjective(event.target.value as StrategyProject['objective'])}>{Object.entries(objectiveLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
        {formError ? <p className="project-editor-error" role="alert"><CircleAlert size={13} />{formError}</p> : null}
        <footer><button type="button" onClick={() => setEditorOpen(false)}>取消</button><button className="is-primary" disabled={busy}>{busy ? '保存中…' : editorMode === 'edit' ? '保存并递增修订' : '创建策略项目'}</button></footer>
      </form>
    </div> : null}
  </>
}
