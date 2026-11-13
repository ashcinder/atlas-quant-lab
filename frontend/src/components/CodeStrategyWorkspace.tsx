import { lazy, Suspense, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Bot, Check, CheckCheck, ChevronDown, Code2, Download, FileCode2, FolderArchive, LoaderCircle, Send, ShieldCheck, Square, Upload, WandSparkles, X, Play, MoreHorizontal, Settings2, PanelRightClose, ArrowUpRight, CircleHelp } from 'lucide-react'
import { request } from '../request'
import { api } from '../api'
import { PublishRuntimeStrategy } from './PublishRuntimeStrategy'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'
import { LabConfirmDialog } from './LabConfirmDialog'
import { BacktestPeriod } from './BacktestPeriod'
import { AISettings } from './AISettings'
import { supportsMinuteBars } from '../marketSupport'
import type { Asset, Interval } from '../types'
import './code-strategy.css'
import './code-workbench.css'
import { STRATEGY_LANGUAGES, languageForFile, type StrategyLanguage } from './strategy-languages'

const PythonProjectWorkspace = lazy(() => import('./PythonProjectWorkspace'))

const MAX_CODE = 60_000
export const PORTABLE_PYTHON_TEMPLATE = `def initialize(context):
    context.state["signals"] = 0

def target(context):
    if len(context.close) < 20:
        return 0.0
    fast = context.sma(5)
    slow = context.sma(20)
    if fast > slow:
        context.state["signals"] += 1
        return 0.8
    return 0.0
`

export const RUNNABLE_PYTHON_TEMPLATE = `def target_bps(index, close, sma):
    fast = sma(5)
    slow = sma(20)
    return (5000 if fast > slow else 0) if index >= 20 else 0
`
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

function ValidationDetails({ value,proofApplicable=true }: { value: Validation;proofApplicable?:boolean }) {
  const bounded = value.syntax_valid != null
  return <div className={`code-validation ${value.valid ? 'is-valid' : 'is-invalid'}`} role="status">
    <details open={!value.valid}><summary><CheckCheck size={14}/><strong>{bounded ? value.valid ? '代码检测通过' : '代码尚未通过平台检测' : value.valid ? '语法检查通过' : '需要修复代码'}</strong><span>检查详情</span><ChevronDown size={12}/></summary>
    {bounded ? <p>语法：{value.syntax_valid ? '通过' : '未通过'} · 回测兼容：{value.backtest_compatible ? '通过' : '未通过'}{proofApplicable&&<> · 证明兼容：{value.proof_compatible ? '通过' : '未通过'}</>} · 合成试跑：{value.dry_run?.passed ? '通过' : '未通过或未执行'}</p> : null}
    {value.error ? <p>{value.error.line ? `第 ${value.error.line} 行${value.error.offset ? `，第 ${value.error.offset} 列` : ''}：` : ''}{value.error.message}</p> : null}
    <small>{bounded ? value.dry_run?.passed ? '使用合成行情检查执行兼容性；不是历史回测，未生成 Proof。' : '保留当前代码，请按诊断修正；未运行真实行情或生成 Proof。' : '仅静态检查，未运行策略。'}</small></details>
  </div>
}

