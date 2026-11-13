import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Check, CheckCheck, ChevronDown, Code2, Download, FileCode2, History, LoaderCircle, Play, Save, Send, Square, Upload, WandSparkles, X } from 'lucide-react'
import { request } from '../request'
import { PublishRuntimeStrategy } from './PublishRuntimeStrategy'
import { labOwnerHeaders, type LabDraft } from '../lab-strategy-types'
import type { ReactNode } from 'react'
import { LabConfirmDialog } from './LabConfirmDialog'
import './code-strategy.css'
import { STRATEGY_LANGUAGES, MAX_STRATEGY_SOURCE, STRATEGY_FILE_ACCEPT, readStrategyFile, type StrategyLanguage } from './strategy-languages'
interface Capabilities { configured: boolean; model?: string; message?: string; bounded_authoring?: boolean; conversation_context?: boolean }
interface Suggestion { explanation: string; code: string | null; validation?: Validation }
interface Message { id: number; role: 'user' | 'assistant'; text: string; code?: string | null; baseline?: string; validation?: Validation }
interface Validation {
  valid: boolean
  error: { message: string; line?: number | null; offset?: number | null; kind?: string } | null
  syntax_valid?: boolean
  backtest_compatible?: boolean
  proof_compatible?: boolean
  dry_run?: { passed: boolean; synthetic: boolean; scenarios: number; bars_per_scenario: number } | null
}

function ValidationDetails({ value }: { value: Validation }) {
  const bounded = value.syntax_valid != null
  return <div className={`code-validation ${value.valid ? 'is-valid' : 'is-invalid'}`} role="status">
    <strong>{bounded ? value.valid ? '代码检测通过' : '代码尚未通过平台检测' : value.valid ? '语法检查通过' : '需要修复代码'}</strong>
    {bounded ? <p>语法：{value.syntax_valid ? '通过' : '未通过'} · 回测兼容：{value.backtest_compatible ? '通过' : '未通过'} · 证明兼容：{value.proof_compatible ? '通过' : '未通过'} · 合成试跑：{value.dry_run?.passed ? '通过' : '未通过或未执行'}</p> : null}
    {value.error ? <p>{value.error.line ? `第 ${value.error.line} 行${value.error.offset ? `，第 ${value.error.offset} 列` : ''}：` : ''}{value.error.message}</p> : null}
    <small>{bounded ? value.dry_run?.passed ? '使用合成行情检查执行兼容性；不是历史回测，未生成 Proof。' : '保留当前代码，请按诊断修正；未运行真实行情或生成 Proof。' : '仅静态检查，未运行策略。'}</small>
  </div>
}

type SourceDraft = Pick<LabDraft, 'source' | 'name' | 'language'>

interface Props {
  draft: SourceDraft
  ownerId: string
  onEdit: (patch: Partial<SourceDraft>) => void
  onSave: () => void
  onRun: () => void
  onHistory: () => void
  runFeedback?: ReactNode
  dirty: boolean
  saved: boolean
  saving: boolean
  running: boolean
  children: ReactNode
}

