import { useEffect, useId, useRef, useState } from 'react'
import { Bot, Check, ChevronDown, Code2, LoaderCircle, Send, Square, WandSparkles, X } from 'lucide-react'
import { request } from '../request'
import { labOwnerHeaders } from '../lab-strategy-types'
import { AISettings } from './AISettings'
import { MAX_STRATEGY_SOURCE, sourceBytes, type StrategyLanguage } from './strategy-languages'
import './code-strategy.css'

interface Capabilities { configured: boolean; model?: string; message?: string; bounded_authoring?: boolean; conversation_context?: boolean }
interface Suggestion { explanation: string; code: string | null; validation?: Validation }
interface Message { id: number; role: 'user' | 'assistant'; text: string; code?: string | null; baseline?: string; validation?: Validation }
export interface Validation {
  valid: boolean
  error: { message: string; line?: number | null; offset?: number | null; kind?: string } | null
  syntax_valid?: boolean
  backtest_compatible?: boolean
  proof_compatible?: boolean
  dry_run?: { passed: boolean; synthetic: boolean; scenarios: number; bars_per_scenario: number } | null
}

export function ValidationDetails({ value, staticOnly = false }: { value: Validation; staticOnly?: boolean }) {
  const bounded = !staticOnly && value.syntax_valid != null
  return <div className={`code-validation ${value.valid ? 'is-valid' : 'is-invalid'}`} role="status">
    <strong>{staticOnly ? value.valid ? '语法与入口静态检查通过' : '需要修复代码' : bounded ? value.valid ? '代码检测通过' : '代码尚未通过平台检测' : value.valid ? '语法检查通过' : '需要修复代码'}</strong>
    {bounded ? <p>语法：{value.syntax_valid ? '通过' : '未通过'} · 回测兼容：{value.backtest_compatible ? '通过' : '未通过'} · 证明兼容：{value.proof_compatible ? '通过' : '未通过'} · 合成试跑：{value.dry_run?.passed ? '通过' : '未通过或未执行'}</p> : null}
    {value.error ? <p>{value.error.line ? `第 ${value.error.line} 行${value.error.offset ? `，第 ${value.error.offset} 列` : ''}：` : ''}{value.error.message}</p> : null}
    <small>{bounded ? value.dry_run?.passed ? '使用合成行情检查执行兼容性；不是历史回测，未生成 Proof。' : '保留当前代码，请按诊断修正；未运行真实行情或生成 Proof。' : '仅静态检查，未运行策略。'}</small>
  </div>
}

interface AssistantProps {
  code: string
  language: StrategyLanguage
  ownerId?: string
  fileName?: string
  disabled?: boolean
  bounded?: boolean
  onApply: (replacement: string, baseline: string) => void
  onClose: () => void
}

export function StrategyCodeAssistant(props: AssistantProps) {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [capabilityError, setCapabilityError] = useState('')
  const capabilityRequest = useRef<AbortController | null>(null)

  const loadCapabilities = () => {
    capabilityRequest.current?.abort()
    const abort = new AbortController()
    capabilityRequest.current = abort
    request<Capabilities>('/strategy-code/capabilities', { signal: abort.signal })
      .then(result => { if (!abort.signal.aborted) setCapabilities(result) })
      .catch(() => { if (!abort.signal.aborted) setCapabilityError('无法读取 AI 连接状态，请重试。') })
  }

  useEffect(() => {
    loadCapabilities()
    return () => capabilityRequest.current?.abort()
  }, [])

  return <StrategyCodeConversation key={props.language} {...props} capabilities={capabilities}
    capabilityError={capabilityError} loadCapabilities={() => { setCapabilityError(''); loadCapabilities() }} />
}

