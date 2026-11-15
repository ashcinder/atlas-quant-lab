import { highlightStrategyCode } from './highlightStrategyCode'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, CheckCheck, Download, FileCode2, History, LoaderCircle, Play, Save, SlidersHorizontal, Upload, X } from 'lucide-react'
import { request } from '../request'
import { PublishRuntimeStrategy } from './PublishRuntimeStrategy'
import { labOwnerHeaders, type LabDraft, type LabMultiEngine } from '../lab-strategy-types'
import type { ReactNode } from 'react'
import { StrategyCodeAssistant, ValidationDetails, type Validation } from './StrategyCodeAssistant'
import { LabConfirmDialog } from './LabConfirmDialog'
import './code-strategy.css'
import { STRATEGY_LANGUAGES, MAX_STRATEGY_SOURCE, MAX_BOUNDED_SOURCE, sourceBytes, STRATEGY_FILE_ACCEPT, readStrategyFile, type StrategyLanguage } from './strategy-languages'
type SourceDraft = Pick<LabDraft, 'source' | 'name' | 'language'> & { kind?: LabDraft['kind'] }

interface Props {
  draft: SourceDraft
  ownerId: string
  onEdit: (patch: Partial<SourceDraft>) => void
  onSave: () => void
  onRun: () => void
  onHistory: () => void
  navigation?: ReactNode
  runFeedback?: ReactNode
  runtimeActions?: ReactNode
  runDisabledReason?: string
  packageB64?: string | null
  engineId?: LabMultiEngine
  readOnly?: boolean
  dirty: boolean
  saved: boolean
  saving: boolean
  running: boolean
  children: ReactNode
}

