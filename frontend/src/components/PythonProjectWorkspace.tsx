import { highlightStrategyCode } from './highlightStrategyCode'
import { useDeferredValue, useEffect, useEffectEvent, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ArrowLeft, BarChart3, Bot, Braces, Check, ChevronRight, Download, FileCode2, FileText, Folder, FolderArchive, FolderOpen, LoaderCircle, Maximize2, Minimize2, MoreHorizontal, PanelLeft, PanelRight, Play, Plus, Search, SlidersHorizontal, Square, Terminal, X } from 'lucide-react'
import { preferredEntry } from '../project-entry'
import type { ImportedPythonProject, ProjectFilePreview, ProjectReport } from '../compute/pythonProject'
import './python-project.css'
import { api } from '../api'
import { checkComparisonEngines, comparisonEngines, comparisonError, prepareComparison, runPreparedComparison,
  type ComparisonEngineCheck, type ComparisonMethod, type ComparisonRow, type PreparedComparison } from '../compute/compareBacktests'
import { BacktestComparison } from './BacktestComparison'
import { ProjectComparisonSetup } from './ProjectComparisonSetup'
import { LabConfirmDialog } from './LabConfirmDialog'
import { ProjectReportDetails } from './ProjectReportDetails'
import { StrategyCodeAssistant } from './StrategyCodeAssistant'
import type { LabBacktestSettings } from '../lab-strategy-types'
import type { Asset } from '../types'

const scriptComparisonReason = '此入口使用项目自己的账户和撮合。三框架回测需要入口提供 target(context)，为所选标的返回 0 到 1 的目标仓位。'

type TreeNode = { name: string; path: string; children?: Map<string, TreeNode>; hasCode?: boolean }

function buildTree(paths: string[], root: string) {
  const tree = new Map<string, TreeNode>()
  for (const path of paths) {
    const parts = path.slice(root ? root.length + 1 : 0).split('/')
    let branch = tree
    for (const [index, name] of parts.entries()) {
      const folder = index < parts.length - 1
      const node: TreeNode = branch.get(name) ?? { name, path: folder ? parts.slice(0, index + 1).join('/') : path, children: folder ? new Map() : undefined }
      branch.set(name, node)
      if (node.children) {
        node.hasCode ||= path.endsWith('.py')
        branch = node.children
      }
    }
  }
  return tree
}

function canPreviewProjectFile(path: string) {
  return /(?:\.(?:md|markdown|json|jsonl|csv|tsv|txt|ya?ml|toml|ini|cfg|log|rst|xml|html|sql|sh)|(?:^|\/)(?:README|LICENSE|Dockerfile))$/i.test(path)
}

function ProjectFileIcon({ path, size = 14 }: { path: string; size?: number }) {
  const Icon = path.endsWith('.py') ? FileCode2 : /\.jsonl?$/i.test(path) ? Braces : FileText
  return <Icon size={size} aria-hidden="true" />
}

function FileTree({ nodes, active, edits, openFile, depth = 0 }: {
  nodes: Map<string, TreeNode>; active: string; edits: Record<string, string>; openFile: (path: string) => void; depth?: number
}) {
  const sorted = [...nodes.values()].sort((a, b) => Number(!!b.children) - Number(!!a.children) || a.name.localeCompare(b.name))
  const indent = { '--tree-indent': `${depth * 12}px` } as CSSProperties
  return <ul>{sorted.map(node => <li key={node.path}>
    {node.children ? <details open={node.hasCode}>
      <summary style={indent}><ChevronRight size={12} /><Folder size={14} /><span>{node.name}</span></summary>
      <FileTree nodes={node.children} active={active} edits={edits} openFile={openFile} depth={depth + 1} />
    </details> : <button type="button" style={indent} className="project-file-row" title={node.path}
      aria-current={node.path === active ? 'true' : undefined} onClick={() => openFile(node.path)}>
      <ProjectFileIcon path={node.path} />
      <span>{node.name}</span>{Object.hasOwn(edits, node.path) ? <i aria-label="已修改" /> : null}
    </button>}
  </li>)}</ul>
}

