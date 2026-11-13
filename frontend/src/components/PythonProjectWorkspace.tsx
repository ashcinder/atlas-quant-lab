import { useEffect, useEffectEvent, useMemo, useRef, useState, type CSSProperties } from 'react'
import { ArrowLeft, ChevronRight, Download, FileCode2, FileText, Folder, FolderArchive, LoaderCircle, PanelLeft, Play, Plus, Square, X } from 'lucide-react'
import { exportPythonProject, inspectPythonProject, runPythonProject, type ProjectReport, type PythonProject } from '../compute/pythonProject'
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
      {node.name.endsWith('.py') ? <FileCode2 size={14} /> : <FileText size={14} />}
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

export default function PythonProjectWorkspace({ onBack, incomingArchive }: { onBack: () => void; incomingArchive: { file: File } | null }) {
  const operation = useRef<AbortController | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const editor = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLPreElement>(null)
  const [project, setProject] = useState<ImportedProject | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newFiles, setNewFiles] = useState<string[]>([])
  const [active, setActive] = useState('')
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
  const canRun = project && (project.scripts.includes(active) || (newFiles.includes(active) && !active.endsWith('/__init__.py') && active !== '__init__.py'))
  const lineNumbers = useMemo(() => source?.split('\n').map((_, index) => index + 1).join('\n'), [source])

  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const handledArchive = useRef<typeof incomingArchive>(null)
  const [replaceFile, setReplaceFile] = useState<File | null>(null)
  function chooseArchive() { input.current?.click() }

  function openFile(path: string) {
    setActive(path)
    setTabs(current => current.includes(path) ? current : [...current, path])
    if (editor.current) editor.current.scrollTop = editor.current.scrollLeft = 0
    if (gutter.current) gutter.current.scrollTop = 0
  }

  function closeTab(path: string) {
    const next = tabs.filter(tab => tab !== path)
    setTabs(next)
    if (active === path) setActive(next[Math.min(tabs.indexOf(path), next.length - 1)] ?? '')
  }

  async function perform(next: 'import' | 'run' | 'export', action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setPhase(next)
    setError('')
    setMessage('')
    try {
      await action(controller.signal)
    } catch (reason) {
      if (reason instanceof Error && reason.name === 'AbortError') setMessage('已停止')
      else setError(reason instanceof Error ? reason.message : '项目操作失败')
    } finally {
      operation.current = null
      setPhase(null)
    }
  }

  function importArchive(file: File) {
    setReplaceFile(null)
    void perform('import', async signal => {
      const imported = await inspectPythonProject(file, signal)
      const entry = preferredEntry(imported.scripts, imported.root)
      setProject({ ...imported, file })
      setEdits({})
      setNewFiles([])
      setActive(entry)
      setTabs([entry])
      setReport(null)
      setRunPath('')
      setNewFile(false)
      setOutputTab('summary')
      setExplorerOpen(true)
    })
  }

  const receiveArchive = useEffectEvent((file: File) => {
    if (dirty) setReplaceFile(file)
    else importArchive(file)
  })
  useEffect(() => {
    if (!incomingArchive || handledArchive.current === incomingArchive) return
    handledArchive.current = incomingArchive
    receiveArchive(incomingArchive.file)
  }, [incomingArchive])

  function run() {
    if (!project || !canRun) return
    void perform('run', async signal => {
      setReport(null)
      setOutputTab('summary')
      setRunPath(active)
      const completed = await runPythonProject(project.file, active, edits, signal)
      setReport(completed)
      setOutputTab(completed.summaries.length ? 'summary' : 'log')
      setMessage(completed.summaries.length ? '回测完成' : '入口脚本运行结束')
    })
  }

  function exportProject() {
    if (!project) return
    void perform('export', async signal => {
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

  return <section className="python-project-workspace" aria-label="Python 项目工作区">
    <input ref={input} aria-label="项目 ZIP" type="file" accept=".zip,application/zip" hidden onChange={event => {
      const file = event.currentTarget.files?.[0]
      event.currentTarget.value = ''
      if (file && !phase) {
        if (dirty) setReplaceFile(file)
        else importArchive(file)
      }
    }} />
    <header className="project-workbench-toolbar">
      <button type="button" onClick={onBack} disabled={!!phase}><ArrowLeft size={15} /> 单文件编辑器</button>
      <button type="button" aria-label="切换文件树" aria-pressed={explorerOpen} onClick={() => setExplorerOpen(value => !value)}><PanelLeft size={16} /></button>
      <div className="project-workbench-title"><FolderArchive size={18} /><strong title={project?.file.name}>{project?.file.name ?? 'Python 项目'}</strong></div>
      <button type="button" disabled={!!phase} onClick={chooseArchive}><FolderArchive size={15} /> 打开 ZIP</button>
      {project ? <button type="button" disabled={!!phase} onClick={exportProject}><Download size={15} /> 导出项目</button> : null}
      {phase ? <button type="button" onClick={() => operation.current?.abort()}><Square size={14} /> 停止</button>
        : <button className="project-run" type="button" disabled={!canRun} onClick={run}><Play size={15} /> 运行当前文件</button>}
    </header>
    {replaceFile ? <div className="project-workbench-feedback" role="alert">
      <span>当前项目有修改。请先导出，或确认用新 ZIP 替换。</span>
      <button type="button" onClick={() => setReplaceFile(null)}>取消</button>
      <button type="button" onClick={() => importArchive(replaceFile)}>替换项目</button>
    </div> : null}
    <div className={`project-workbench-grid${explorerOpen ? '' : ' is-explorer-closed'}`}>
      {explorerOpen ? <aside className="project-explorer" aria-label="项目文件">
        <header><strong>文件资源管理器</strong><button type="button" title="新建 Python 文件" aria-label="新建 Python 文件" disabled={!project || !!phase}
          onClick={() => { setNewFile(true); setNewPath(''); setError('') }}><Plus size={16} /></button></header>
        {newFile ? <form onSubmit={event => { event.preventDefault(); createFile() }}>
          <input aria-label="新建文件路径" autoFocus placeholder="例如 lib/signals.py" value={newPath} onChange={event => setNewPath(event.target.value)} />
          <button type="submit">新建</button><button type="button" aria-label="取消新建" onClick={() => setNewFile(false)}><X size={14} /></button>
        </form> : null}
        <div className="project-tree-scroll">
          {project ? <FileTree nodes={tree} active={active} edits={edits} openFile={openFile} /> : <p>打开项目 ZIP 后浏览文件。</p>}
        </div>
      </aside> : null}
      <div className="project-code-panel">
        <div className="project-file-tabs" aria-label="已打开文件">{tabs.map(path => <div key={path} className={active === path ? 'is-active' : ''}>
          <button type="button" aria-pressed={active === path} title={path} onClick={() => openFile(path)}><FileCode2 size={14} />{path.split('/').at(-1)}{Object.hasOwn(edits, path) ? ' •' : ''}</button>
          <button type="button" aria-label={`关闭 ${path.slice(prefix.length)}`} onClick={() => closeTab(path)}><X size={13} /></button>
        </div>)}</div>
        {active ? <div className="project-file-path" title={active}>{active.slice(prefix.length)}</div> : null}
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
        </div> : <div className="project-editor-empty">
          {active ? <><FileText size={27} /><p>{active.endsWith('.py') ? '该文件使用其他编码，可以运行，编辑需要 UTF-8 源码。' : '此文件随项目提供。请选择 Python 文件查看源码。'}</p></>
            : project ? <><FileCode2 size={27} /><p>从左侧打开文件。</p></>
              : <><FolderArchive size={30} /><h2>打开 Python 项目</h2><p>选择包含源码和行情数据的 ZIP。</p><button type="button" disabled={!!phase} onClick={chooseArchive}>选择 ZIP</button></>}
        </div>}
        <footer>{project ? <>{project.files.length + newFiles.length} 个文件{dirty ? ' · 有修改，可导出 ZIP' : ''}</> : 'Python 项目回测'}</footer>
      </div>
      <aside className="project-output" aria-label="项目回测结果">
        <header><button type="button" aria-pressed={outputTab === 'summary'} onClick={() => setOutputTab('summary')}>回测结果</button><button type="button" aria-pressed={outputTab === 'log'} onClick={() => setOutputTab('log')}>运行日志</button></header>
        <div className="project-output-scroll">
          {runPath ? <p className="project-output-path" title={runPath}>{runPath.slice(prefix.length)}</p> : null}
          {phase ? <p role="status"><LoaderCircle className="spin" size={14} /> {phase === 'run' ? '正在回测…' : phase === 'import' ? '正在读取项目…' : '正在导出项目…'}</p> : null}
          {message ? <p role="status">{message}</p> : null}
          {error ? <pre className="python-project-error" role="alert">{error}</pre> : null}
          {!phase && !report && !error && !message ? <p>打开策略脚本，点击「运行当前文件」。回测使用项目内的行情和参数。</p> : null}
          {report ? <>
            {outputTab === 'summary' ? <>{report.summaries.length ? <ProjectMetrics report={report} /> : <p>项目未生成摘要。可查看运行日志或下载输出。</p>}
              {report.warnings.map(warning => <p key={warning}>{warning}</p>)}</> : <pre>{report.log || '没有日志输出。'}</pre>}
            <button className="project-report-download" type="button" onClick={() => downloadFile(report.archive, (runPath.split('/').at(-1) ?? '项目').replace(/\.py$/, '') + '-回测报告.zip')}><Download size={15} /> 下载报告</button>
          </> : null}
        </div>
      </aside>
    </div>
  </section>
}