function StrategyCodeConversation({ code, language, ownerId, fileName, disabled = false, bounded = true,
  capabilities, capabilityError, loadCapabilities, onApply, onClose }: AssistantProps & {
  capabilities: Capabilities | null
  capabilityError: string
  loadCapabilities: () => void
}) {
  const promptId = useId()
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [aiSettingsOpen, setAISettingsOpen] = useState(false)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const oversized = sourceBytes(code) > MAX_STRATEGY_SOURCE

  useEffect(() => () => { controller.current?.abort(); generation.current += 1 }, [])
  useEffect(() => { if (messages.length || busy) messagesEnd.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, busy])

  const send = async () => {
    if (disabled || oversized || !prompt.trim() || busy || !capabilities?.configured) return
    const current = ++generation.current
    const text = prompt.trim()
    const baseline = code
    const history = messages.slice(-6).map(message => {
      const content = message.text + (message.code ? `\n此前建议代码（不代表已应用，当前编辑器代码另行提供）：\n${message.code}` : '')
      return { role: message.role, content: content.length > 4000 ? content.slice(0, 3960) + '\n[历史消息过长，已截断]' : content }
    })
    const structured = bounded && capabilities?.bounded_authoring === true && language === 'python' && (!baseline.trim() || /\bdef\s+target_bps\s*\(/.test(baseline))
    const abort = new AbortController(); controller.current = abort
    setMessages((items) => [...items, { id: current * 2, role: 'user', text }])
    setPrompt(''); setBusy(true); setError(''); setNotice('')
    try {
      const response = await request<Suggestion>('/strategy-code/assist', { method: 'POST', headers: ownerId ? labOwnerHeaders(ownerId) : undefined, body: JSON.stringify({ prompt: text, code: baseline, language, ...(structured ? { generation_mode: 'rules' } : {}), ...(capabilities.conversation_context ? { history } : {}) }), signal: abort.signal }, structured ? 120_000 : 90_000)
      if (generation.current !== current) return
      setMessages((items) => [...items, { id: current * 2 + 1, role: 'assistant', text: response.explanation, code: response.code, baseline, validation: response.validation }])
    } catch (reason) {
      if (generation.current === current) { setError(reason instanceof Error ? reason.message : 'AI 请求失败，请重试。'); setPrompt(text) }
    } finally { if (generation.current === current) setBusy(false) }
  }
  const cancel = () => { generation.current += 1; controller.current?.abort(); setBusy(false); setNotice('已停止等待本次生成。') }
  return <aside className="code-assistant" aria-label="AI 代码助手">
    <header>
      <span><WandSparkles size={17} /><strong>{fileName ? `AI 助手 · ${fileName}` : 'AI 助手'}</strong></span>
      <button aria-label="收起 AI 助手" onClick={onClose}><X size={17} /></button>
    </header>
    <div className="code-ai-status">
      <i className={capabilities?.configured ? 'is-ready' : ''} />
      <span>{capabilities?.configured ? `${capabilities.model ?? '模型'} 已配置`
        : capabilityError || capabilities?.message || (capabilities ? '尚未配置模型' : '正在检查模型连接…')}</span>
      <button onClick={loadCapabilities} aria-label="刷新 AI 连接状态">刷新</button>
      <button onClick={() => setAISettingsOpen(value => !value)}>AI 服务配置</button>
    </div>
    <div className="code-conversation" aria-live="polite">
      {!messages.length ? <div className="code-assistant-intro">
        <div className="code-assistant-mark"><Bot size={30} /></div>
        <h2>{fileName ? '检查或修改当前文件' : '把想法写成策略'}</h2>
        <p>{fileName ? '助手会收到当前文件的源码与提问。' : '描述你的交易逻辑，或让我帮你检查当前代码。'}</p>
        <div className="code-prompt-examples">
          {['写一个双均线交叉策略', '加入止损与仓位限制', '分析当前策略的风险', '给代码添加中文注释'].map(text =>
            <button key={text} onClick={() => setPrompt(text)}>{text}<ChevronDown size={12} /></button>)}
        </div>
        <small>AI 修改先预览，由你决定是否应用。</small>
      </div> : messages.map(message => <article className={`code-message is-${message.role}`} key={message.id}>
        <strong>{message.role === 'user' ? '你' : 'AI 助手'}</strong>
        <p>{message.text}</p>
        {message.code ? <div className="code-suggestion">
          <details><summary><Code2 size={14} />查看建议代码 · {message.code.split('\n').length} 行</summary><pre>{message.code}</pre></details>
          {message.validation ? <ValidationDetails value={message.validation} /> : null}
          <button disabled={disabled || message.validation?.valid === false} onClick={() => {
            if (message.code != null && message.baseline != null && message.validation?.valid !== false) {
              onApply(message.code, message.baseline)
            }
          }}><Check size={14} />应用到编辑器</button>
        </div> : null}
      </article>)}
      {busy ? <div className="code-ai-thinking"><LoaderCircle size={16} className="spin" />正在根据当前代码生成建议…</div> : null}
      <div ref={messagesEnd} />
    </div>
    {aiSettingsOpen && <AISettings />}
    {error ? <p className="code-ai-feedback" role="alert">{error}</p> : null}
    {notice ? <p className="code-ai-feedback" role="status">{notice}</p> : null}
    {oversized ? <p className="code-ai-feedback" role="status">AI 助手最多接收 60,000 字节的单个文件。</p> : null}
    <form className="code-ai-composer" onSubmit={event => { event.preventDefault(); void send() }}>
      <label htmlFor={promptId}>告诉 AI 你想实现什么</label>
      <textarea id={promptId} value={prompt} maxLength={4000} onChange={event => setPrompt(event.target.value)}
        placeholder="例如：用 20 / 60 日均线判断趋势，单次仓位不超过 20%…" onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            void send()
          }
        }} />
      <div>
        <small>{fileName ? '发送当前文件' : '发送当前代码'} · Shift + Enter 换行</small>
        {busy ? <button type="button" onClick={cancel}><Square size={14} />停止</button>
          : <button type="submit" disabled={disabled || oversized || !prompt.trim() || !capabilities?.configured}><Send size={15} />发送</button>}
      </div>
      {!capabilities?.configured ? <details className="code-connect-help">
        <summary>如何连接 AI？</summary>
        <p>打开「AI 服务配置」，选择服务商，填写模型与 Key 并授权，也可连接服务端配置的本地模型。</p>
      </details> : null}
    </form>
  </aside>
}