export function RqAlphaCodeWorkspace({ draft, ownerId, onEdit, onSave, onRun, onHistory, navigation, runFeedback, runtimeActions, runDisabledReason, packageB64, engineId = 'atlas_portfolio', readOnly = false, dirty, saved, saving, running, children }: Props) {
  const { source: code, language, name } = draft
  const multi = draft.kind === 'multi_python'
  const rqalpha = multi && engineId === 'rqalpha'
  const languageInfo = STRATEGY_LANGUAGES.find((item) => item.id === language)!
  const [checking, setChecking] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [validation, setValidation] = useState<Validation | null>(null)
  const [pane, setPane] = useState<'code' | 'guide'>('code')
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantVisited, setAssistantVisited] = useState(false)
  const [pending, setPending] = useState<{ code: string; name?: string; language?: StrategyLanguage; reason: string } | null>(null)
  const [undoCode, setUndoCode] = useState<string | null>(null)
  const [cursor, setCursor] = useState({ line: 1, column: 1 })
  const checkController = useRef<AbortController | null>(null)
  const editor = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLDivElement>(null)
  const highlight = useRef<HTMLPreElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const revision = useRef(0)
  const codeRef = useRef(code)
  const importSequence = useRef(0)

  const highlightedCode = useMemo(() => highlightStrategyCode(code, language), [code, language])

  useEffect(() => () => { checkController.current?.abort(); importSequence.current += 1 }, [])

  const edit = (next: string) => {
    if (readOnly) return
    if (sourceBytes(next) > MAX_STRATEGY_SOURCE) { setError('代码超过 60,000 字节。'); return }
    revision.current += 1
    codeRef.current = next
    onEdit({ source: next })
    setValidation(null); setNotice('')
  }
  const switchLanguage = (next: StrategyLanguage) => {
    if (readOnly || next === language) return
    importSequence.current += 1
    revision.current += 1
    onEdit({ language: next })
    setValidation(null); setUndoCode(null)
    setError(''); setNotice(''); setPending(null)
  }
  const replace = (next: string, nextName?: string, nextLanguage?: StrategyLanguage) => {
    if (readOnly) return
    if (nextLanguage) switchLanguage(nextLanguage)
    setUndoCode(codeRef.current)
    edit(next)
    if (nextName) onEdit({ name: nextName })
    setPending(null); setPane('code')
  }
  const importFile = async (file: File) => {
    if (readOnly) return
    const sequence = ++importSequence.current
    const baseRevision = revision.current
    try {
      const imported = await readStrategyFile(file)
      if (multi && imported.language !== 'python') throw new Error('RQAlpha 策略仅支持 Python 源码。')
      if (sequence !== importSequence.current) return
      const payload = { code: imported.source, name: imported.name, language: imported.language, reason: '导入文件会替换当前编辑器中的源码。' }
      setError('')
      if (codeRef.current || revision.current !== baseRevision) setPending(payload)
      else replace(payload.code, payload.name, payload.language)
    } catch (reason) {
      if (sequence === importSequence.current) setError(reason instanceof Error ? reason.message : '无法读取文件')
    }
  }
  const download = () => {
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `${[...name].filter((char) => char.charCodeAt(0) >= 32).join('').replace(/[<>:"/\\|?*]/g, '_').trim() || 'strategy'}${languageInfo.extensions[0]}`
    document.body.append(link)
    link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    setNotice(`已发起 ${languageInfo.extensions[0]} 文件下载。`)
  }
  const check = async () => {
    if (checkController.current || !canCheck) return
    const abort = new AbortController()
    checkController.current = abort
    const snapshot = revision.current
    setChecking(true); setError('')
    try {
      if (portable) {
        const { runPortablePython } = await import('../compute/portablePython')
        const bars = Array.from({ length: 100 }, (_, i) => ({ time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 100000 }))
        await runPortablePython(code, bars, {}, abort.signal)
        if (!abort.signal.aborted && snapshot === revision.current) setValidation({ valid: true, error: null, syntax_valid: true, backtest_compatible: true, proof_compatible: false, dry_run: { passed: true, synthetic: true, scenarios: 1, bars_per_scenario: 100 } })
        return
      }
      const result = await request<Validation>(multi ? '/lab-multi/check' : '/strategy-code/validate', {
        method: 'POST', headers: labOwnerHeaders(ownerId), signal: abort.signal,
        body: JSON.stringify(multi ? { source: code, engine_id: engineId, ...(packageB64 ? { package_b64: packageB64 } : {}) } : { code, language, profile: 'bounded' }),
      })
      if (abort.signal.aborted) return
      if (snapshot === revision.current) setValidation(result)
      else setNotice('代码已修改，请重新检查当前版本。')
    } catch (reason) {
      if (!abort.signal.aborted && snapshot === revision.current) setError(reason instanceof Error ? reason.message : '检查失败，请重试。')
    } finally {
      if (checkController.current === abort) checkController.current = null
      if (!abort.signal.aborted) setChecking(false)
    }
  }
  const position = () => {
    const start = editor.current?.selectionStart ?? 0
    const lines = code.slice(0, start).split('\n')
    setCursor({ line: lines.length, column: lines.at(-1)!.length + 1 })
  }

  const sourceSize = sourceBytes(code)
  const portable = language === 'python' && !multi && /\bdef\s+target\s*\(/.test(code)
  const sourceLimit = multi || portable ? MAX_STRATEGY_SOURCE : MAX_BOUNDED_SOURCE
  const oversize = sourceSize > sourceLimit
  const canCheck = !readOnly && language === 'python' && !!code.trim() && !oversize
  return <section className="lab-code-workbench" aria-label="代码策略工作区">
    {pending ? <LabConfirmDialog title="替换当前代码？" description={pending.reason} confirmLabel="替换代码" onCancel={() => setPending(null)} onConfirm={() => replace(pending.code, pending.name, pending.language)} /> : null}
    {navigation}
    <header className="lab-code-command">
      <div className="lab-code-title">
        <label>策略名称<input aria-label="代码策略名称" readOnly={readOnly} value={name} maxLength={80} onChange={(event) => { if (!readOnly) onEdit({ name: event.target.value }) }} /></label>
        {rqalpha || readOnly ? <span className="lab-language-label">{languageInfo.label}{readOnly ? ' · 历史只读' : ''}</span> : <label>语言<select aria-label="策略编程语言" value={language} onChange={(event) => switchLanguage(event.target.value as StrategyLanguage)}>{STRATEGY_LANGUAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
        <span className="lab-save-state">{saving ? '正在保存…' : dirty || !saved ? '未保存' : '已保存'}</span>
      </div>
      <div className="lab-command-actions">
        {!readOnly ? <>
          <button type="button" aria-pressed={assistantOpen} onClick={() => {
            setAssistantVisited(true)
            setAssistantOpen(open => !open)
          }}><Bot size={15} />AI 助手</button>
          <button type="button" aria-pressed={!assistantOpen} onClick={() => setAssistantOpen(false)}><SlidersHorizontal size={15} />回测设置</button>
        </> : null}
        <button onClick={() => { setAssistantOpen(false); onHistory() }} disabled={!saved}><History size={15} />历史回测</button>
        <button onClick={onSave} disabled={readOnly || saving || !name.trim()}><Save size={15} />保存策略</button>
        <button disabled={checking || !canCheck} onClick={() => void check()}>{checking ? <LoaderCircle size={15} className="spin" /> : <CheckCheck size={15} />}检查代码</button>
        <button className="lab-primary" disabled={running || saving || !saved || !canCheck || !!runDisabledReason} title={!saved ? '先保存策略，再运行回测' : runDisabledReason} onClick={() => { setAssistantOpen(false); onRun() }}><Play size={15} />{running ? '回测中…' : multi ? '运行回测' : '运行三框架回测'}</button>
      </div>
      {runFeedback}
    </header>
    <div className="lab-code-columns">
      <div className="lab-source-column">
        <div className="lab-source-tools">
          <button disabled={readOnly} onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
          <input ref={fileInput} type="file" accept={multi ? ".py" : STRATEGY_FILE_ACCEPT} hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importFile(file) }} />
          <button onClick={download}><Download size={15} />下载源码</button>
          {runtimeActions !== undefined ? runtimeActions : !readOnly && !multi && language === 'python' && !/\bdef\s+target\s*\(/.test(code) ? <PublishRuntimeStrategy ownerId={ownerId} draft={{ name, source_kind: 'python', strategy_id: 'python_bounded', python_source: code }} disabled={running || !canCheck} /> : null}
        </div>
      <div className="code-editor-panel">
        <div className="code-editor-tabs"><div role="tablist" aria-label="代码编辑视图"><button role="tab" aria-selected={pane === 'code'} onClick={() => setPane('code')}><FileCode2 size={14} />strategy{languageInfo.extensions[0]}</button><button role="tab" aria-selected={pane === 'guide'} onClick={() => setPane('guide')}>编写指南</button></div><div>{undoCode !== null ? <button onClick={() => { const previous = undoCode; setUndoCode(code); edit(previous) }}>撤销替换</button> : null}</div></div>
        {pane === 'code' ? <div className="code-editor-surface"><div ref={gutter} className="code-line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}</div><div className="code-text-layer"><pre ref={highlight} aria-hidden="true" className="code-highlight">{highlightedCode}{'\n'}</pre><textarea ref={editor} readOnly={readOnly} aria-label={`${languageInfo.label} 策略代码`} value={code} spellCheck={false} autoCapitalize="off" autoComplete="off" wrap="off" onChange={(event) => edit(event.target.value)} onSelect={position} onScroll={(event) => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; if (highlight.current) { highlight.current.scrollTop = event.currentTarget.scrollTop; highlight.current.scrollLeft = event.currentTarget.scrollLeft } }} onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); if (!readOnly && !saving && name.trim()) onSave() }
        }} /></div></div> : <article className="code-writing-guide"><h2>编写指南</h2><p>{rqalpha ? 'RQAlpha 公开版 · 原生 Python' : multi ? 'A 股多标的 · Trine Python SDK' : languageInfo.environment}</p><p>{rqalpha ? '使用 init(context) 和 handle_bar(context, bar_dict)，通过 order_target_percent 等原生 API 提交订单。context.symbols 为所选股票池的米筐代码（如 600519.XSHG），context.parameters 为已保存的参数字典。检查代码仅做静态语法与入口检查，不运行策略，也不证明回测兼容或计算正确。' : multi ? '策略通过 SDK 读取已收盘行情与共享账户，返回目标仓位或订单意图。请按策略包声明的执行方式编写。' : /\bdef\s+target\s*\(/.test(code) ? '通用入口 target(context) 返回 0–1 的目标仓位，可使用 context.close、context.sma(period)、context.params 与 context.state。initialize(context) 可选。一次生成信号后分别回放三个框架。' : language === 'python' ? '用 target_bps(index, close, sma) 返回 0–9500 的整数仓位。5000 表示 50%。检查代码会显示回测兼容性；历史回测与 Proof 分别运行。' : '此语言支持编辑和下载。'}</p><p>导入 UTF-8 源码文件（最大 60 KB），点击「保存策略」将源码与回测设置存入当前账号。</p></article>}
        <footer className="code-editor-status"><span>UTF-8</span><span>{languageInfo.label}</span><span>{code.split('\n').length} 行</span><span>行 {cursor.line}，列 {cursor.column}</span><span>{sourceSize.toLocaleString()} 字节</span></footer>
        {validation ? <ValidationDetails value={validation} staticOnly={rqalpha} /> : null}
      </div>
        <div className="lab-editor-feedback">
          {error ? <p role="alert">{error}<button onClick={() => setError('')} aria-label="关闭错误"><X size={14} /></button></p> : null}
          {notice ? <p role="status">{notice}</p> : null}
          <p>{rqalpha ? 'RQAlpha Python · 学术非商用 · 历史回测' : multi ? '标准 Python · A 股多标的 · 共享人民币账户' : portable ? '通用 Python · 单标的三框架回测' : language === 'python' ? '受限 Python · 单标的三框架回测' : '此语言可编辑和下载，尚未接入检查与回测。'}</p>
          {language === 'python' && oversize ? <p role="status">源码超过 {sourceLimit.toLocaleString() + ' 字节'}，请缩短后再检查或运行。</p> : null}
        </div>
      </div>
      <div className="lab-backtest-column">
        <div hidden={assistantOpen}>{children}</div>
        {assistantVisited ? <div hidden={!assistantOpen}>
          <StrategyCodeAssistant code={code} language={language} ownerId={ownerId} bounded={!multi}
        disabled={readOnly} onClose={() => setAssistantOpen(false)} onApply={(next, baseline) => {
          if (codeRef.current !== baseline) setPending({ code: next, reason: '生成建议后代码已有修改。应用建议会替换当前版本，你可以取消以保留编辑。' })
          else replace(next)
        }} />
        </div> : null}
      </div>
    </div>
  </section>
}