export function CodeStrategyWorkspace({ research, assets = [], onResearchContextChange }: { research?: ResearchWorkspaceProps; assets?: Asset[]; onResearchContextChange?: (asset: Asset, interval: Interval) => void } = {}) {
  const [projectMode, setProjectMode] = useState(false)
  const [projectMounted, setProjectMounted] = useState(false)
  const [incomingArchive, setIncomingArchive] = useState<{ file: File } | null>(null)
  const projectInput = useRef<HTMLInputElement>(null)
  const openProject = () => {
    toolsMenu.current?.removeAttribute('open')
    setProjectMounted(true)
    setProjectMode(true)
  }
  const [code, setCode] = useState<string>(RUNNABLE_PYTHON_TEMPLATE)
  const portable = /\bdef\s+target\s*\(/.test(code)
  const [codeEngine,setCodeEngine] = useState<'atlas'|'vnpy'|'rqalpha'>('atlas')
  const codeAbort=useRef<AbortController|null>(null)
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
  const [backtesting, setBacktesting] = useState(false)
  const backtestPending = useRef(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [validation, setValidation] = useState<Validation | null>(null)
  const [pane, setPane] = useState<'code' | 'guide'>('code')
  const [assistantOpen, setAssistantOpen] = useState(true)
  const inspectorId=useId()
  const [inspectorTab,setInspectorTab]=useState<'backtest'|'assistant'>(research?'backtest':'assistant')
  const [runSettings,setRunSettings]=useState<Partial<{capital:number;commission:number;slippage:number;spread:number;position:number;participation:number}>>({})
  const [aiSettingsOpen, setAISettingsOpen] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
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
  const toolsMenu = useRef<HTMLDetailsElement>(null)
  const latestContext=useRef(research)
  useEffect(()=>{latestContext.current=research},[research])
  const settings={capital:runSettings.capital??research?.initialCapital??100000,commission:runSettings.commission??research?.commission??.001,slippage:runSettings.slippage??research?.slippage??.0005,spread:runSettings.spread??research?.spread??.0005,position:runSettings.position??research?.maxPosition??.95,participation:runSettings.participation??research?.maxParticipation??.01}
  const showInspector=(tab:'backtest'|'assistant')=>{setAssistantOpen(true);setInspectorTab(tab)}
  const loadExample=(next:string)=>{
    toolsMenu.current?.removeAttribute('open')
    if(code.trim()&&code!==next)setPending({code:next,reason:'载入示例会替换当前代码。可以先下载保存，或取消保留编辑。'})
    else replace(next)
  }

  const highlightedCode = useMemo(() => code.split(/(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"""[\s\S]*?"""|'[^'\n]*'|"[^"\n]*"|\b(?:from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)\b|\b\d+(?:\.\d+)?\b)/g).map((token, index) => {
    const kind = (token.startsWith('//') || token.startsWith('/*') || (token.startsWith('#') && ['python', 'r', 'julia'].includes(language))) ? 'comment' : /^['"]/.test(token) ? 'string' : /^(from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)$/.test(token) ? 'keyword' : /^\d/.test(token) ? 'number' : ''
    return <span key={index} className={kind ? `syntax-${kind}` : undefined}>{token}</span>
  }), [code, language])

  const loadCapabilities = () => {
    setCapabilityError('')
    request<Capabilities>('/strategy-code/capabilities').then(setCapabilities).catch(() => setCapabilityError('无法读取 AI 连接状态，请重试。'))
  }
  useEffect(() => {
    const refresh = () => { request<Capabilities>('/strategy-code/capabilities').then(setCapabilities).catch(() => setCapabilityError('无法读取 AI 连接状态，请重试。')) }
    refresh(); window.addEventListener('atlas-ai-config-changed', refresh)
    return () => { window.removeEventListener('atlas-ai-config-changed', refresh); controller.current?.abort(); codeAbort.current?.abort(); generation.current += 1; importSequence.current += 1 }
  }, [])
  useEffect(() => {
    if (!dirty && !Object.entries(drafts.current).some(([id, draft]) => id !== language && draft?.dirty)) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, language])
  useEffect(() => { if (messages.length || busy) messagesEnd.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, busy])
  useEffect(()=>{
    const close=(event:PointerEvent)=>{if(toolsMenu.current?.open&&!toolsMenu.current.contains(event.target as Node))toolsMenu.current.removeAttribute('open')}
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&toolsMenu.current?.open){toolsMenu.current.removeAttribute('open');toolsMenu.current.querySelector('summary')?.focus()}}
    window.addEventListener('pointerdown',close);window.addEventListener('keydown',escape)
    return()=>{window.removeEventListener('pointerdown',close);window.removeEventListener('keydown',escape)}
  },[])

  const edit = (next: string) => {
    if (next.length > MAX_CODE) { setError('代码超过 60,000 字符，请拆分后导入。'); return }
    revision.current += 1; codeRef.current = next
    setCode(next); setDirty(true); setValidation(null); setNotice('')
  }
  const switchLanguage = (next: StrategyLanguage) => {
    if (next === language) return
    drafts.current[language] = { code: codeRef.current, name, dirty }
    const saved = drafts.current[next]
    generation.current += 1; controller.current?.abort(); codeAbort.current?.abort(); importSequence.current += 1
    revision.current += 1
    const nextCode = saved?.code ?? (next === 'python' ? RUNNABLE_PYTHON_TEMPLATE : STRATEGY_LANGUAGES.find((item) => item.id === next)!.template)
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
    if (checking || backtesting || !code.trim() || language !== 'python') return
    const snapshot = revision.current
    setChecking(true); setError('')
    codeAbort.current=new AbortController()
    try {
      if(portable){
        const {runPortablePython}=await import('../compute/portablePython')
        const bars=Array.from({length:100},(_,i)=>({time:1700000000+i*60,open:100+i,high:102+i,low:99+i,close:101+i,volume:100000}))
        await runPortablePython(code,bars,{},codeAbort.current.signal)
        if(snapshot===revision.current)setValidation({valid:true,syntax_valid:true,backtest_compatible:true,proof_compatible:false,error:null,dry_run:{passed:true,synthetic:true,scenarios:1,bars_per_scenario:100}})
        else setNotice('代码已修改，请重新检查当前版本。')
        return
      }
      const result = await request<Validation>('/strategy-code/validate', { method: 'POST', signal:codeAbort.current.signal, body: JSON.stringify({ code, language, ...(capabilities?.bounded_authoring ? { profile: 'bounded' } : {}) }) })
      if (snapshot === revision.current) setValidation(result)
      else setNotice('代码已修改，请重新检查当前版本。')
    } catch (reason) { if(codeAbort.current?.signal.aborted)setNotice('已取消本次检查，代码已保留。');else setError(reason instanceof Error ? reason.message : '检查失败，请重试。') }
    finally { setChecking(false) }
  }
  const runCodeBacktest = async () => {
    if (!research?.asset || backtestPending.current || checking || !code.trim() || language !== 'python') return
    if(settings.capital<=0||settings.position<=0||settings.position>1||settings.participation<=0||settings.participation>1||[settings.commission,settings.slippage,settings.spread].some(v=>v<0||v>.1)){
      setError('请检查资金与成本：初始资金须大于0，仓位与参与率须大于0且不超过100%，费用为0至10%。');showInspector('backtest');return
    }
    if (research.source!=='huggingface' && ['1m','5m'].includes(research.interval) && (!start || !end)) { setError('请先设置分钟回测的开始与结束时间。'); return }
    const snapshot = revision.current
    backtestPending.current = true; setBacktesting(true); setError(''); research.onLoading(true)
    codeAbort.current=new AbortController()
    try {
      if(!portable){
      const checked = await request<Validation>('/strategy-code/validate', {method:'POST',signal:codeAbort.current.signal,body:JSON.stringify({code,language,...(capabilities?.bounded_authoring ? {profile:'bounded'} : {})})})
      if (snapshot !== revision.current) throw new Error('代码已修改，请重新运行当前版本。')
      setValidation(checked)
      if (!checked.valid || checked.backtest_compatible === false) throw new Error(checked.error?.message ?? '代码未通过回测兼容检查，请按诊断修正。')
      }
      const payload = { backtest_engine:codeEngine,execution_model:research.source==='huggingface'?'unified':'native',strategy_name:name,portable_python:portable?code:undefined, symbol: research.asset.symbol, asset_class: research.asset.asset_class,
        interval: research.interval, data_source: research.source, strategy_id: portable?'python_portable':'python_bounded', python_source: portable?undefined:code,
        start: start ? new Date(start).toISOString() : null, end: end ? new Date(end).toISOString() : null,
        params: {}, initial_capital: settings.capital, commission_rate: settings.commission,
        slippage_rate: settings.slippage, spread_rate: settings.spread, max_position: settings.position,
        max_participation_rate: settings.participation, execution_pipeline: research.executionPipeline }
      const result=await api.runBacktest(payload,codeAbort.current.signal)
      if (snapshot !== revision.current) { setNotice('上一代码快照的回测已完成，可在历史中查看；当前编辑内容已保留。'); return }
      const current=latestContext.current
      if(current?.asset?.symbol!==research.asset.symbol||current?.interval!==research.interval||current?.source!==research.source){setNotice('上一组设置的回测已完成，可在历史中查看；当前回测设置已保留。');return}
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(code))
      research.onCustomResult(result, { name, source: code, strategyKind:portable?'python_portable':'python_bounded', start, end, backtestSettings:settings,executionPipeline: research.executionPipeline, hash: Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('') })
      setNotice(`代码回测完成：${result.trades.length} 笔交易；收益、曲线与交易明细已更新。`)
    } catch (reason) { if(codeAbort.current?.signal.aborted)setNotice('已取消本次回测，代码已保留。');else setError(reason instanceof Error ? reason.message : '代码回测失败') }
    finally { backtestPending.current = false; setBacktesting(false); research.onLoading(false) }
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
      const response = await request<Suggestion>('/strategy-code/assist', { method: 'POST', body: JSON.stringify({ prompt: text, code: baseline, language, ...(structured ? { generation_mode: 'rules' } : {}), ...(capabilities.conversation_context ? { history } : {}) }), signal: abort.signal }, structured ? 120_000 : 90_000)
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

  return <>
    {projectMounted ? <div className="python-project-host" hidden={!projectMode}>
      <Suspense fallback={<p role="status">正在加载项目工作区…</p>}>
        <PythonProjectWorkspace onBack={() => setProjectMode(false)} incomingArchive={incomingArchive} />
      </Suspense>
    </div> : null}
    <section hidden={projectMode} className={`code-studio ${assistantOpen ? '' : 'assistant-closed'}`} aria-label="代码策略工作区">
    {pending ? <LabConfirmDialog title="替换当前代码？" description={pending.reason} confirmLabel="替换代码" onCancel={() => setPending(null)} onConfirm={() => replace(pending.code, pending.name, pending.language)} /> : null}
    <header className="code-studio-toolbar">
      <div className="studio-document-heading"><span className="studio-document-icon"><FileCode2 size={21} /></span><div>
        <input aria-label="代码策略名称" className="code-name" value={name} maxLength={80} onChange={event=>{setName(event.target.value);setDirty(true)}} />
        <span className="code-draft-state"><i className={dirty?'is-dirty':''} />{dirty?'有未下载的修改':'页面草稿'}<span>·</span>{research?.asset?`${research.asset.name} · ${research.interval}`:'策略开发'}</span>
      </div></div>
      <div className="studio-header-actions">
        <button className="studio-project-toggle" type="button" aria-label="项目文件" title="项目文件" disabled={backtesting} onClick={() => openProject()}><FolderArchive size={16} /><span>项目文件</span></button>
        <details className="code-tools-menu" ref={toolsMenu}><summary aria-label="代码文件与工具"><MoreHorizontal size={17} /><span>文件</span><ChevronDown size={12} /></summary><div>
          <button type="button" onClick={()=>{toolsMenu.current?.removeAttribute('open');fileInput.current?.click()}}><Upload size={15} /><span>导入代码<small>打开本地源码文件</small></span></button>
          <button type="button" disabled={backtesting} onClick={() => { toolsMenu.current?.removeAttribute('open'); projectInput.current?.click() }}><FolderArchive size={15} /><span>导入 Python 项目<small>ZIP · 选择入口脚本并运行</small></span></button>
          <button type="button" onClick={()=>{toolsMenu.current?.removeAttribute('open');download()}}><Download size={15} /><span>下载保存<small>保存到自己的设备 · ⌘ / Ctrl S</small></span></button>
          <hr /><p className="studio-menu-label">从示例开始</p>
          <button type="button" disabled={language!=='python'} onClick={()=>loadExample(PORTABLE_PYTHON_TEMPLATE)}><Code2 size={15} /><span>载入通用Python（三框架）<small>函数、循环、状态 · NumPy / pandas</small></span></button>
          <button type="button" disabled={language!=='python'} onClick={()=>loadExample(RUNNABLE_PYTHON_TEMPLATE)}><ShieldCheck size={15} /><span>载入 Python 示例<small>整数仓位接口 · 可检查证明兼容性</small></span></button>
        </div></details>
        <input ref={fileInput} type="file" accept={STRATEGY_LANGUAGES.flatMap(item=>[...item.extensions]).join(',')} hidden onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)void importFile(file)}} />
        <input ref={projectInput} aria-label="导入 Python 项目 ZIP" type="file" accept=".zip,application/zip" hidden onChange={event => {
          const file = event.currentTarget.files?.[0]
          event.currentTarget.value = ''
          if (file) { setIncomingArchive({ file }); openProject() }
        }} />
        <button className="studio-download" title="下载源码（⌘ / Ctrl S）" aria-label="下载保存" onClick={download}><Download size={16} /></button>
        <span className="studio-action-divider" />
        <button className="code-check" title={portable?'检查语法并使用合成行情试跑':language==='python'?'检查语法与执行兼容性':`${languageInfo.label} 编译检查尚未接入`} disabled={checking||backtesting||!code.trim()||language!=='python'} onClick={()=>void check()}>{checking?<LoaderCircle size={15} className="spin"/>:<CheckCheck size={15}/>}检查代码</button>
        {research&&<button className="code-run-primary" type="button" title="使用右侧设置运行当前代码（⌘ / Ctrl Enter）" disabled={!research.asset||backtesting||checking||!code.trim()||language!=='python'} onClick={()=>void runCodeBacktest()}>{backtesting?<LoaderCircle size={15} className="spin"/>:<Play size={15}/>}<span>{backtesting?'回测中…':'运行回测'}</span></button>}
        <button className="studio-inspector-trigger" title="回测设置" aria-label="回测设置" aria-pressed={assistantOpen&&inspectorTab==='backtest'} onClick={()=>showInspector('backtest')} hidden={!research}><Settings2 size={17}/></button>
        <button className="code-ai-toggle" aria-pressed={assistantOpen&&inspectorTab==='assistant'} onClick={()=>showInspector('assistant')}><WandSparkles size={16}/><span>AI 助手</span></button>
      </div>
    </header>
    <div className="code-studio-body">
      <div className="code-editor-panel">
        <div className="code-editor-tabs"><div role="tablist" aria-label="代码编辑视图"><button role="tab" aria-selected={pane === 'code'} onClick={() => setPane('code')}><FileCode2 size={14} />strategy{languageInfo.extensions[0]}</button><button role="tab" aria-selected={pane === 'guide'} onClick={() => setPane('guide')}>编写指南</button></div><div><select className="studio-language-select" aria-label="策略编程语言" disabled={checking||backtesting} value={language} onChange={event=>switchLanguage(event.target.value as StrategyLanguage)}>{STRATEGY_LANGUAGES.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select>{undoCode !== null ? <button onClick={() => { const previous = undoCode; setUndoCode(code); edit(previous) }}>撤销替换</button> : null}</div></div>
        {pane === 'code' ? <div className="code-editor-surface"><div ref={gutter} className="code-line-numbers" aria-hidden="true">{code.split('\n').map((_, index) => <div key={index}>{index + 1}</div>)}</div><div className="code-text-layer">{!code.trim()&&<div className="studio-empty-state"><FileCode2 size={32}/><h2>从一个想法，开始一份策略</h2><p>直接编写代码，或选择一个起点。</p><div>{language==='python'&&<button type="button" onClick={()=>loadExample(PORTABLE_PYTHON_TEMPLATE)}><Play size={14}/>载入通用 Python 示例</button>}<button type="button" onClick={()=>fileInput.current?.click()}><Upload size={14}/>导入策略文件</button></div><button type="button" className="studio-empty-ai" onClick={()=>showInspector('assistant')}><WandSparkles size={13}/>让 AI 帮我写<ArrowUpRight size={13}/></button></div>}<pre ref={highlight} aria-hidden="true" className="code-highlight">{highlightedCode}{'\n'}</pre><textarea ref={editor} aria-label={`${languageInfo.label} 策略代码`} value={code} spellCheck={false} autoCapitalize="off" autoComplete="off" wrap="off" onChange={(event) => edit(event.target.value)} onSelect={position} onScroll={(event) => { if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop; if (highlight.current) { highlight.current.scrollTop = event.currentTarget.scrollTop; highlight.current.scrollLeft = event.currentTarget.scrollLeft } }} onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {event.preventDefault();if(event.shiftKey)void check();else void runCodeBacktest()}
          if ((event.metaKey || event.ctrlKey) && event.key === 's') { event.preventDefault(); download() }
          if (event.key === 'Tab' && !event.shiftKey) {
            event.preventDefault(); const start = event.currentTarget.selectionStart; const end = event.currentTarget.selectionEnd
            edit(code.slice(0, start) + '    ' + code.slice(end))
            requestAnimationFrame(() => editor.current?.setSelectionRange(start + 4, start + 4))
          }
        }} /></div></div> : <article className="code-writing-guide"><h2>用 {languageInfo.label} 表达你的交易想法</h2><p>{languageInfo.environment}。右侧助手会按所选语言与当前代码生成建议。</p><dl><dt>起步示例</dt><dd>{language === 'python' ? '通用Python请定义target(context)，返回0至1；context提供history、close、bar、sma(period)、state、params。也保留单个 target_bps(index, close, sma) 函数，返回 0–9500 的整数仓位；5000 表示 50%。默认示例兼容回测与 zkVM 证明。' : '示例演示 20 周期均线信号。通用语言返回目标仓位；平台语言使用对应平台接口。行情、执行与回测需要在目标环境中接入。'}</dd><dt>导入与保存</dt><dd>支持 UTF-8 {languageInfo.extensions.join(" / ")} 文件，最大 60 KB。导入只读取到编辑器；下载保存到自己的设备。切换语言保留代码草稿，刷新或退出前请下载。</dd><dt>AI 与隐私</dt><dd>发送问题时，当前代码和问题会交给服务端配置的模型。请不要在代码或提问中放入密钥。</dd><dt>检查与执行</dt><dd>Python 按后端能力检测，完整检测包括语法、平台回测及证明兼容与合成行情试跑；其他语言暂未接入编译检查，请下载到对应工具中验证。受限 Python 可通过上方入口回测、保存并订阅，使用平台模拟或币安测试账户持续运行；普通 SDK 类请使用隔离执行工具。不能直接自动运行实盘。</dd></dl></article>}
        <footer className="code-editor-status"><span className={`studio-editor-state ${validation?.valid?'is-valid':validation?'is-invalid':''}`}><i/>{checking?'检查中':backtesting?'回测中':!code.trim()?'等待编写':validation?.valid?'检查通过':validation?'需要修正':language==='python'?'尚未检查':'仅编辑'}</span><span>{portable?'通用 Python':language==='python'?'整数 Python':languageInfo.label}</span><span>UTF-8</span><span>{code.split('\n').length} 行</span><span>行 {cursor.line}，列 {cursor.column}</span><span>{code.length.toLocaleString()} 字符</span></footer>
        {validation ? <ValidationDetails value={validation} proofApplicable={!portable} /> : null}
      </div>
      {assistantOpen?<aside className="code-inspector" aria-label="策略工具">
        <div className="studio-inspector-heading"><div role="tablist" aria-label="策略工具面板" onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'&&research?'backtest':event.key==='End'?'assistant':research&&inspectorTab==='assistant'?'backtest':'assistant';setInspectorTab(next);event.currentTarget.querySelector<HTMLButtonElement>(`[data-studio-tab="${next}"]`)?.focus()}}}>{research&&<button role="tab" data-studio-tab="backtest" id={`${inspectorId}-backtest-tab`} aria-controls={`${inspectorId}-backtest`} tabIndex={inspectorTab==='backtest'?0:-1} aria-selected={inspectorTab==='backtest'} onClick={()=>setInspectorTab('backtest')}><Settings2 size={14}/>回测设置</button>}<button role="tab" data-studio-tab="assistant" id={`${inspectorId}-assistant-tab`} aria-controls={`${inspectorId}-assistant`} tabIndex={inspectorTab==='assistant'?0:-1} aria-selected={inspectorTab==='assistant'} onClick={()=>setInspectorTab('assistant')}><WandSparkles size={14}/>AI 助手</button></div><button type="button" aria-label="收起侧栏" title="专注编辑，收起侧栏" onClick={()=>setAssistantOpen(false)}><PanelRightClose size={16}/></button></div>
        {research&&<section className="studio-backtest-settings" role="tabpanel" id={`${inspectorId}-backtest`} aria-labelledby={`${inspectorId}-backtest-tab`} hidden={inspectorTab!=='backtest'}>
          <header><small>本次回测</small><h2>用历史数据检验想法</h2><p>设置将用于当前代码，与归档项目独立。</p></header>
          <div className="studio-settings-fields">
            <label>研究标的<select aria-label="代码回测标的" disabled={!onResearchContextChange||checking||backtesting} value={research.asset?.symbol??''} onChange={event=>{const asset=assets.find(item=>item.symbol===event.target.value);if(asset)onResearchContextChange?.(asset,supportsMinuteBars(asset)?research.interval:['1m','5m'].includes(research.interval)?'15m':research.interval)}}>{!research.asset&&<option value="">请选择标的</option>}{(assets.length?assets:research.asset?[research.asset]:[]).map(asset=><option key={asset.symbol} value={asset.symbol}>{asset.name} · {asset.symbol}</option>)}</select></label>
            <div className="studio-field-pair"><label>K线周期<select aria-label="代码回测周期" disabled={!onResearchContextChange||!research.asset||checking||backtesting} value={research.interval} onChange={event=>{if(research.asset)onResearchContextChange?.(research.asset,event.target.value as Interval)}}>{Object.entries({'1m':'1分钟','5m':'5分钟','15m':'15分钟','1h':'1小时','4h':'4小时','1d':'日线','1wk':'周线'}).filter(([interval])=>supportsMinuteBars(research.asset)||!['1m','5m'].includes(interval)).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
            <label>回测框架<select aria-label="代码回测框架" disabled={checking||backtesting} value={codeEngine} onChange={event=>setCodeEngine(event.target.value as 'atlas'|'vnpy'|'rqalpha')}><option value="atlas">Atlas</option><option value="vnpy">vn.py</option><option value="rqalpha">RQAlpha</option></select></label></div>
            <label className="studio-period-label">历史区间</label><BacktestPeriod label="代码回测" disabled={checking||backtesting} start={start} end={end} onApply={(from,to)=>{setStart(from);setEnd(to)}} />
            <div className="studio-source-context"><i/>{research.source==='huggingface'?'Hugging Face · 历史快照':research.source==='auto'?'自动选择行情来源':research.source}<span>{research.source==='huggingface'?'三框架统一口径':'框架默认口径'}</span></div>
          </div>
          <details className="studio-cost-settings"><summary>资金与交易成本<ChevronDown size={13}/></summary><div className="studio-cost-fields">{([
            ['capital','初始资金',settings.capital,1,research.asset?.currency??'CNY'],['commission','手续费率',settings.commission,100,'%'],['slippage','滑点率',settings.slippage,100,'%'],['spread','买卖价差',settings.spread,100,'%'],['position','最大仓位',settings.position,100,'%'],['participation','成交量参与率',settings.participation,100,'%']
          ] as const).map(([key,label,value,scale,unit])=><label key={key}>{label}<span><input aria-label={`代码回测${label}`} type="number" min={0} step={key==='capital'?1000:.01} disabled={checking||backtesting} value={Number((value*scale).toFixed(6))} onChange={event=>setRunSettings(current=>({...current,[key]:(Number.isFinite(event.target.valueAsNumber)?event.target.valueAsNumber:0)/scale}))}/><em>{unit}</em></span></label>)}</div></details>
          <div className="studio-capital-summary"><span>初始资金</span><strong>{settings.capital.toLocaleString()}<small>{research.asset?.currency??'CNY'}</small></strong></div>
          <div className={`studio-readiness ${validation?.valid?'is-valid':''}`}><ShieldCheck size={17}/><div><strong>{!code.trim()?'先准备一份策略代码':language!=='python'?'当前语言仅支持编辑':validation?.valid?'代码已通过检查':'准备好后即可运行'}</strong><p>{!code.trim()?'导入源码，或载入通用 Python 示例。':language!=='python'?'切换 Python，或下载到对应平台执行。':'运行时自动检查，完成后查看曲线与成交明细。'}</p></div></div>
          {portable&&<button className="studio-inline-action" onClick={()=>{setPane('guide');editor.current?.focus()}}><CircleHelp size={14}/>通用 Python 编写指南<ArrowUpRight size={12}/></button>}
          {language==='python'&&!portable&&<details className="studio-publish-tools"><summary>发布与证明<ChevronDown size={13}/></summary><p>普通回测不生成 Proof。发布前请检查策略的执行与证明兼容性。</p>{!portable&&<PublishRuntimeStrategy label="保存并订阅" draft={{name,source_kind:'python',strategy_id:'python_bounded',python_source:code}} disabled={backtesting||!code.trim()||code.length>16384}/>}</details>}
          {(checking||backtesting)&&<button className="studio-stop" onClick={()=>codeAbort.current?.abort()}><Square size={13}/>停止本次执行</button>}
        </section>}
        <section className="code-assistant" role="tabpanel" id={`${inspectorId}-assistant`} aria-labelledby={`${inspectorId}-assistant-tab`} hidden={inspectorTab!=='assistant'}><header><span><Bot size={15}/>策略编写助手</span><button aria-label="配置 AI 服务" title="配置 AI 服务" onClick={()=>setAISettingsOpen(open=>!open)}><Settings2 size={15}/></button></header>
        <div className="code-ai-status"><i className={capabilities?.configured ? 'is-ready' : ''} /><span>{capabilities?.configured ? `${capabilities.model ?? '模型'} 已配置` : capabilityError || capabilities?.message || (capabilities ? '尚未配置模型' : '正在检查模型连接…')}</span><button onClick={loadCapabilities} aria-label="刷新 AI 连接状态">刷新</button></div>
        {aiSettingsOpen && <section className="code-ai-config"><div className="studio-ai-config-heading"><strong>连接 AI 服务</strong><button onClick={()=>setAISettingsOpen(false)}>返回对话<ArrowUpRight size={12}/></button></div><AISettings /></section>}
        <div className="code-conversation" hidden={aiSettingsOpen} aria-live="polite">{!messages.length ? <div className="code-assistant-intro"><div className="code-assistant-mark"><Bot size={30} /></div><h2>{capabilities?.configured?'一起完善你的策略':'连接模型，开始协作'}</h2><p>{capabilities?.configured?'描述交易逻辑、解释代码，或一起检查风险。':'连接 DeepSeek 或其他模型后，即可让助手编写和修改策略。'}</p>{!capabilities?.configured&&<button className="studio-connect-primary" onClick={()=>setAISettingsOpen(true)}><Settings2 size={15}/>连接 AI 服务<ArrowUpRight size={13}/></button>}<div className="code-prompt-examples">{['写一个双均线交叉策略', '加入止损与仓位限制', '分析当前策略的风险', '给代码添加中文注释'].map((text) => <button key={text} onClick={() => setPrompt(text)}>{text}<ChevronDown size={12} /></button>)}</div><small>AI 修改先预览，由你决定是否应用。</small></div> : messages.map((message) => <article className={`code-message is-${message.role}`} key={message.id}><strong>{message.role === 'user' ? '你' : 'AI 助手'}</strong><p>{message.text}</p>{message.code ? <div className="code-suggestion"><details><summary><Code2 size={14} />查看建议代码 · {message.code.split('\n').length} 行</summary><pre>{message.code}</pre></details>{message.validation ? <ValidationDetails value={message.validation} /> : null}<button disabled={message.validation?.valid === false} onClick={() => {
            if (message.validation?.valid === false) return
            if (codeRef.current !== message.baseline) setPending({ code: message.code!, reason: '生成建议后代码已有修改。应用建议会替换当前版本，你可以取消以保留编辑。' })
            else replace(message.code!)
          }}><Check size={14} />应用到编辑器</button></div> : null}</article>)}{busy ? <div className="code-ai-thinking"><LoaderCircle size={16} className="spin" />正在根据当前代码生成建议…</div> : null}<div ref={messagesEnd} /></div>
        <form className="code-ai-composer" hidden={aiSettingsOpen} onSubmit={(event) => { event.preventDefault(); void send() }}><label htmlFor="code-ai-prompt">告诉 AI 你想实现什么</label><textarea id="code-ai-prompt" value={prompt} maxLength={4000} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：用 20 / 60 日均线判断趋势，单次仓位不超过 20%…" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div><small>发送当前代码 · Shift + Enter 换行</small>{busy ? <button type="button" onClick={cancel}><Square size={14} />停止</button> : <button type="submit" disabled={!prompt.trim() || !capabilities?.configured}><Send size={15} />发送</button>}</div>{!capabilities?.configured ? <details className="code-connect-help"><summary>连接 DeepSeek / 其他服务</summary><button type="button" onClick={()=>setAISettingsOpen(true)}>打开 AI 服务配置</button><p>打开右上角设置 → AI 服务，选择 DeepSeek 或通义千问，填写模型与 Key，授权后保存并测试连接。也可以在服务端配置本机 Ollama（ATLAS_AI_URL 与 ATLAS_AI_MODEL），启动模型后刷新连接状态。代码助手会发送当前代码和提问；保密策略请使用开发者自己控制的本地模型。</p></details> : null}</form>
      </section></aside>:null}
    </div>
    {error||notice?<div className="code-studio-feedback">{error?<p role="alert">{error}<button onClick={()=>setError('')} aria-label="关闭错误"><X size={14}/></button></p>:null}{notice?<p role="status">{notice}</p>:null}</div>:null}
  </section>
  </>
}
