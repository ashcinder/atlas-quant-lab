import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Check, CheckCheck, ChevronDown, Code2, Download, FileCode2, LoaderCircle, MessageSquare, Send, ShieldCheck, Square, Upload, WandSparkles, X } from 'lucide-react'
import { request } from '../request'
import { LabConfirmDialog } from './LabConfirmDialog'
import './code-strategy.css'
import { STRATEGY_LANGUAGES, languageForFile, type StrategyLanguage } from './strategy-languages'

const MAX_CODE = 60_000
interface Capabilities { configured: boolean; model?: string; message?: string }
interface Suggestion { explanation: string; code: string | null }
interface Message { id: number; role: 'user' | 'assistant'; text: string; code?: string | null; baseline?: string }
interface Validation { valid: boolean; error: { message: string; line?: number | null; offset?: number | null } | null }

export function CodeStrategyWorkspace() {
  const [code, setCode] = useState<string>(STRATEGY_LANGUAGES[0].template)
  const [language, setLanguage] = useState<StrategyLanguage>('python')
  const languageInfo = STRATEGY_LANGUAGES.find((item) => item.id === language)!
  const drafts = useRef<Partial<Record<StrategyLanguage, { code: string; name: string; dirty: boolean }>>>({})
  const [name, setName] = useState('我的均线策略')
  const [dirty, setDirty] = useState(false)
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
  const [assistantOpen, setAssistantOpen] = useState(true)
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
  useEffect(() => {
    if (!dirty && !Object.entries(drafts.current).some(([id, draft]) => id !== language && draft?.dirty)) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, language])
  useEffect(() => { if (messages.length || busy) messagesEnd.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, busy])

  const edit = (next: string) => {
    if (next.length > MAX_CODE) { setError('代码超过 60,000 字符，请拆分后导入。'); return }
    revision.current += 1; codeRef.current = next
    setCode(next); setDirty(true); setValidation(null); setNotice('')
  }
  const switchLanguage = (next: StrategyLanguage) => {
    if (next === language) return
    drafts.current[language] = { code: codeRef.current, name, dirty }
    const saved = drafts.current[next]
    generation.current += 1; controller.current?.abort(); importSequence.current += 1
    revision.current += 1
    const nextCode = saved?.code ?? STRATEGY_LANGUAGES.find((item) => item.id === next)!.template
    codeRef.current = nextCode; setCode(nextCode); setLanguage(next)
    setName(saved?.name ?? '我的均线策略'); setDirty(saved?.dirty ?? false)
    setMessages([]); setPrompt(''); setBusy(false); setValidation(null); setUndoCode(null)
    setError(''); setNotice(''); setPending(null); setCursor({ line: 1, column: 1 })
    if (editor.current) editor.current.scrollTop = editor.current.scrollLeft = 0
    if (highlight.current) highlight.current.scrollTop = highlight.current.scrollLeft = 0
    if (gutter.current) gutter.current.scrollTop = 0
  }
  const replace = (next: string, nextName?: string, nextLanguage?: StrategyLanguage) => {
    if (nextLanguage && nextLanguage !== language) {
      switchLanguage(nextLanguage)
      setUndoCode(drafts.current[nextLanguage]?.code ?? STRATEGY_LANGUAGES.find((item) => item.id === nextLanguage)!.template)
    } else setUndoCode(codeRef.current)

    edit(next)
    if (nextName) setName(nextName)
    setPending(null); setPane('code')
  }
  const importFile = async (file: File) => {
    const sequence = ++importSequence.current
    const baseRevision = revision.current
    const detected = languageForFile(file.name)
    if (!detected) { setError('不支持此文件扩展名，请导入语言列表中对应的 UTF-8 源码文件。'); return }
    if (file.size > MAX_CODE) { setError('文件不能超过 60 KB。'); return }
    try {
      const bytes = await file.arrayBuffer()
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
      if (sequence !== importSequence.current) return
      if (text.includes('\0')) throw new Error('binary')
      const payload = { code: text, name: file.name.replace(/\.[^.]+$/, ''), language: detected.id, reason: `导入文件将打开 ${detected.label} 编辑器，并替换该语言的当前代码。` }
      setError('')
      if (dirty || drafts.current[detected.id]?.dirty || revision.current !== baseRevision) setPending(payload)
      else replace(payload.code, payload.name, payload.language)
    } catch { if (sequence === importSequence.current) setError('无法读取文件，请使用 UTF-8 文本格式的源码文件。') }
  }
  const download = () => {
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `${[...name].filter((char) => char.charCodeAt(0) >= 32).join('').replace(/[<>:"/\\|?*]/g, '_').trim() || 'strategy'}${languageInfo.extensions[0]}`
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    setDirty(false); setNotice(`已发起 ${languageInfo.extensions[0]} 文件下载。草稿仍保留在当前页面。`)
  }
  const check = async () => {
    if (checking || language !== 'python') return
    const snapshot = revision.current
    setChecking(true); setError('')
    try {
      const result = await request<Validation>('/strategy-code/validate', { method: 'POST', body: JSON.stringify({ code, language }) })
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
    const abort = new AbortController(); controller.current = abort
    setMessages((items) => [...items, { id: current * 2, role: 'user', text }])
    setPrompt(''); setBusy(true); setError('')
    try {
      const response = await request<Suggestion>('/strategy-code/assist', { method: 'POST', body: JSON.stringify({ prompt: text, code: baseline, language }), signal: abort.signal }, 90_000)
      if (generation.current !== current) return
      setMessages((items) => [...items, { id: current * 2 + 1, role: 'assistant', text: response.explanation, code: response.code, baseline }])
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

  return <section className={`code-studio ${assistantOpen ? '' : 'assistant-closed'}`} aria-label="代码策略工作区">
    {pending ? <LabConfirmDialog title="替换当前代码？" description={pending.reason} confirmLabel="替换代码" onCancel={() => setPending(null)} onConfirm={() => replace(pending.code, pending.name, pending.language)} /> : null}
    <header className="code-studio-toolbar">
      <div className="code-language"><Code2 size={17} /><select aria-label="策略编程语言" value={language} onChange={(event) => switchLanguage(event.target.value as StrategyLanguage)}>{STRATEGY_LANGUAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div>
      <input aria-label="代码策略名称" className="code-name" value={name} maxLength={100} onChange={(event) => { setName(event.target.value); setDirty(true) }} />
      <span className="code-draft-state">{dirty ? '未下载的修改' : '页面草稿'}</span>
      <button onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
      <input ref={fileInput} type="file" accept={STRATEGY_LANGUAGES.flatMap((item) => [...item.extensions]).join(',')} hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importFile(file) }} />
      <button onClick={download}><Download size={15} />下载保存</button>
      <button className="code-check" title={language === 'python' ? '静态语法检查' : `${languageInfo.label} 编译检查尚未接入`} disabled={checking || !code.trim() || language !== 'python'} onClick={() => void check()}>{checking ? <LoaderCircle size={15} className="spin" /> : <CheckCheck size={15} />}检查代码</button>
    </header>
    <div className="code-studio-body">
      <div className="code-editor-panel">
        <div className="code-editor-tabs"><div role="tablist" aria-label="代码编辑视图"><button role="tab" aria-selected={pane === 'code'} onClick={() => setPane('code')}><FileCode2 size={14} />strategy{languageInfo.extensions[0]}</button><button role="tab" aria-selected={pane === 'guide'} onClick={() => setPane('guide')}>编写指南</button></div><div>{undoCode !== null ? <button onClick={() => { const previous = undoCode; setUndoCode(code); edit(previous) }}>撤销替换</button> : null}{!assistantOpen ? <button onClick={() => setAssistantOpen(true)}><Bot size={15} />AI 助手</button> : null}</div></div>
        {pane === 'code' ? <div className="code-editor-surface"><div ref={gutter} className="code-line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}</div><div className="code-text-layer"><pre ref={highlight} aria-hidden="true" className="code-highlight">{highlightedCode}{'\n'}</pre><textarea ref={editor} aria-label={`${languageInfo.label} 策略代码`} value={code} spellCheck={false} autoCapitalize="off" autoComplete="off" wrap="off" onChange={(event) => edit(event.target.value)} onSelect={position} onScroll={(event) => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; if (highlight.current) { highlight.current.scrollTop = event.currentTarget.scrollTop; highlight.current.scrollLeft = event.currentTarget.scrollLeft } }} onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); download() }
          if (event.key === 'Tab' && !event.shiftKey) {
            event.preventDefault(); const start = event.currentTarget.selectionStart; const end = event.currentTarget.selectionEnd
            edit(code.slice(0, start) + '    ' + code.slice(end))
            requestAnimationFrame(() => editor.current?.setSelectionRange(start + 4, start + 4))
          }
        }} /></div></div> : <article className="code-writing-guide"><h2>用 {languageInfo.label} 表达你的交易想法</h2><p>{languageInfo.environment}。右侧助手会按所选语言与当前代码生成建议。</p><dl><dt>起步模板</dt><dd>{language === 'python' ? '继承 BaseStrategy，实现 generate_targets(ctx)，用 ctx.history 读取历史并返回 TargetPosition 目标仓位。' : '模板演示 20 周期均线信号。通用语言返回目标仓位；平台语言使用对应平台接口。行情、执行与回测需要在目标环境中接入。'}</dd><dt>导入与保存</dt><dd>支持 UTF-8 {languageInfo.extensions.join(" / ")} 文件，最大 60 KB。导入只读取到编辑器；下载保存到自己的设备。切换语言或模块保留代码草稿，刷新或退出前请下载。</dd><dt>AI 与隐私</dt><dd>发送问题时，当前代码和问题会交给服务端配置的模型。请不要在代码或提问中放入密钥。</dd><dt>检查与执行</dt><dd>Python 支持静态语法检查；其他语言暂未接入编译检查，请下载到对应工具中验证。此编辑器尚未连接隔离回测，不能直接运行实盘。</dd></dl></article>}
        <footer className="code-editor-status"><span>UTF-8</span><span>{languageInfo.label}</span><span>{code.split('\n').length} 行</span><span>行 {cursor.line}，列 {cursor.column}</span><span>{code.length.toLocaleString()} 字符</span></footer>
        {validation ? <div className={`code-validation ${validation.valid ? 'is-valid' : 'is-invalid'}`} role="status"><strong>{validation.valid ? '语法检查通过' : '需要修复代码'}</strong>{validation.error ? <p>{validation.error.line ? `第 ${validation.error.line} 行：` : ''}{validation.error.message}</p> : null}<small>仅静态检查，未运行策略。</small></div> : null}
      </div>
      {assistantOpen ? <aside className="code-assistant" aria-label="AI 代码助手"><header><span><WandSparkles size={17} /><strong>AI 助手</strong></span><button aria-label="收起 AI 助手" onClick={() => setAssistantOpen(false)}><X size={17} /></button></header>
        <div className="code-ai-status"><i className={capabilities?.configured ? 'is-ready' : ''} /><span>{capabilities?.configured ? `${capabilities.model ?? '模型'} 已配置` : capabilityError || capabilities?.message || (capabilities ? '尚未配置模型' : '正在检查模型连接…')}</span><button onClick={loadCapabilities} aria-label="刷新 AI 连接状态">刷新</button></div>
        <div className="code-conversation" aria-live="polite">{!messages.length ? <div className="code-assistant-intro"><div className="code-assistant-mark"><Bot size={30} /></div><h2>把想法写成策略</h2><p>描述你的交易逻辑，或让我帮你检查当前代码。</p><div className="code-prompt-examples">{['写一个双均线交叉策略', '加入止损与仓位限制', '分析当前策略的风险', '给代码添加中文注释'].map((text) => <button key={text} onClick={() => setPrompt(text)}>{text}<ChevronDown size={12} /></button>)}</div><small>AI 修改先预览，由你决定是否应用。</small></div> : messages.map((message) => <article className={`code-message is-${message.role}`} key={message.id}><strong>{message.role === 'user' ? '你' : 'AI 助手'}</strong><p>{message.text}</p>{message.code ? <div className="code-suggestion"><details><summary><Code2 size={14} />查看建议代码 · {message.code.split('\n').length} 行</summary><pre>{message.code}</pre></details><button onClick={() => {
            if (codeRef.current !== message.baseline) setPending({ code: message.code!, reason: '生成建议后代码已有修改。应用建议会替换当前版本，你可以取消以保留编辑。' })
            else replace(message.code!)
          }}><Check size={14} />应用到编辑器</button></div> : null}</article>)}{busy ? <div className="code-ai-thinking"><LoaderCircle size={16} className="spin" />正在根据当前代码生成建议…</div> : null}<div ref={messagesEnd} /></div>
        <form className="code-ai-composer" onSubmit={(event) => { event.preventDefault(); void send() }}><label htmlFor="code-ai-prompt">告诉 AI 你想实现什么</label><textarea id="code-ai-prompt" value={prompt} maxLength={4000} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：用 20 / 60 日均线判断趋势，单次仓位不超过 20%…" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div><small>发送当前代码 · Shift + Enter 换行</small>{busy ? <button type="button" onClick={cancel}><Square size={14} />停止</button> : <button type="submit" disabled={!prompt.trim() || !capabilities?.configured}><Send size={15} />发送</button>}</div>{!capabilities?.configured ? <details className="code-connect-help"><summary>如何连接 AI？</summary><p>打开右上角设置 → AI 服务，选择 DeepSeek 或通义千问，填写模型与 Key，授权后保存并测试连接。也可以在服务端配置本机 Ollama（ATLAS_AI_URL 与 ATLAS_AI_MODEL），启动模型后刷新连接状态。代码助手会发送当前代码和提问；保密策略请使用开发者自己控制的本地模型。</p></details> : null}</form>
      </aside> : null}
    </div>
    <div className="code-studio-feedback">{error ? <p role="alert">{error}<button onClick={() => setError('')} aria-label="关闭错误"><X size={14} /></button></p> : null}{notice ? <p role="status">{notice}</p> : null}<span><ShieldCheck size={13} />{language === 'python' ? 'Python 支持语法检查，未运行策略。' : `${languageInfo.label} 支持编辑与 AI 编写，编译和回测尚未接入。`}</span><span><MessageSquare size={13} />AI 建议需自行审阅</span></div>
  </section>
}