export function CodeStrategyWorkspace({ draft, ownerId, onEdit, onSave, onRun, onHistory, runFeedback, dirty, saved, saving, running, children }: Props) {
  const { source: code, language, name } = draft
  const languageInfo = STRATEGY_LANGUAGES.find((item) => item.id === language)!
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [capabilityError, setCapabilityError] = useState('')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [validation, setValidation] = useState<Validation | null>(null)
  const [pane, setPane] = useState<'code' | 'guide'>('code')
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [pending, setPending] = useState<{ code: string; name?: string; language?: StrategyLanguage; reason: string } | null>(null)
  const [undoCode, setUndoCode] = useState<string | null>(null)
  const [cursor, setCursor] = useState({ line: 1, column: 1 })
  const editor = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLDivElement>(null)
  const highlight = useRef<HTMLPreElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const revision = useRef(0)
  const codeRef = useRef(code)
  const importSequence = useRef(0)
  const messagesEnd = useRef<HTMLDivElement>(null)

  const highlightedCode = useMemo(() => code.split(/(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"""[\s\S]*?"""|'[^'\n]*'|"[^"\n]*"|\b(?:from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)\b|\b\d+(?:\.\d+)?\b)/g).map((token, index) => {
    const kind = (token.startsWith('//') || token.startsWith('/*') || (token.startsWith('#') && ['python', 'r', 'julia'].includes(language))) ? 'comment' : /^['"]/.test(token) ? 'string' : /^(from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)$/.test(token) ? 'keyword' : /^\d/.test(token) ? 'number' : ''
    return <span key={index} className={kind ? `syntax-${kind}` : undefined}>{token}</span>
  }), [code, language])

  const loadCapabilities = () => {
    setCapabilityError('')
    request<Capabilities>('/strategy-code/capabilities').then(setCapabilities).catch(() => setCapabilityError('无法读取 AI 连接状态，请重试。'))
  }
  useEffect(() => { request<Capabilities>('/strategy-code/capabilities').then(setCapabilities).catch(() => setCapabilityError('无法读取 AI 连接状态，请重试。')); return () => { controller.current?.abort(); generation.current += 1; importSequence.current += 1 } }, [])
  useEffect(() => { if (messages.length || busy) messagesEnd.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, busy])

  const edit = (next: string) => {
    if (next.length > MAX_STRATEGY_SOURCE) { setError('代码超过 60,000 字符。'); return }
    revision.current += 1
    codeRef.current = next
    onEdit({ source: next })
    setValidation(null); setNotice('')
  }
  const switchLanguage = (next: StrategyLanguage) => {
    if (next === language) return
    generation.current += 1; controller.current?.abort(); importSequence.current += 1
    revision.current += 1
    onEdit({ language: next })
    setMessages([]); setPrompt(''); setBusy(false); setValidation(null); setUndoCode(null)
    setError(''); setNotice(''); setPending(null)
  }
  const replace = (next: string, nextName?: string, nextLanguage?: StrategyLanguage) => {
    if (nextLanguage) switchLanguage(nextLanguage)
    setUndoCode(codeRef.current)
    edit(next)
    if (nextName) onEdit({ name: nextName })
    setPending(null); setPane('code')
  }
  const importFile = async (file: File) => {
    const sequence = ++importSequence.current
    const baseRevision = revision.current
    try {
      const imported = await readStrategyFile(file)
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
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    setNotice(`已发起 ${languageInfo.extensions[0]} 文件下载。`)
  }
  const check = async () => {
    if (checking || language !== 'python') return
    const snapshot = revision.current
    setChecking(true); setError('')
    try {
      const result = await request<Validation>('/strategy-code/validate', { method: 'POST', headers: labOwnerHeaders(ownerId), body: JSON.stringify({ code, language, ...(capabilities?.bounded_authoring ? { profile: 'bounded' } : {}) }) })
      if (snapshot === revision.current) setValidation(result)
      else setNotice('代码已修改，请重新检查当前版本。')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '检查失败，请重试。') }
    finally { setChecking(false) }
  }
  const send = async () => {
    if (!prompt.trim() || busy || !capabilities?.configured) return
    const current = ++generation.current
    const text = prompt.trim()
    const baseline = codeRef.current
    const history = messages.slice(-6).map(message => {
      const content = message.text + (message.code ? `\n此前建议代码（不代表已应用，当前编辑器代码另行提供）：\n${message.code}` : '')
      return { role: message.role, content: content.length > 4000 ? content.slice(0, 3960) + '\n[历史消息过长，已截断]' : content }
    })
    const structured = capabilities?.bounded_authoring === true && language === 'python' && (!baseline.trim() || /\bdef\s+target_bps\s*\(/.test(baseline))
    const abort = new AbortController(); controller.current = abort
    setMessages((items) => [...items, { id: current * 2, role: 'user', text }])
    setPrompt(''); setBusy(true); setError('')
    try {
      const response = await request<Suggestion>('/strategy-code/assist', { method: 'POST', headers: labOwnerHeaders(ownerId), body: JSON.stringify({ prompt: text, code: baseline, language, ...(structured ? { generation_mode: 'rules' } : {}), ...(capabilities.conversation_context ? { history } : {}) }), signal: abort.signal }, structured ? 120_000 : 90_000)
      if (generation.current !== current) return
      setMessages((items) => [...items, { id: current * 2 + 1, role: 'assistant', text: response.explanation, code: response.code, baseline, validation: response.validation }])
    } catch (reason) {
      if (generation.current === current) { setError(reason instanceof Error ? reason.message : 'AI 请求失败，请重试。'); setPrompt(text) }
    } finally { if (generation.current === current) setBusy(false) }
  }
  const cancel = () => { generation.current += 1; controller.current?.abort(); setBusy(false); setNotice('已停止等待本次生成。') }
  const position = () => {
    const start = editor.current?.selectionStart ?? 0
    const lines = code.slice(0, start).split('\n')
    setCursor({ line: lines.length, column: lines.at(-1)!.length + 1 })
  }

  const canCheck = language === 'python' && !!code.trim()
  return <section className="lab-code-workbench" aria-label="代码策略工作区">
    {pending ? <LabConfirmDialog title="替换当前代码？" description={pending.reason} confirmLabel="替换代码" onCancel={() => setPending(null)} onConfirm={() => replace(pending.code, pending.name, pending.language)} /> : null}
    <header className="lab-code-command">
      <div className="lab-code-title">
        <label>策略名称<input aria-label="代码策略名称" value={name} maxLength={80} onChange={(event) => onEdit({ name: event.target.value })} /></label>
        <label>语言<select aria-label="策略编程语言" value={language} onChange={(event) => switchLanguage(event.target.value as StrategyLanguage)}>{STRATEGY_LANGUAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <span className="lab-save-state">{saving ? '正在保存…' : dirty || !saved ? '未保存' : '已保存'}</span>
      </div>
      <div className="lab-command-actions">
        <button onClick={onHistory} disabled={!saved}><History size={15} />历史回测</button>
        <button onClick={onSave} disabled={saving || !name.trim()}><Save size={15} />保存策略</button>
        <button disabled={checking || !canCheck} onClick={() => void check()}>{checking ? <LoaderCircle size={15} className="spin" /> : <CheckCheck size={15} />}检查代码</button>
        <button className="lab-primary" disabled={running || saving || !saved || !canCheck} title={!saved ? '先保存策略，再运行回测' : undefined} onClick={onRun}><Play size={15} />{running ? '回测中…' : '运行回测'}</button>
      </div>
      {runFeedback}
    </header>
    <div className="lab-code-columns">
      <div className="lab-source-column">
        <div className="lab-source-tools">
          <button onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
          <input ref={fileInput} type="file" accept={STRATEGY_FILE_ACCEPT} hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importFile(file) }} />
          <button onClick={download}><Download size={15} />下载源码</button>
          {language === 'python' ? <PublishRuntimeStrategy ownerId={ownerId} draft={{ name, source_kind: 'python', strategy_id: 'python_bounded', python_source: code }} disabled={running || !code.trim() || code.length > 16_384} /> : null}
        </div>
      <div className="code-editor-panel">
        <div className="code-editor-tabs"><div role="tablist" aria-label="代码编辑视图"><button role="tab" aria-selected={pane === 'code'} onClick={() => setPane('code')}><FileCode2 size={14} />strategy{languageInfo.extensions[0]}</button><button role="tab" aria-selected={pane === 'guide'} onClick={() => setPane('guide')}>编写指南</button></div><div>{undoCode !== null ? <button onClick={() => { const previous = undoCode; setUndoCode(code); edit(previous) }}>撤销替换</button> : null}{!assistantOpen ? <button onClick={() => setAssistantOpen(true)}><Bot size={15} />AI 助手</button> : null}</div></div>
        {pane === 'code' ? <div className="code-editor-surface"><div ref={gutter} className="code-line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}</div><div className="code-text-layer"><pre ref={highlight} aria-hidden="true" className="code-highlight">{highlightedCode}{'\n'}</pre><textarea ref={editor} aria-label={`${languageInfo.label} 策略代码`} value={code} spellCheck={false} autoCapitalize="off" autoComplete="off" wrap="off" onChange={(event) => edit(event.target.value)} onSelect={position} onScroll={(event) => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; if (highlight.current) { highlight.current.scrollTop = event.currentTarget.scrollTop; highlight.current.scrollLeft = event.currentTarget.scrollLeft } }} onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); if (!saving && name.trim()) onSave() }
        }} /></div></div> : <article className="code-writing-guide"><h2>编写指南</h2><p>{languageInfo.environment}</p><p>{language === 'python' ? '用 target_bps(index, close, sma) 返回 0–9500 的整数仓位。5000 表示 50%。检查代码会显示回测兼容性；历史回测与 Proof 分别运行。' : '当前语言支持编辑和下载，检查和回测使用受限 Python。'}</p><p>导入 UTF-8 源码文件（最大 60 KB），点击「保存策略」将源码与回测设置存入当前账号。</p></article>}
        <footer className="code-editor-status"><span>UTF-8</span><span>{languageInfo.label}</span><span>{code.split('\n').length} 行</span><span>行 {cursor.line}，列 {cursor.column}</span><span>{code.length.toLocaleString()} 字符</span></footer>
        {validation ? <ValidationDetails value={validation} /> : null}
      </div>
      {assistantOpen ? <aside className="code-assistant" aria-label="AI 代码助手"><header><span><WandSparkles size={17} /><strong>AI 助手</strong></span><button aria-label="收起 AI 助手" onClick={() => setAssistantOpen(false)}><X size={17} /></button></header>
        <div className="code-ai-status"><i className={capabilities?.configured ? 'is-ready' : ''} /><span>{capabilities?.configured ? `${capabilities.model ?? '模型'} 已配置` : capabilityError || capabilities?.message || (capabilities ? '尚未配置模型' : '正在检查模型连接…')}</span><button onClick={loadCapabilities} aria-label="刷新 AI 连接状态">刷新</button></div>
        <div className="code-conversation" aria-live="polite">{!messages.length ? <div className="code-assistant-intro"><div className="code-assistant-mark"><Bot size={30} /></div><h2>把想法写成策略</h2><p>描述你的交易逻辑，或让我帮你检查当前代码。</p><div className="code-prompt-examples">{['写一个双均线交叉策略', '加入止损与仓位限制', '分析当前策略的风险', '给代码添加中文注释'].map((text) => <button key={text} onClick={() => setPrompt(text)}>{text}<ChevronDown size={12} /></button>)}</div><small>AI 修改先预览，由你决定是否应用。</small></div> : messages.map((message) => <article className={`code-message is-${message.role}`} key={message.id}><strong>{message.role === 'user' ? '你' : 'AI 助手'}</strong><p>{message.text}</p>{message.code ? <div className="code-suggestion"><details><summary><Code2 size={14} />查看建议代码 · {message.code.split('\n').length} 行</summary><pre>{message.code}</pre></details>{message.validation ? <ValidationDetails value={message.validation} /> : null}<button disabled={message.validation?.valid === false} onClick={() => {
            if (message.validation?.valid === false) return
            if (codeRef.current !== message.baseline) setPending({ code: message.code!, reason: '生成建议后代码已有修改。应用建议会替换当前版本，你可以取消以保留编辑。' })
            else replace(message.code!)
          }}><Check size={14} />应用到编辑器</button></div> : null}</article>)}{busy ? <div className="code-ai-thinking"><LoaderCircle size={16} className="spin" />正在根据当前代码生成建议…</div> : null}<div ref={messagesEnd} /></div>
        <form className="code-ai-composer" onSubmit={(event) => { event.preventDefault(); void send() }}><label htmlFor="code-ai-prompt">告诉 AI 你想实现什么</label><textarea id="code-ai-prompt" value={prompt} maxLength={4000} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：用 20 / 60 日均线判断趋势，单次仓位不超过 20%…" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div><small>发送当前代码 · Shift + Enter 换行</small>{busy ? <button type="button" onClick={cancel}><Square size={14} />停止</button> : <button type="submit" disabled={!prompt.trim() || !capabilities?.configured}><Send size={15} />发送</button>}</div>{!capabilities?.configured ? <details className="code-connect-help"><summary>如何连接 AI？</summary><p>打开右上角设置 → AI 服务，选择 DeepSeek 或通义千问，填写模型与 Key，授权后保存并测试连接。也可以在服务端配置本机 Ollama（ATLAS_AI_URL 与 ATLAS_AI_MODEL），启动模型后刷新连接状态。代码助手会发送当前代码和提问；保密策略请使用开发者自己控制的本地模型。</p></details> : null}</form>
      </aside> : null}
        <div className="lab-editor-feedback">
          {error ? <p role="alert">{error}<button onClick={() => setError('')} aria-label="关闭错误"><X size={14} /></button></p> : null}
          {notice ? <p role="status">{notice}</p> : null}
          <p>{language === 'python' ? '受限 Python · 单标的历史回测' : '此语言可编辑和下载，尚未接入检查与回测。'}</p>
        </div>
      </div>
      <div className="lab-backtest-column">{children}</div>
    </div>
  </section>
}
