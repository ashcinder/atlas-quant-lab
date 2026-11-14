import { useEffect, useEffectEvent, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Braces, Check, ChevronRight, Download, FileCode2, FileText, Folder, FolderArchive, FolderOpen, LoaderCircle, MoreHorizontal, PanelLeft, PanelRight, Play, Plus, Square, X } from 'lucide-react'
import type { ProjectFilePreview, ProjectReport, PythonProject } from '../compute/pythonProject'
import './python-project.css'

type ImportedProject = PythonProject & { file: File }
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

function preferredEntry(scripts: string[], root: string) {
  const prefix = root ? root + '/' : ''
  return scripts.find(path => path === prefix + 'main.py')
    ?? scripts.find(path => path === prefix + 'backtest.py')
    ?? scripts.find(path => /(^|\/)strategy_[^/]+\.py$/.test(path))
    ?? scripts[0]
}

function ProjectMetrics({ report }: { report: ProjectReport }) {
  return report.summaries.map(({ path, data }) => {
    const result = data.result && typeof data.result === 'object' ? data.result as Record<string, unknown> : data
    const percent = (value: unknown) => typeof value === 'number' ? (value * 100).toFixed(2) + '%' : '—'
    const metrics = [
      ['累计收益', percent(result.return)],
      ['最大回撤', percent(result.max_drawdown)],
      ['期末净值', typeof result.equity === 'number' ? result.equity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'],
      ['已平仓', typeof result.sells === 'number' ? String(result.sells) : '—'],
    ]
    if (metrics.every(([, value]) => value === '—')) return null
    return <section className="python-project-metrics" key={path}>
      <h3>{typeof data.industry === 'string' ? data.industry : '项目报告'}</h3>
      {typeof data.from === 'string' && typeof data.to === 'string' ? <p>{data.from} 至 {data.to}</p> : null}
      <dl>{metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </section>
  })
}

export default function PythonProjectWorkspace({ children, draftToolbar, draftConfiguration, draftFilename, draftDirty, incomingArchive, importDisabled, onOpenArchive }: {
  children: ReactNode
  draftToolbar: ReactNode
  draftConfiguration?: ReactNode
  draftFilename: string
  draftDirty: boolean
  incomingArchive: { file: File } | null
  importDisabled: boolean
  onOpenArchive: () => void
}) {
  const explorerId = useId()
  const operation = useRef<AbortController | null>(null)
  const editor = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLPreElement>(null)
  const [project, setProject] = useState<ImportedProject | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newFiles, setNewFiles] = useState<string[]>([])
  const [active, setActive] = useState('')
  const [entry, setEntry] = useState('')
  const [previews, setPreviews] = useState<Record<string, ProjectFilePreview>>({})
  const [previewError, setPreviewError] = useState<{ path: string; message: string } | null>(null)
  const [previewAttempt, setPreviewAttempt] = useState(0)
  const [outputOpen, setOutputOpen] = useState(false)
  const [view, setView] = useState<'draft' | 'project'>('draft')
  const [archiveError, setArchiveError] = useState('')
  const [tabs, setTabs] = useState<string[]>([])
  const [phase, setPhase] = useState<'import' | 'run' | 'export' | null>(null)
  const [report, setReport] = useState<ProjectReport | null>(null)
  const [runPath, setRunPath] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [explorerOpen, setExplorerOpen] = useState(true)
  const [newFile, setNewFile] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [outputTab, setOutputTab] = useState<'summary' | 'log'>('summary')
  const dirty = Object.keys(edits).length > 0
  const tree = useMemo(() => buildTree([...(project?.files.map(file => file.path) ?? []), ...newFiles], project?.root ?? ''), [project, newFiles])
  const prefix = project?.root ? project.root + '/' : ''
  const source = Object.hasOwn(edits, active) ? edits[active] : project?.sources[active]
  const archive = project?.file
  const preview = Object.hasOwn(previews, active) ? previews[active] : undefined
  const canPreview = !!active && canPreviewProjectFile(active)
  const entryName = entry.split('/').at(-1)
  const activeName = active.split('/').at(-1)
  const relativePath = active.slice(prefix.length)
  const parentPath = relativePath.split('/').slice(0, -1).join(' / ')
  const lineNumbers = useMemo(() => source?.split('\n').map((_, index) => index + 1).join('\n'), [source])

  useEffect(() => () => operation.current?.abort(), [])
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

  function openFile(path: string) {
    setView('project')
    setPreviewError(null)
    setActive(path)
    if (path.endsWith('.py') && path.split('/').at(-1) !== '__init__.py') setEntry(path)
    setTabs(current => current.includes(path) ? current : [...current, path])
    if (editor.current) editor.current.scrollTop = editor.current.scrollLeft = 0
    if (gutter.current) gutter.current.scrollTop = 0
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

  async function perform(next: 'import' | 'run' | 'export', action: (signal: AbortSignal) => Promise<void>) {
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
      const detail = cancelled ? '已停止' : reason instanceof Error ? reason.message : '项目操作失败'
      if (next === 'import') setArchiveError(detail)
      else if (cancelled) setMessage(detail)
      else setError(detail)
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
      const entry = preferredEntry(imported.scripts, imported.root)
      setProject({ ...imported, file })
      setEdits({})
      setNewFiles([])
      setView('project')
      setActive(entry)
      setEntry(entry)
      setPreviews({})
      setPreviewError(null)
      setOutputOpen(false)
      setTabs([entry])
      setReport(null)
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

  function run() {
    if (!project || !entry) return
    void perform('run', async signal => {
      setReport(null)
      setOutputTab('summary')
      setOutputOpen(true)
      setRunPath(entry)
      const { runPythonProject } = await import('../compute/pythonProject')
      const completed = await runPythonProject(project.file, entry, edits, signal)
      setReport(completed)
      setOutputTab(completed.summaries.length ? 'summary' : 'log')
      setMessage(completed.summaries.length ? '回测完成' : '入口脚本运行结束')
    })
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
      setError('请输入项目内的 Python 路径，例如 signals.py 或 lib/signals.py')
      return
    }
    const paths = [...(project?.files.map(file => file.path) ?? []), ...newFiles]
    if (paths.some(other => other === fullPath || other.startsWith(fullPath + '/') || fullPath.startsWith(other + '/'))) {
      setError('文件路径已存在，或与目录冲突')
      return
    }
    setEdits(current => ({ ...current, [fullPath]: '' }))
    setNewFiles(current => [...current, fullPath])
    openFile(fullPath)
    setNewFile(false)
    setNewPath('')
    setError('')
  }

  return <div className={`strategy-code-workspace${explorerOpen ? '' : ' is-explorer-closed'}`}>
    <header className="strategy-draft-header" hidden={view !== 'draft'} aria-label="策略草稿工具栏">
      {draftConfiguration}
      {draftToolbar}
    </header>
    <aside className="project-explorer" aria-label="文件资源管理器">
      <header>
        <strong>文件</strong>
        <button type="button" aria-expanded={explorerOpen} aria-controls={explorerId} title={explorerOpen ? '收起文件树' : '展开文件树'}
          aria-label={explorerOpen ? '收起文件树' : '展开文件树'} onClick={() => setExplorerOpen(value => !value)}><PanelLeft size={16} /></button>
      </header>
      <div id={explorerId} className="project-explorer-body" hidden={!explorerOpen}>
        <div className="project-explorer-actions">
          {phase === 'import'
            ? <button type="button" onClick={() => operation.current?.abort()}><LoaderCircle size={14} className="spin" /> 取消导入</button>
            : <button type="button" disabled={!!phase || importDisabled} onClick={onOpenArchive}><FolderOpen size={15} /> 打开项目 ZIP</button>}
        </div>
        <div className="project-tree-scroll">
          <div className="project-tree-group">草稿</div>
          <button type="button" className="project-file-row project-draft-row" aria-current={view === 'draft' ? 'true' : undefined} onClick={() => setView('draft')}>
            <FileCode2 size={14} /><span>{draftFilename}</span>{draftDirty ? <i aria-label="已修改" /> : null}
          </button>
          {project ? <div className="project-tree-project">
            <div className="project-tree-group">
              <FolderArchive size={14} /><span title={project.file.name}>{project.file.name}</span>
              <button type="button" title="新建 Python 文件" aria-label="新建 Python 文件" disabled={!!phase}
                onClick={() => { setNewFile(true); setNewPath(''); setError('') }}><Plus size={15} /></button>
            </div>
            {newFile ? <form onSubmit={event => { event.preventDefault(); createFile() }}>
              <input aria-label="新建文件路径" autoFocus placeholder="例如 lib/signals.py" value={newPath} onChange={event => setNewPath(event.target.value)} />
              <button type="submit">新建</button><button type="button" aria-label="取消新建" onClick={() => setNewFile(false)}><X size={14} /></button>
              {error && view === 'draft' ? <p role="alert">{error}</p> : null}
            </form> : null}
            {runPath && view === 'draft' && (phase === 'run' || report) ? <div className="project-explorer-actions">
              <button type="button" onClick={() => { openFile(runPath); setOutputOpen(true) }}>{phase === 'run' ? <><LoaderCircle size={14} className="spin" /> 查看正在运行的回测</> : <><Check size={14} /> 查看最近的回测</>}</button>
            </div> : null}
            <FileTree nodes={tree} active={view === 'project' ? active : ''} edits={edits} openFile={openFile} />
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
          <div className="project-file-tabs" aria-label="已打开文件">
            {tabs.map(path => <div key={path} className={active === path ? 'is-active' : ''}>
              <button type="button" aria-pressed={active === path} title={path} onClick={() => openFile(path)}>
                <ProjectFileIcon path={path} /><span>{path.split('/').at(-1)}</span>{Object.hasOwn(edits, path) ? ' •' : ''}
              </button>
              <button type="button" aria-label={`关闭 ${path.slice(prefix.length)}`} onClick={() => closeTab(path)}><X size={13} /></button>
            </div>)}
            {!tabs.length ? <span className="project-no-tabs">项目编辑器</span> : null}
          </div>
          <div className="project-document-actions">
            <button type="button" aria-expanded={outputOpen} aria-controls={`${explorerId}-output`} onClick={() => setOutputOpen(value => !value)}>
              <PanelRight size={15} /><span>回测输出</span>
            </button>
            {phase === 'run' || phase === 'export'
              ? <button type="button" onClick={() => operation.current?.abort()}><Square size={14} /> 停止</button>
              : <button className="project-run" type="button" disabled={!entry || !!phase} onClick={run}
                title={entry ? `运行 ${entry.slice(prefix.length)}（⌘ / Ctrl + Enter）` : '选择 Python 入口脚本'}>
                <Play size={15} /><span>运行 {entryName ?? '回测'}</span>
              </button>}
            <details className="project-actions-menu">
              <summary aria-label="项目操作" title="项目操作"><MoreHorizontal size={17} /></summary>
              <div><button type="button" disabled={!!phase} onClick={event => {
                event.currentTarget.closest('details')?.removeAttribute('open')
                exportProject()
              }}><Download size={15} /> 导出项目 ZIP</button></div>
            </details>
          </div>
        </header>
        <div className={`project-workbench-grid${outputOpen ? ' has-output' : ''}`}>
          <div className="project-code-panel">
            {active ? <div className="project-file-path" title={relativePath}>
              {parentPath ? <><span>{parentPath}</span><ChevronRight size={12} /></> : null}
              <strong>{activeName}</strong>
              {typeof source !== 'string' ? <small>只读</small> : null}
            </div> : null}
            {typeof source === 'string' ? <div className="project-source">
              <pre ref={gutter} aria-hidden="true">{lineNumbers}</pre>
              <textarea key={active} ref={editor} aria-label="项目 Python 源码" value={source} spellCheck={false} wrap="off" readOnly={!!phase}
                onScroll={event => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop }}
                onChange={event => edit(event.target.value)}
                onKeyDown={event => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); run() }
                  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') { event.preventDefault(); exportProject() }
                  if (event.key === 'Tab' && !event.shiftKey && !phase) {
                    event.preventDefault()
                    const { selectionStart, selectionEnd } = event.currentTarget
                    edit(source.slice(0, selectionStart) + '    ' + source.slice(selectionEnd))
                    requestAnimationFrame(() => editor.current?.setSelectionRange(selectionStart + 4, selectionStart + 4))
                  }
                }} />
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
            <footer>{project.files.length + newFiles.length} 个文件{dirty ? ' · 有修改，可导出 ZIP' : ''}</footer>
          </div>
          <aside id={`${explorerId}-output`} className="project-output" aria-label="项目回测结果" hidden={!outputOpen}>
            <header><button type="button" aria-pressed={outputTab === 'summary'} onClick={() => setOutputTab('summary')}>回测结果</button><button type="button" aria-pressed={outputTab === 'log'} onClick={() => setOutputTab('log')}>运行日志</button></header>
            <div className="project-output-scroll">
              {runPath ? <p className="project-output-path" title={runPath}>{runPath.slice(prefix.length)}</p> : null}
              {phase ? <p role="status"><LoaderCircle className="spin" size={14} /> {phase === 'run' ? '正在回测…' : phase === 'import' ? '正在读取项目…' : '正在导出项目…'}</p> : null}
              {message ? <p role="status">{message}</p> : null}
              {error ? <pre className="python-project-error" role="alert">{error}</pre> : null}
              {!phase && !report && !error && !message ? <p>回测使用项目内的行情和参数。运行后，结果与日志会显示在这里。</p> : null}
              {report ? <>
                {outputTab === 'summary' ? <>{report.summaries.length ? <ProjectMetrics report={report} /> : <p>项目未生成摘要。可查看运行日志或下载输出。</p>}
                  {report.warnings.map(warning => <p key={warning}>{warning}</p>)}</> : <pre>{report.log || '没有日志输出。'}</pre>}
                <button className="project-report-download" type="button" onClick={() => downloadFile(report.archive, (runPath.split('/').at(-1) ?? '项目').replace(/\.py$/, '') + '-回测报告.zip')}><Download size={15} /> 下载报告</button>
              </> : null}
            </div>
          </aside>
        </div>
      </section> : null}
    </div>
  </div>
}
