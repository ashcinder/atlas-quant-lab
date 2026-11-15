import { lazy, Suspense, useEffect, useEffectEvent, useRef, useState } from 'react'
import { api } from '../api'
import type { ImportedPythonProject, ProjectReport } from '../compute/pythonProject'
import { listLabProjects, readLabProject, type LabProjectEntry } from '../lab-project-library'
import type { LabMultiJob, LabStrategy, LabStrategySummary } from '../lab-strategy-types'
import { preferredEntry } from '../project-entry'
import { ProjectReportDetails } from './ProjectReportDetails'

const MultiResult = lazy(() => import('./LabMultiBacktest').then(module => ({ default: module.LabMultiBacktestResult })))

export type SavedLabSelection =
  | { key: string; kind: 'strategy'; record: LabStrategy }
  | { key: string; kind: 'zip'; project: ImportedPythonProject; entry: string; mode: 'script' | 'market'; updatedAt: string }

type SavedLibrary = { owner: string; strategies: LabStrategySummary[]; projects: LabProjectEntry[] }

export function SavedLabStrategyPicker({ ownerId, selected, disabled, onSelect }: {
  ownerId: string; selected: SavedLabSelection | null; disabled: boolean; onSelect: (strategy: SavedLabSelection | null) => void
}) {
  const [entries, setEntries] = useState<SavedLibrary>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const opening = useRef<AbortController | null>(null)
  const library = entries?.owner === ownerId ? entries : undefined
  const refreshSelection = useEffectEvent((updated: SavedLibrary) => {
    if (selected?.kind === 'strategy') {
      const row = updated.strategies.find(item => item.id === selected.record.id)
      if (row && row.revision !== selected.record.revision) void select(selected.key, updated)
    } else if (selected?.kind === 'zip') {
      const row = updated.projects.find(item => `zip:${item.id}` === selected.key)
      if (row && row.updated_at !== selected.updatedAt) void select(selected.key, updated)
    }
  })
  useEffect(() => {
    if (!ownerId) return
    const controller = new AbortController()
    void Promise.allSettled([api.listLabStrategies(ownerId, controller.signal), listLabProjects(ownerId)]).then(([strategies, projects]) => {
      if (controller.signal.aborted) return
      const updated = { owner: ownerId, strategies: strategies.status === 'fulfilled' ? strategies.value : [],
        projects: projects.status === 'fulfilled' ? projects.value : [] }
      setEntries(updated)
      refreshSelection(updated)
      if (strategies.status === 'rejected' || projects.status === 'rejected') setError('部分已保存策略暂时无法读取。')
    })
    return () => { controller.abort(); opening.current?.abort() }
  }, [ownerId])
  if (!ownerId) return null

  async function select(key: string, available = library) {
    opening.current?.abort()
    if (!key) { onSelect(null); return }
    const controller = new AbortController()
    opening.current = controller
    setBusy(true); setError('')
    try {
      const id = key.slice(key.indexOf(':') + 1)
      if (key.startsWith('zip:')) {
        const archive = available?.projects.find(item => item.id === id)
        if (!archive) throw new Error('找不到项目，请返回策略实验室确认。')
        const [file, { inspectPythonProject }] = await Promise.all([readLabProject(ownerId, archive), import('../compute/pythonProject')])
        const inspected = await inspectPythonProject(file, controller.signal)
        controller.signal.throwIfAborted()
        const previous = selected?.kind === 'zip' && selected.key === key ? selected : null
        const entry = previous && inspected.scripts.includes(previous.entry) ? previous.entry : preferredEntry(inspected.scripts, inspected.root) ?? ''
        onSelect({ key, kind: 'zip', project: { ...inspected, file }, entry, mode: previous?.mode ?? 'script', updatedAt: archive.updated_at })
      } else {
        const record = await api.getLabStrategy(ownerId, id, controller.signal)
        controller.signal.throwIfAborted()
        if (record.kind === 'multi_python' && record.settings.engine_id !== 'rqalpha') throw new Error('此历史策略可在策略实验室查看。')
        onSelect({ key, kind: 'strategy', record })
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取策略。')
    } finally {
      if (opening.current === controller) { opening.current = null; setBusy(false) }
    }
  }

  return <div className="form-section market-saved-strategies">
    <label className="field-stack"><span>已保存策略</span>
      <select aria-label="已保存策略" value={selected?.key ?? ''} disabled={!library || busy || disabled} onChange={event => void select(event.target.value)}>
        <option value="">使用策略模板</option>
        {library?.strategies.some(item => item.language === 'python') ? <optgroup label="我的 Python 策略">
          {library.strategies.filter(item => item.language === 'python').map(item => <option key={item.id} value={`strategy:${item.id}`}>{item.name}</option>)}
        </optgroup> : null}
        {library?.projects.length ? <optgroup label="本机 ZIP 项目">
          {library.projects.map(item => <option key={item.id} value={`zip:${item.id}`}>{item.name}</option>)}
        </optgroup> : null}
      </select>
    </label>
    {busy ? <small role="status">正在读取策略…</small> : null}
    {error ? <small role="alert">{error}</small> : null}
  </div>
}

export function ArchiveRunSettings({ selection, disabled, onChange }: {
  selection: Extract<SavedLabSelection, { kind: 'zip' }>; disabled: boolean; onChange: (next: SavedLabSelection) => void
}) {
  const prefix = selection.project.root ? selection.project.root + '/' : ''
  return <section className="trine-code-context">
    <strong>{selection.project.file.name}</strong>
    <label className="field-stack"><span>运行入口</span><select value={selection.entry} disabled={disabled}
      onChange={event => onChange({ ...selection, entry: event.target.value })}>
      {selection.project.scripts.map(path => <option key={path} value={path}>{path.slice(prefix.length)}</option>)}
    </select></label>
    <label className="field-stack"><span>运行方式</span><select value={selection.mode} disabled={disabled}
      onChange={event => onChange({ ...selection, mode: event.target.value as 'script' | 'market' })}>
      <option value="script">使用项目自带的回测</option><option value="market">使用行情页数据（需要 target）</option>
    </select></label>
    {selection.mode === 'script' ? <small>项目脚本使用自己的行情和参数，输出显示在下方回测结果。</small> : <small>入口需要定义 <code>target(context)</code>，由所选引擎执行回测。</small>}
  </section>
}

export function SavedProjectRunResult({ report, job, busy, ownerId, selection }: {
  report: ProjectReport | null; job: LabMultiJob | null; busy: boolean; ownerId: string; selection: SavedLabSelection
}) {
  return <section className="results-panel panel-normal market-project-result" aria-label="已保存策略回测结果">
    <header className="project-output-heading"><strong>已保存策略回测结果</strong>
      {report ? <span><button type="button" onClick={() => {
          const url = URL.createObjectURL(report.archive)
          const a = document.createElement('a'); a.href = url
          a.download = (selection.kind === 'zip' ? selection.entry.split('/').at(-1) : '策略') + '-回测报告.zip'
          a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
        }}>下载报告</button></span> : null}
    </header>
    <div className="project-output-scroll">
      {busy && !job ? <p role="status">正在运行已保存策略…</p> : null}
      {report ? report.summaries.length ? <ProjectReportDetails report={report} /> : <p>脚本已结束，可下载报告查看项目输出。</p> : null}
      {job ? <Suspense fallback={<p role="status">加载组合报告…</p>}><MultiResult job={job} ownerId={ownerId} /></Suspense> : null}
      {!job && !report && !busy ? <p>点击「运行回测」查看结果。</p> : null}
      <p>此运行方式生成项目或组合报告。上链使用平台单标的回测报告，ZKP 使用支持的受限 Python 策略。</p>
    </div>
  </section>
}