function downloadFile(file: Blob, name: string) {
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function isStrategyEntry(path: string, prefix: string) {
  return path === prefix + 'main.py' || path === prefix + 'backtest.py' || /(?:^|\/)strategy_[^/]+\.py$/.test(path)
}

function entryOption(path: string, prefix: string) {
  const relative = path.slice(prefix.length)
  const separator = relative.lastIndexOf('/')
  return separator < 0 ? relative : relative.slice(separator + 1) + ' · ' + relative.slice(0, separator)
}

export default function PythonProjectWorkspace({ compact = false, comparisonContext, children, draftToolbar, draftConfiguration, typeControl, draftFilename, draftDirty, incomingArchive, importDisabled, onOpenArchive, onBackToLibrary, initialProject, onArchiveImported }: {
  comparisonContext?: { settings: LabBacktestSettings; assets: Asset[]; ownerId: string }
  compact?: boolean
  children: ReactNode
  draftToolbar: ReactNode
  draftConfiguration?: ReactNode
  typeControl?: ReactNode
  draftFilename?: string
  draftDirty: boolean
  incomingArchive: { file: File } | null
  importDisabled: boolean
  onOpenArchive: () => void
  onBackToLibrary?: () => void
  initialProject?: ImportedPythonProject
  onArchiveImported?: (file: File, id?: string) => Promise<string>
}) {
  const explorerId = useId()
  const operation = useRef<AbortController | null>(null)
  const editor = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLPreElement>(null)
  const highlight = useRef<HTMLPreElement>(null)
  const activeTab = useRef<HTMLDivElement>(null)
  const outputScroll = useRef<HTMLDivElement>(null)
  const outputPane = useRef<HTMLElement>(null)
  const [comparisonRows, setComparisonRows] = useState<ComparisonRow[]>([])
  const [comparisonSettings, setComparisonSettings] = useState(comparisonContext?.settings)
  const [comparisonMethod, setComparisonMethod] = useState<ComparisonMethod>('unified')
  const [inspection, setInspection] = useState<{
    file: File; entry: string; edits: Record<string, string>; settings: LabBacktestSettings
    method: ComparisonMethod; owner: string; prepared: PreparedComparison; engines: ComparisonEngineCheck[]
  } | null>(null)
  const [resultContext, setResultContext] = useState<Omit<PreparedComparison, 'request'>>()
  const [project, setProject] = useState<ImportedPythonProject | null>(initialProject ?? null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newFiles, setNewFiles] = useState<string[]>([])
  const [entry, setEntry] = useState(() => initialProject ? preferredEntry(initialProject.scripts, initialProject.root) : '')
  const [active, setActive] = useState(entry)
  const [fileQuery, setFileQuery] = useState('')
  const deferredQuery = useDeferredValue(fileQuery.trim().toLowerCase())
  const [previews, setPreviews] = useState<Record<string, ProjectFilePreview>>({})
  const [previewError, setPreviewError] = useState<{ path: string; message: string } | null>(null)
  const [previewAttempt, setPreviewAttempt] = useState(0)
  const [outputOpen, setOutputOpen] = useState(!!initialProject)
  const [outputExpanded, setOutputExpanded] = useState(false)
  const [view, setView] = useState<'draft' | 'project'>(initialProject ? 'project' : 'draft')
  const [archiveError, setArchiveError] = useState('')
  const [tabs, setTabs] = useState<string[]>(() => entry ? [entry] : [])
  const [phase, setPhase] = useState<'import' | 'check' | 'run' | 'export' | 'save' | null>(null)
  const [report, setReport] = useState<ProjectReport | null>(null)
  const [runPath, setRunPath] = useState('')
  const [runKind, setRunKind] = useState<'script' | 'comparison'>('script')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [explorerOpen, setExplorerOpen] = useState(true)
  const [newFile, setNewFile] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [newFileError, setNewFileError] = useState('')
  const [outputTab, setOutputTab] = useState<'summary' | 'settings' | 'assistant'>('summary')
  const [assistantReplacement, setAssistantReplacement] = useState<{ file: string; source: string } | null>(null)
  const [assistantUndo, setAssistantUndo] = useState<{ file: string; source: string } | null>(null)
  const editorLocked = phase === 'save' || phase === 'import'
  const dirty = Object.keys(edits).length > 0
  const paths = useMemo(() => [...(project?.files.map(file => file.path) ?? []), ...newFiles], [project, newFiles])
  const tree = useMemo(() => buildTree(paths, project?.root ?? ''), [paths, project?.root])
  const scripts = useMemo(() => [...(project?.scripts ?? []), ...newFiles.filter(path => !path.endsWith('/__init__.py') && path !== '__init__.py')], [project, newFiles])
  const prefix = project?.root ? project.root + '/' : ''
  const source = Object.hasOwn(edits, active) ? edits[active] : project?.sources[active]
  const archive = project?.file
  const preview = Object.hasOwn(previews, active) ? previews[active] : undefined
  const canPreview = !!active && canPreviewProjectFile(active)
  const entryGroups = useMemo(() => {
    const preferred: string[] = []
    const other: string[] = []
    for (const path of scripts) {
      if (isStrategyEntry(path, prefix)) preferred.push(path)
      else other.push(path)
    }
    return [{ label: '常用入口', paths: preferred }, { label: '其他 Python 文件', paths: other }]
  }, [scripts, prefix])
  const entrySource = edits[entry] ?? project?.sources[entry]
  const scriptOnly = entrySource !== undefined && !/\btarget\b/.test(entrySource)
    && /^\s*if\s+__name__\s*==\s*['"]__main__['"]\s*:/m.test(entrySource)
    && !/^\s*from\s+[.\w]+\s+import\s+\*/m.test(entrySource)
    && !/\b(?:exec|globals|locals|vars)\s*\(/.test(entrySource)
  const effectiveMethod = comparisonSettings?.data_source === 'huggingface' ? comparisonMethod : 'native'
  const checked = inspection && inspection.file === archive && inspection.entry === entry && inspection.edits === edits
    && inspection.settings === comparisonSettings && inspection.method === effectiveMethod && inspection.owner === comparisonContext?.ownerId ? inspection : null
  const matchedPaths = useMemo(() => deferredQuery ? paths.filter(path => path.slice(prefix.length).toLowerCase().includes(deferredQuery)) : [], [deferredQuery, paths, prefix])
  const runLabel = runKind === 'script' ? '脚本运行' : '引擎对比'
  const activeName = active.split('/').at(-1)
  const relativePath = active.slice(prefix.length)
  const parentPath = relativePath.split('/').slice(0, -1).join(' / ')
  const highlighted = useMemo(() => source === undefined ? null : highlightStrategyCode(source, 'python'), [source])
  const lineNumbers = useMemo(() => source?.split('\n').map((_, index) => index + 1).join('\n'), [source])

  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    activeTab.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [active, view])
  useEffect(() => {
    if (outputScroll.current) outputScroll.current.scrollTop = 0
  }, [outputTab, runPath])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  useEffect(() => {
    if (!archive || !canPreview || preview || view !== 'project') return
    const controller = new AbortController()
    const signal = controller.signal
    void import('../compute/pythonProject').then(({ previewPythonProjectFile }) =>
      previewPythonProjectFile(archive, active, signal),
    ).then(result => {
      if (!signal.aborted) setPreviews(current => Object.fromEntries([...Object.entries(current).slice(-11), [active, result]]))
    }).catch(reason => {
      if (!signal.aborted) setPreviewError({ path: active, message: reason instanceof Error ? reason.message : '文件读取失败' })
    })
    return () => controller.abort()
  }, [archive, active, canPreview, preview, previewAttempt, view])

  const handledArchive = useRef<typeof incomingArchive>(null)
  const [replaceFile, setReplaceFile] = useState<File | null>(null)
  const [leavingProject, setLeavingProject] = useState(false)

  function revealOutput(tab: typeof outputTab) {
    setOutputOpen(true)
    setOutputTab(tab)
    if (tab === 'assistant') setOutputExpanded(false)
    requestAnimationFrame(() => {
      const pane = outputPane.current
      if (pane && pane.getBoundingClientRect().top > window.innerHeight * 0.65) {
        pane.scrollIntoView?.({ block: 'nearest' })
      }
    })
  }

  function openFile(path: string) {
    setView('project')
    setPreviewError(null)
    setActive(path)
    setTabs(current => current.includes(path) ? current : [...current, path])
    if (editor.current) editor.current.scrollTop = editor.current.scrollLeft = 0
    if (gutter.current) gutter.current.scrollTop = 0
    if (highlight.current) highlight.current.scrollTop = highlight.current.scrollLeft = 0
  }

  function closeTab(path: string) {
    const next = tabs.filter(tab => tab !== path)
    setTabs(next)
    if (active === path) {
      const selected = next[Math.min(tabs.indexOf(path), next.length - 1)]
      if (selected) openFile(selected)
      else setActive('')
    }
  }

  async function perform(next: 'import' | 'check' | 'run' | 'export' | 'save', action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setPhase(next)
    setError('')
    setMessage('')
    if (next === 'import') setArchiveError('')
    try {
      await action(controller.signal)
    } catch (reason) {
      const cancelled = reason instanceof Error && reason.name === 'AbortError'
      const detail = cancelled ? '已停止' : comparisonError(reason, '项目操作失败')
      if (next === 'import') setArchiveError(detail)
      else if (cancelled) setMessage(detail)
      else { setError(detail); if (next === 'save') revealOutput('summary') }
    } finally {
      operation.current = null
      setPhase(null)
    }
  }

  function importArchive(file: File) {
    setReplaceFile(null)
    void perform('import', async signal => {
      const { inspectPythonProject } = await import('../compute/pythonProject')
      const imported = await inspectPythonProject(file, signal)
      const libraryId = await onArchiveImported?.(file)
      signal.throwIfAborted()
      const entry = preferredEntry(imported.scripts, imported.root)
      setProject({ ...imported, file, libraryId })
      setEdits({})
      setAssistantUndo(null)
      setNewFiles([])
      setView('project')
      setActive(entry)
      setEntry(entry)
      setPreviews({})
      setPreviewError(null)
      setOutputOpen(true)
      setOutputExpanded(false)
      setComparisonSettings(comparisonContext?.settings)
      setComparisonMethod('unified')
      setInspection(null)
      setResultContext(undefined)
      setFileQuery('')
      setTabs([entry])
      setReport(null)
      setComparisonRows([])
      setRunPath('')
      setNewFile(false)
      setOutputTab('summary')
      setExplorerOpen(true)
    })
  }

  const receiveArchive = useEffectEvent((file: File) => {
    if (operation.current) return
    if (dirty) setReplaceFile(file)
    else importArchive(file)
  })
  useEffect(() => {
    if (!incomingArchive || handledArchive.current === incomingArchive) return
    handledArchive.current = incomingArchive
    receiveArchive(incomingArchive.file)
  }, [incomingArchive])

  function startRun(kind: 'script' | 'comparison') {
    setRunKind(kind)
    setRunPath(entry)
    setReport(null)
    setComparisonRows([])
    setResultContext(undefined)
    revealOutput('summary')
  }

  async function prepareEntry(signal: AbortSignal) {
    if (!project || !comparisonContext || !comparisonSettings?.symbol) throw new Error('请选择回测标的。')
    const settings = comparisonSettings
    const owner = comparisonContext.ownerId
    if (settings.start && settings.end && Date.parse(settings.start) >= Date.parse(settings.end)) {
      throw new Error('结束时间必须晚于开始时间。')
    }
    if (!Number.isFinite(settings.initial_capital) || settings.initial_capital <= 0) throw new Error('初始资金必须大于零。')
    const { prepareProjectPlan } = await import('../compute/pythonProject')
    const payload = {
      ...settings, strategy_name: project.file.name.replace(/\.zip$/i, ''), params: {},
      execution_model: effectiveMethod, adjustment: settings.data_source === 'huggingface' ? 'raw' : 'auto',
    }
    const [prepared, statuses] = await Promise.all([
      prepareComparison(payload, signal, (bars, datasetId, runSignal) => prepareProjectPlan(project.file, entry, edits, bars, datasetId, runSignal)),
      api.backtestEngines(signal).catch(() => undefined),
    ])
    signal.throwIfAborted()
    return { file: project.file, entry, edits, settings, method: effectiveMethod, owner,
      prepared, engines: checkComparisonEngines(payload, statuses) }
  }

  function inspectComparison() {
    if (!project || !entry || !comparisonContext || scriptOnly) return
    void perform('check', async signal => {
      setInspection(null)
      outputScroll.current?.scrollTo?.({ top: 0 })
      setInspection(await prepareEntry(signal))
    })
  }

  function compareProject() {
    if (!project || !entry || !comparisonContext) return
    if (!comparisonSettings?.symbol && !scriptOnly) { revealOutput('settings'); return }
    void perform('run', async signal => {
      startRun('comparison')
      if (scriptOnly) {
        setComparisonRows(comparisonEngines.map(engine => ({ engine, status: 'skipped', error: scriptComparisonReason })))
        return
      }
      setComparisonRows(comparisonEngines.map(engine => ({ engine, status: 'pending' })))
      try {
        const inspected = checked ?? await prepareEntry(signal)
        setInspection(inspected)
        const { barCount, from, to, method, datasetId } = inspected.prepared
        setResultContext({ barCount, from, to, method, datasetId })
        await runPreparedComparison(inspected.prepared, signal, setComparisonRows, inspected.owner, inspected.engines)
      } catch (reason) {
        const detail = comparisonError(reason, '入口准备失败。')
        setComparisonRows(comparisonEngines.map(engine => ({ engine, status: signal.aborted ? 'cancelled' : 'error',
          error: signal.aborted ? undefined : detail })))
        throw reason
      }
    })
  }

  function run() {
    if (!project || !entry) return
    void perform('run', async signal => {
      startRun('script')
      const { runPythonProject } = await import('../compute/pythonProject')
      const completed = await runPythonProject(project.file, entry, edits, signal)
      setReport(completed)
      setMessage(completed.summaries.length ? '回测完成' : '入口脚本运行结束')
    })
  }

  function runPrimary() {
    if (comparisonContext) compareProject()
    else run()
  }

  function applySuggestion(file: string, next: string) {
    if (file !== active || source === undefined || editorLocked) return
    setAssistantUndo({ file, source })
    edit(next)
  }

  function exportProject() {
    if (!project) return
    void perform('export', async signal => {
      const { exportPythonProject } = await import('../compute/pythonProject')
      const archive = dirty ? await exportPythonProject(project.file, edits, signal) : project.file
      downloadFile(archive, project.file.name)
      setMessage('项目 ZIP 已导出')
    })
  }

  function saveProject() {
    if (!project?.libraryId || !onArchiveImported || !dirty) return
    const { libraryId } = project
    void perform('save', async signal => {
      const { savePythonProject } = await import('../compute/pythonProject')
      const saved = await savePythonProject(project.file, edits, signal)
      signal.throwIfAborted()
      await onArchiveImported(saved.file, libraryId)
      setProject({ ...saved, libraryId })
      setNewFiles([])
      setEdits({})
      setMessage('项目已保存')
    })
  }

  function edit(next: string) {
    setEdits(current => {
      if (!Object.hasOwn(project?.sources ?? {}, active) || next !== project?.sources[active]) return { ...current, [active]: next }
      const cleaned = { ...current }
      delete cleaned[active]
      return cleaned
    })
  }

  function createFile() {
    const path = newPath.trim()
    const fullPath = prefix + path
    if (!path.endsWith('.py') || fullPath.length > 500 || path.includes('\0') || path.includes('\\') || path.includes(':') || path.split('/').some(part => ['', '.', '..', '__MACOSX', '__pycache__', '.DS_Store'].includes(part))) {
      setNewFileError('请输入项目内的 Python 路径，例如 signals.py 或 lib/signals.py')
      return
    }
    if (paths.some(other => other === fullPath || other.startsWith(fullPath + '/') || fullPath.startsWith(other + '/'))) {
      setNewFileError('文件路径已存在，或与目录冲突')
      return
    }
    setEdits(current => ({ ...current, [fullPath]: '' }))
    setNewFiles(current => [...current, fullPath])
    setFileQuery('')
    openFile(fullPath)
    setNewFile(false)
    setNewPath('')
  }

  return <div className={`strategy-code-workspace${compact && view === 'draft' ? ' is-embedded' : ''}${explorerOpen ? '' : ' is-explorer-closed'}${view === 'project' ? ' is-project-view' : ''}`}>
    {assistantReplacement ? <LabConfirmDialog title="替换当前代码？"
      description="生成建议后文件已有修改。应用建议会替换当前编辑内容。"
      confirmLabel="替换代码" onCancel={() => setAssistantReplacement(null)}
      onConfirm={() => { applySuggestion(assistantReplacement.file, assistantReplacement.source); setAssistantReplacement(null) }} /> : null}
    {leavingProject ? <LabConfirmDialog title="离开 ZIP 项目？" description="项目有未导出的修改。可以先导出 ZIP，再返回策略库。"
      confirmLabel="离开项目" destructive onCancel={() => setLeavingProject(false)}
      onConfirm={() => { setLeavingProject(false); onBackToLibrary?.() }}
      extraAction={<button type="button" disabled={!!phase} onClick={exportProject}>导出项目 ZIP</button>} /> : null}
    <header className="strategy-draft-header" hidden={view !== 'draft'} aria-label="策略草稿工具栏">
      {typeControl}
      {draftConfiguration}
      {draftToolbar}
    </header>
    <aside className="project-explorer" aria-label="文件资源管理器" hidden={view === 'project' && !explorerOpen}>
      <header>
        <strong>文件</strong>
        {view === 'draft' ? <button type="button" aria-expanded={explorerOpen} aria-controls={explorerId} title={explorerOpen ? '收起文件树' : '展开文件树'}
          aria-label={explorerOpen ? '收起文件树' : '展开文件树'} onClick={() => setExplorerOpen(value => !value)}><PanelLeft size={16} /></button> : null}
      </header>
      <div id={explorerId} className="project-explorer-body" hidden={!explorerOpen}>
        <div className="project-explorer-actions">
          {phase === 'import'
            ? <button type="button" onClick={() => operation.current?.abort()}><LoaderCircle size={14} className="spin" /> 取消导入</button>
            : <button type="button" disabled={!!phase || importDisabled} onClick={onOpenArchive}><FolderOpen size={15} /> 打开项目 ZIP</button>}
          {project ? <label className="project-file-search">
            <Search size={14} aria-hidden="true" />
            <input type="search" aria-label="搜索项目文件" placeholder="搜索文件名或路径" value={fileQuery} onChange={event => setFileQuery(event.target.value)} />
          </label> : null}
        </div>
        <div className="project-tree-scroll">
          {draftFilename ? <>
            <div className="project-tree-group">策略草稿</div>
            <button type="button" className="project-file-row project-draft-row" aria-current={view === 'draft' ? 'true' : undefined} onClick={() => setView('draft')}>
              <FileCode2 size={14} /><span>{draftFilename}</span>{draftDirty ? <i aria-label="已修改" /> : null}
            </button>
          </> : null}
          {project ? <div className="project-tree-project">
            <div className="project-tree-group">
              <FolderArchive size={14} /><span title={project.file.name}>{project.file.name.replace(/\.zip$/i, '')}</span>
              <button type="button" title="新建 Python 文件" aria-label="新建 Python 文件" disabled={!!phase}
                onClick={() => { setNewFile(true); setNewPath(''); setNewFileError('') }}><Plus size={15} /></button>
            </div>
            {newFile ? <form onSubmit={event => { event.preventDefault(); createFile() }}>
              <input aria-label="新建文件路径" autoFocus placeholder="例如 lib/signals.py" value={newPath} onChange={event => setNewPath(event.target.value)} />
              <button type="submit">新建</button><button type="button" aria-label="取消新建" onClick={() => setNewFile(false)}><X size={14} /></button>
              {newFileError ? <p role="alert">{newFileError}</p> : null}
            </form> : null}
            {runPath && view === 'draft' && (phase === 'run' || report || comparisonRows.length > 0) ? <div className="project-explorer-actions">
              <button type="button" onClick={() => { openFile(runPath); revealOutput('summary') }}>{phase === 'run' ? <><LoaderCircle size={14} className="spin" /> 查看正在运行的回测</> : <><Check size={14} /> 查看最近的回测</>}</button>
            </div> : null}
            {deferredQuery ? matchedPaths.length ? <ul className="project-search-results">{matchedPaths.map(path => <li key={path}>
              <button type="button" className="project-file-row" aria-current={view === 'project' && active === path ? 'true' : undefined}
                title={path.slice(prefix.length)} onClick={() => openFile(path)}>
                <ProjectFileIcon path={path} /><span><strong>{path.split('/').at(-1)}</strong><small>{path.slice(prefix.length)}</small></span>
              </button>
            </li>)}</ul> : <p className="project-search-empty">找不到匹配的文件</p>
              : <FileTree nodes={tree} active={view === 'project' ? active : ''} edits={edits} openFile={openFile} />}
          </div> : null}
        </div>
      </div>
    </aside>

    <div className="strategy-workbench-main">
      {phase === 'import' ? <p className="project-workbench-feedback" role="status">正在读取项目 ZIP…</p> : null}
      {archiveError ? <div className="project-workbench-feedback" role="alert">
        <span>{archiveError}</span><button type="button" aria-label="关闭导入提示" onClick={() => setArchiveError('')}><X size={14} /></button>
      </div> : null}
      {replaceFile ? <div className="project-workbench-feedback" role="alert">
        <span>当前项目有修改。请先导出，或确认用新 ZIP 替换。</span>
        <button type="button" onClick={() => setReplaceFile(null)}>取消</button>
        <button type="button" disabled={!!phase} onClick={() => importArchive(replaceFile)}>替换项目</button>
        <button type="button" disabled={!!phase} onClick={exportProject}><Download size={14} /> 导出当前项目</button>
      </div> : null}
      <div className="strategy-draft-view" hidden={view !== 'draft'}>{children}</div>
      {project ? <section className="python-project-workspace" aria-label="Python 项目工作区" hidden={view !== 'project'}>
        <header className="project-document-bar">
          <div className="project-entry-area">
            <button type="button" className="project-icon-button" aria-expanded={explorerOpen} aria-controls={explorerId}
              aria-label={explorerOpen ? '收起文件树' : '展开文件树'} title={explorerOpen ? '收起文件树' : '展开文件树'}
              onClick={() => setExplorerOpen(value => !value)}><PanelLeft size={16} /></button>
            {onBackToLibrary ? <button className="project-icon-button" type="button" disabled={!!phase || importDisabled} aria-label="返回策略库" title="返回策略库"
              onClick={() => dirty ? setLeavingProject(true) : onBackToLibrary()}><ArrowLeft size={16} /></button> : null}
            <label className="project-entry-select">
              <span>运行入口</span>
              <select aria-label="运行入口" title={entry.slice(prefix.length)} value={entry} disabled={!!phase} onChange={event => { setEntry(event.target.value); openFile(event.target.value) }}>
                {entryGroups.filter(group => group.paths.length > 0).map(group => <optgroup key={group.label} label={group.label}>
                  {group.paths.map(path => <option key={path} value={path}>{entryOption(path, prefix)}</option>)}
                </optgroup>)}
              </select>
            </label>
          </div>
          <div className="project-document-actions">
            {typeControl}
            {phase === 'run' || phase === 'export' || phase === 'check' || phase === 'save'
              ? <button className="project-stop" type="button" onClick={() => operation.current?.abort()}><Square size={13} />停止</button>
              : <button className="project-run" type="button" disabled={!entry || !!phase} onClick={runPrimary}
                aria-keyshortcuts="Control+Enter Meta+Enter"><Play size={14} />{comparisonContext ? '运行三框架回测' : '运行项目脚本'}</button>}
            {comparisonContext && comparisonSettings ? <button type="button" disabled={!!phase} onClick={() => revealOutput('settings')}>
              <SlidersHorizontal size={14} /><span>回测设置</span>
            </button> : null}
            <button type="button" disabled={source === undefined} aria-pressed={outputOpen && outputTab === 'assistant'} onClick={() => revealOutput('assistant')}>
              <Bot size={15} /><span>AI 助手</span>
            </button>
            {onArchiveImported && project.libraryId ? <button type="button" disabled={!!phase || !dirty} onClick={saveProject}>
              <Check size={15} />保存项目
            </button> : null}
            <button type="button" className="project-icon-button" aria-expanded={outputOpen} aria-controls={`${explorerId}-output`}
              aria-label={outputOpen ? '隐藏回测输出' : '显示回测输出'} title={outputOpen ? '隐藏回测输出' : '显示回测输出'}
              onClick={() => outputOpen ? setOutputOpen(false) : revealOutput(outputTab)}><PanelRight size={16} /></button>
            <details className="project-actions-menu">
              <summary aria-label="项目操作" title="项目操作"><MoreHorizontal size={17} /></summary>
              <div>
                {comparisonContext ? <button type="button" disabled={!entry || !!phase} onClick={event => {
                  event.currentTarget.closest('details')?.removeAttribute('open')
                  run()
                }}><Play size={15} />运行项目脚本</button> : null}
                <button type="button" disabled={!!phase} onClick={event => {
                event.currentTarget.closest('details')?.removeAttribute('open')
                exportProject()
              }}><Download size={15} /> 导出项目 ZIP</button></div>
            </details>
          </div>
        </header>
        <div className={`project-workbench-grid${outputOpen ? ' has-output' : ''}${outputOpen && outputExpanded ? ' is-output-expanded' : ''}`}>
          <div className="project-code-panel">
            <div className="project-file-tabs" aria-label="已打开文件">
              {tabs.length ? tabs.map(path => <div key={path} ref={active === path ? activeTab : undefined} className={active === path ? 'is-active' : undefined}>
                <button type="button" aria-pressed={active === path} title={path.slice(prefix.length)} onClick={() => openFile(path)}>
                  <ProjectFileIcon path={path} /><span>{path.split('/').at(-1)}</span>{Object.hasOwn(edits, path) ? <span aria-label="已修改">•</span> : null}
                </button>
                <button type="button" aria-label={`关闭 ${path.slice(prefix.length)}`} onClick={() => closeTab(path)}><X size={13} /></button>
              </div>) : <span className="project-no-tabs">从文件列表打开文件</span>}
            </div>
            {active ? <div className="project-file-path" title={relativePath}>
              {parentPath ? <><span>{parentPath}</span><ChevronRight size={12} /></> : null}
              <strong>{activeName}</strong>
              {entry === active ? <small className="project-entry-badge">入口</small>
                : scripts.includes(active) ? <button type="button" className="project-entry-action" disabled={!!phase} onClick={() => setEntry(active)}>设为入口</button>
                  : typeof source !== 'string' ? <small>只读</small> : null}
            </div> : null}
            {typeof source === 'string' ? <div className="project-source">
              <pre ref={gutter} className="project-gutter" aria-hidden="true">{lineNumbers}</pre>
              <div className="project-editor-layer">
              <pre ref={highlight} className="project-highlight" aria-hidden="true">{highlighted}{'\n'}</pre>
              <textarea key={active} ref={editor} aria-label="项目 Python 源码" value={source} spellCheck={false} wrap="off" readOnly={editorLocked}
                onScroll={event => {
                  const { scrollTop, scrollLeft } = event.currentTarget
                  if (gutter.current) gutter.current.scrollTop = scrollTop
                  if (highlight.current) {
                    highlight.current.scrollTop = scrollTop
                    highlight.current.scrollLeft = scrollLeft
                  }
                }}
                onChange={event => edit(event.target.value)}
                onKeyDown={event => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); runPrimary() }
                  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                    event.preventDefault()
                    if (project.libraryId) saveProject()
                    else exportProject()
                  }
                  if (event.key === 'Tab' && !event.shiftKey && !editorLocked) {
                    event.preventDefault()
                    const { selectionStart, selectionEnd } = event.currentTarget
                    edit(source.slice(0, selectionStart) + '    ' + source.slice(selectionEnd))
                    requestAnimationFrame(() => editor.current?.setSelectionRange(selectionStart + 4, selectionStart + 4))
                  }
                }} />
              </div>
            </div> : canPreview ? <div className="project-file-preview" aria-label={`${activeName} 预览`}>
              {preview?.kind === 'text' ? <>
                {preview.truncated ? <p className="project-preview-note">预览前 512 KiB</p> : null}
                <pre tabIndex={0}>{preview.text || '空文件'}</pre>
              </> : <div className="project-editor-empty">
                {previewError?.path === active ? <>
                  <p role="alert">{previewError.message}</p>
                  <button type="button" onClick={() => { setPreviewError(null); setPreviewAttempt(count => count + 1) }}>重新读取</button>
                </> : preview ? <p>{preview.kind === 'encoding' ? '此文件不是 UTF-8 文本。' : '此文件包含二进制数据。'}</p>
                  : <p role="status">正在读取文件…</p>}
              </div>}
            </div> : <div className="project-editor-empty">
              {active ? <><FileText size={27} /><p>{active.endsWith('.py') ? '该文件使用其他编码，可以运行，编辑需要 UTF-8 源码。' : '此文件随项目提供，可导出 ZIP 后在本地打开。'}</p></>
                : <><FileCode2 size={27} /><p>从左侧打开文件。</p></>}
            </div>}
            <footer><span>{paths.length} 个文件</span>
              {assistantUndo?.file === active && !editorLocked ? <button type="button" onClick={() => {
                edit(assistantUndo.source)
                setAssistantUndo(null)
              }}>撤销替换</button> : null}{phase === 'save' ? <span role="status">正在保存项目…</span>
              : dirty ? <span>有未保存的修改</span> : message === '项目已保存' ? <span role="status">项目已保存</span> : null}</footer>
          </div>
          <aside ref={outputPane} id={`${explorerId}-output`} className="project-output" aria-label="项目回测结果" hidden={!outputOpen}>
            <header className="project-output-heading">
              <strong>{outputTab === 'assistant' ? <Bot size={16} /> : <BarChart3 size={16} />}{outputTab === 'assistant' ? '策略工具' : '回测输出'}</strong>
              <div className="project-output-actions">
                <button type="button" className="project-icon-button" aria-pressed={outputExpanded}
                  aria-label={outputExpanded ? '还原回测输出' : '放大回测输出'} title={outputExpanded ? '还原回测输出' : '放大回测输出'}
                  onClick={() => setOutputExpanded(value => !value)}>{outputExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>
                <button type="button" className="project-icon-button" aria-label="关闭回测输出" title="关闭回测输出" onClick={() => setOutputOpen(false)}><X size={16} /></button>
              </div>
            </header>
            <div className="project-output-tabs" aria-label="输出视图">
              <button type="button" aria-pressed={outputTab === 'summary'} onClick={() => setOutputTab('summary')}>结果</button>
              {comparisonContext && comparisonSettings ? <button type="button" aria-pressed={outputTab === 'settings'} onClick={() => setOutputTab('settings')}>回测设置</button> : null}
              <button type="button" aria-pressed={outputTab === 'assistant'} onClick={() => setOutputTab('assistant')}>助手</button>
            </div>
            <div ref={outputScroll} className="project-output-scroll">
              {outputTab === 'assistant' ? source === undefined ? <div className="project-output-empty"><strong>请选择一个可编辑的 Python 文件</strong></div>
                : <StrategyCodeAssistant key={active} code={source} language="python" ownerId={comparisonContext?.ownerId}
                  fileName={activeName} bounded={false} disabled={editorLocked} onClose={() => setOutputTab('summary')}
                  onApply={(next, baseline) => {
                    if (source !== baseline) setAssistantReplacement({ file: active, source: next })
                    else applySuggestion(active, next)
                  }} />
                : outputTab === 'settings' && comparisonContext && comparisonSettings ? <ProjectComparisonSetup
                entry={entry.slice(prefix.length)} scriptOnly={scriptOnly} method={effectiveMethod} busy={!!phase} preparing={phase === 'check'}
                settings={comparisonSettings} assets={comparisonContext.assets} error={error || (message === '已停止' ? message : undefined)}
                checked={checked?.prepared} engines={checked?.engines}
                onMethod={method => { setError(''); setComparisonMethod(method) }}
                onSettings={patch => { setError(''); setComparisonSettings(value => value && ({ ...value, ...patch })) }}
              /> : <>
                {runPath ? <div className="project-run-context">
                  <span>{runLabel}</span>
                  <strong title={runPath.slice(prefix.length)}>{runPath.split('/').at(-1)}</strong>
                </div> : null}
                {phase === 'run' ? <p className="project-run-status" role="status"><LoaderCircle className="spin" size={14} />正在{runKind === 'script' ? '运行脚本' : '回测'}…</p> : null}
                {message && message !== '项目已保存' ? <p className="project-run-status" role="status"><Check size={14} />{message}</p> : null}
                {error ? <pre className="python-project-error" role="alert">{error}</pre> : null}
                <BacktestComparison context={resultContext} rows={comparisonRows} compact />
                {runKind === 'comparison' && scriptOnly && comparisonRows.length > 0 ? <button className="project-report-download"
                  type="button" disabled={!!phase} onClick={run}><Play size={14} />运行项目脚本</button> : null}
                  {report ? <>
                    {report.summaries.length ? <ProjectReportDetails report={report} /> : <p>脚本已结束。可以下载报告查看项目输出。</p>}
                  </> : null}
                {!runPath && !phase && !error && !message ? <div className="project-output-empty">
                  <Terminal size={22} aria-hidden="true" />
                  <strong>{comparisonContext && scriptOnly ? '项目组合回测' : '等待运行'}</strong>
                  <p>{comparisonContext && scriptOnly ? '此入口有自己的组合回测，三框架需要可对比的仓位信号。'
                    : comparisonContext ? '选择入口和回测设置，查看三个框架各自的结果。' : '选择入口，运行项目脚本以查看输出。'}</p>
                  {comparisonContext && scriptOnly ? <button type="button" className="project-report-download" onClick={run}><Play size={14} />运行项目脚本</button> : null}
                </div> : null}
              </>}
            </div>
            {outputTab === 'settings' ? <footer className="project-output-footer">
              {scriptOnly ? <div className="project-comparison-commands">
                  <button type="button" disabled={!!phase || !entry} onClick={compareProject}>查看框架可用性</button>
                  <button type="button" className="project-run" disabled={!!phase || !entry} onClick={run}><Play size={14} />运行项目脚本</button>
                </div>
                : <div className="project-comparison-commands">
                  <button type="button" disabled={!!phase || !entry || !comparisonSettings?.symbol} onClick={inspectComparison}>{checked ? '重新检查' : '检查配置'}</button>
                  <button type="button" className="project-run" disabled={!!phase || !entry || !comparisonSettings?.symbol} onClick={compareProject}>
                    <Play size={14} />运行三框架回测
                  </button>
                </div>}
            </footer> : outputTab === 'summary' && report ? <footer className="project-output-footer">
              <button className="project-report-download" type="button" onClick={() => downloadFile(report.archive, (runPath.split('/').at(-1) ?? '项目').replace(/\.py$/, '') + '-回测报告.zip')}><Download size={15} /> 下载报告</button>
            </footer> : null}
          </aside>
        </div>
      </section> : null}
    </div>
  </div>
}
