import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Bot, Box, Braces, Check, ChevronDown, CircleAlert, Code2, Cpu, FileArchive,
  Fingerprint, GitBranch, KeyRound, LockKeyhole, PackageCheck, Play, Plus,
  Save, ShieldCheck, SlidersHorizontal, Sparkles, Trash2, UploadCloud, Workflow, X,
} from 'lucide-react'
import { api } from '../api'
import type {
  QuantAgent, StrategyPackageRecord, StudioAIAuthority, StudioAIRole, StudioSpec,
  StudioTemplate, StudioValidation, StudioWorkflow, StudioWorkflowNode, StudioWorkflowRecord,
} from '../types'

export type StudioTab = 'workflow' | 'packages' | 'proof' | 'sdk'
interface Props {
  onError: (message: string) => void
  activeTab?: StudioTab
  embedded?: boolean
  onTabChange?: (tab: StudioTab) => void
  onWorkflowSaved?: (record: StudioWorkflowRecord) => void
  onPackageUploaded?: (record: StrategyPackageRecord) => void
  assetSymbol?: string
  assetClass?: string
  interval?: string
}

const roleLabels: Record<StudioAIRole, string> = {
  regime_detection: '市场状态识别', signal_review: '信号复核', risk_control: 'AI 风险官',
  position_management: '仓位管理', execution_review: '执行前审查',
}
const authorityLabels: Record<StudioAIAuthority, string> = {
  advisory: '仅建议', veto: '可否决', bounded_adjustment: '有界调整',
}
const typeMeta: Record<string, { tag: string; hint: string }> = {
  market_data: { tag: 'DATA', hint: '时点对齐 / 复权 / 质量门' },
  universe: { tag: 'UNIV', hint: '标的筛选与退市处理' },
  feature_engine: { tag: 'FACTOR', hint: '因果特征，禁止未来函数' },
  strategy: { tag: 'ALPHA', hint: '私密策略包 / Runner' },
  position_sizer: { tag: 'SIZE', hint: '生成基准目标仓位' },
  ai_guard: { tag: 'AI', hint: '结构化建议 / 否决 / 有界调整' },
  risk_gate: { tag: 'HARD RISK', hint: '确定性限额，AI 无法绕过' },
  execution_review: { tag: 'REVIEW', hint: '流动性与订单复核' },
  execution: { tag: 'EXEC', hint: '下一根 K 线 / 成本 / 滑点' },
  audit: { tag: 'PROOF', hint: '决策承诺与追责回执' },
  output: { tag: 'SCORE', hint: '回测、实盘与跑分' },
}
const nodeStage: Record<string, number> = {
  market_data: 10, universe: 10, feature_engine: 20, strategy: 30, position_sizer: 40,
  risk_gate: 50, execution_review: 55, execution: 60, audit: 70, output: 80,
}
const aiStage: Record<StudioAIRole, number> = {
  regime_detection: 25, signal_review: 35, position_management: 45, risk_control: 48, execution_review: 55,
}

function cloneWorkflow(workflow: StudioWorkflow): StudioWorkflow {
  return JSON.parse(JSON.stringify(workflow)) as StudioWorkflow
}

function orderNodes(nodes: StudioWorkflowNode[]) {
  return [...nodes].sort((left, right) => {
    const leftStage = left.type === 'ai_guard' ? aiStage[left.config.role as StudioAIRole] : nodeStage[left.type]
    const rightStage = right.type === 'ai_guard' ? aiStage[right.config.role as StudioAIRole] : nodeStage[right.type]
    return leftStage - rightStage
  })
}

function linearize(workflow: StudioWorkflow, nodes: StudioWorkflowNode[]): StudioWorkflow {
  const ordered = orderNodes(nodes)
  return { ...workflow, nodes: ordered, edges: ordered.slice(1).map((node, index) => ({ source: ordered[index].id, target: node.id })) }
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="qjs-field"><span>{label}{hint ? <small>{hint}</small> : null}</span>{children}</label>
}

function ValidationPanel({ validation }: { validation: StudioValidation | null }) {
  if (!validation) return <div className="qjs-validation is-pending" aria-live="polite"><Cpu className="spin" size={15} /><span><strong>正在编译…</strong><small>检查 DAG、AI 权限与硬风控路径</small></span></div>
  return <div className={`qjs-validation ${validation.valid ? 'is-valid' : 'is-invalid'}`}>
    {validation.valid ? <ShieldCheck size={16} /> : <CircleAlert size={16} />}
    <span><strong>{validation.valid ? '可运行 · 风控路径完整' : `编译失败 · ${validation.errors.length} 项`}</strong><small>{validation.valid ? `${validation.summary.nodes} 节点 / ${validation.summary.ai_nodes} AI / ${validation.graph_hash.slice(0, 12)}…` : validation.errors[0]}</small></span>
  </div>
}

export function QuantStrategyStudio({
  onError, activeTab, embedded = false, onTabChange, onWorkflowSaved, onPackageUploaded,
  assetSymbol = 'BTC-USD', assetClass = 'crypto', interval = '1d',
}: Props) {
  const [localTab, setLocalTab] = useState<StudioTab>('workflow')
  const tab = activeTab ?? localTab
  const goTab = (next: StudioTab) => {
    setLocalTab(next)
    onTabChange?.(next)
  }
  const [spec, setSpec] = useState<StudioSpec | null>(null)
  const [templates, setTemplates] = useState<StudioTemplate[]>([])
  const [agents, setAgents] = useState<QuantAgent[]>([])
  const [workflow, setWorkflow] = useState<StudioWorkflow | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [validation, setValidation] = useState<StudioValidation | null>(null)
  const [agentId, setAgentId] = useState('')
  const [token, setToken] = useState('')
  const [packages, setPackages] = useState<StrategyPackageRecord[]>([])
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [zkProfiles, setZkProfiles] = useState<import('../types').ZkProfile[]>([])
  const [zkDataset, setZkDataset] = useState<import('../types').ZkMarketDataset | null>(null)
  const [zkProof, setZkProof] = useState<import('../types').ZkProofRecord | null>(null)
  const [publishedProofReport, setPublishedProofReport] = useState<string | null>(null)
  const [proofBusy, setProofBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [activeTemplateId, setActiveTemplateId] = useState('')
  const [saveNotice, setSaveNotice] = useState<{ tone: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [removeArmed, setRemoveArmed] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const proofFileRef = useRef<HTMLInputElement>(null)
  const validationRequest = useRef(0)

  const markEdited = useCallback(() => {
    validationRequest.current += 1
    setValidation(null)
    setDirty(true)
    setSaveNotice(null)
    setActiveTemplateId('')
  }, [])

  useEffect(() => {
    Promise.all([api.getStudioSpec(), api.getStudioTemplates(), api.listQuantAgents(), api.listZkProfiles()]).then(([nextSpec, nextTemplates, nextAgents, nextProfiles]) => {
      setSpec(nextSpec); setTemplates(nextTemplates); setAgents(nextAgents.filter((agent) => !agent.is_demo))
      setZkProfiles(nextProfiles)
      if (nextTemplates[0]) {
        const first = cloneWorkflow(nextTemplates[0].workflow)
        setWorkflow(first); setSelectedId(first.nodes[0]?.id ?? ''); setActiveTemplateId(nextTemplates[0].id)
      }
    }).catch((reason) => onError(reason instanceof Error ? reason.message : '策略工作室加载失败'))
  }, [onError])

  useEffect(() => {
    if (!workflow) return
    const requestId = ++validationRequest.current
    const timer = window.setTimeout(() => {
      api.validateStudioWorkflow(workflow).then((nextValidation) => {
        if (requestId === validationRequest.current) setValidation(nextValidation)
      }).catch((reason) => {
        if (requestId !== validationRequest.current) return
        setValidation(null); onError(reason instanceof Error ? reason.message : '工作流校验失败')
      })
    }, 280)
    return () => window.clearTimeout(timer)
  }, [onError, workflow])

  useEffect(() => {
    if (!dirty) return undefined
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const selected = workflow?.nodes.find((node) => node.id === selectedId) ?? null
  const allowedAuthority = selected?.type === 'ai_guard'
    ? spec?.ai_roles.find((role) => role.id === selected.config.role)?.allowed_authority ?? [] : []

  const loadTemplate = (template: StudioTemplate) => {
    const next = cloneWorkflow(template.workflow)
    validationRequest.current += 1
    setWorkflow(next); setSelectedId(next.nodes[0]?.id ?? ''); setValidation(null)
    setActiveTemplateId(template.id); setDirty(true); setRemoveArmed(false)
    setSaveNotice({ tone: 'info', text: `已载入“${template.name}”，保存后才会形成版本。` })
  }

  const patchSelected = useCallback((patch: Partial<StudioWorkflowNode>, configPatch?: Record<string, unknown>) => {
    markEdited()
    setWorkflow((current) => {
      if (!current) return current
      const nodes = current.nodes.map((node) => node.id === selectedId ? { ...node, ...patch, config: { ...node.config, ...configPatch } } : node)
      return linearize(current, nodes)
    })
  }, [markEdited, selectedId])

  const patchWorkflow = (patch: Partial<StudioWorkflow>) => {
    markEdited()
    setWorkflow((current) => current ? { ...current, ...patch } : current)
  }

  const addAI = (role: StudioAIRole) => {
    if (!workflow) return
    let sequence = workflow.nodes.filter((node) => node.id.startsWith(`ai_${role}_`)).length + 1
    while (workflow.nodes.some((node) => node.id === `ai_${role}_${sequence}`)) sequence += 1
    const authority = spec?.ai_roles.find((item) => item.id === role)?.allowed_authority[0] ?? 'advisory'
    const node: StudioWorkflowNode = {
      id: `ai_${role}_${sequence}`, type: 'ai_guard', label: roleLabels[role],
      config: { role, authority, provider_ref: 'server:primary-model', timeout_ms: 2500, on_error: role === 'risk_control' ? 'deny' : 'use_baseline', instructions: '仅根据输入证据返回结构化决策和 reason_codes。' },
    }
    markEdited(); setWorkflow(linearize(workflow, [...workflow.nodes, node])); setSelectedId(node.id)
    setRemoveArmed(false)
  }

  const removeSelected = () => {
    if (!workflow || selected?.type !== 'ai_guard') return
    const remaining = workflow.nodes.filter((node) => node.id !== selectedId)
    const next = linearize(workflow, remaining)
    markEdited(); setWorkflow(next); setSelectedId(next.nodes[0]?.id ?? ''); setRemoveArmed(false)
    setSaveNotice({ tone: 'info', text: `已删除“${selected.label}”，尚未保存。` })
  }

  const upload = async (file: File) => {
    if (!agentId || !token) { onError('先选择自己的 Agent 并填入开发者凭证'); return }
    setUploading(true)
    try {
      const uploaded = await api.uploadStrategyPackage(agentId, token, file)
      setPackages(await api.listStrategyPackages(agentId, token)); goTab('packages')
      onPackageUploaded?.(uploaded)
    } catch (reason) { onError(reason instanceof Error ? reason.message : '策略包上传失败') }
    finally { setUploading(false) }
  }

  const loadPackages = async () => {
    if (!agentId || !token) { onError('需要 Agent 和开发者凭证'); return }
    try { setPackages(await api.listStrategyPackages(agentId, token)); goTab('packages') }
    catch (reason) { onError(reason instanceof Error ? reason.message : '无法读取私密策略包') }
  }

  const save = async () => {
    if (!workflow) return
    if (!agentId) { setSaveNotice({ tone: 'error', text: '请选择自己的 Agent；没有 Agent 时请先在 QuantJudge 发布页创建。' }); return }
    if (!token) { setSaveNotice({ tone: 'error', text: '请输入创建 Agent 时获得的开发者凭证。凭证只保存在当前页面内存。' }); return }
    if (!validation?.valid) { setSaveNotice({ tone: 'error', text: '等待编译完成，并修复所有 DAG 或硬风控错误后再保存。' }); return }
    setSaving(true)
    try {
      const record = await api.saveStudioWorkflow(agentId, token, workflow, '工作室可视化修订')
      setDirty(false)
      setSaveNotice({ tone: 'success', text: `已保存 r${record.revision} · ${record.graph_hash.slice(0, 12)}…` })
      onWorkflowSaved?.(record)
    }
    catch (reason) {
      const message = reason instanceof Error ? reason.message : '工作流保存失败'
      setSaveNotice({ tone: 'error', text: `${message}；请检查 Agent、凭证和网络后重试。` })
    }
    finally { setSaving(false) }
  }

  const prepareDataset = async () => {
    setProofBusy(true)
    try { setZkDataset(await api.createZkMarketDataset(assetSymbol, assetClass, interval as import('../types').Interval)) }
    catch (reason) { onError(reason instanceof Error ? reason.message : '可信市场数据集生成失败') }
    finally { setProofBusy(false) }
  }

  const uploadProof = async (file: File) => {
    const profile = zkProfiles.find((item) => item.status === 'active')
    if (!agentId || !token) { onError('上传证明前需要选择 Agent 并填写开发者凭证'); return }
    if (!profile?.verifier_ready) { onError('生产 verifier 尚未构建或 profile 未激活'); return }
    setProofBusy(true)
    try { setZkProof(await api.uploadZkProof(agentId, token, profile.id, file)) }
    catch (reason) { onError(reason instanceof Error ? reason.message : 'ZKP receipt 验证失败') }
    finally { setProofBusy(false) }
  }

  const publishProof = async () => {
    if (!agentId || !token || !zkProof) return
    setProofBusy(true)
    try {
      const report = await api.publishZkReport(agentId, token, zkProof.id)
      setPublishedProofReport(`${report.id} · ${report.evidence_level ?? 'zk_verified'}`)
    } catch (reason) { onError(reason instanceof Error ? reason.message : 'ZKP 报告发布失败') }
    finally { setProofBusy(false) }
  }

  if (!workflow) return <div className="qjs-loading"><Cpu className="spin" size={22} />加载策略开发套件…</div>
  const ordered = orderNodes(workflow.nodes)

  return <section className={`qjs-shell ${embedded ? 'is-embedded' : ''}`}>
    <header className="qjs-toolbar">
      {embedded ? <div className="qjs-embedded-context"><Fingerprint size={14} aria-hidden="true" /><span><strong>私密编译会话</strong><small>源码、提示词和凭证不进入公开跑分结果</small></span><em className={dirty ? 'is-dirty' : validation?.valid ? 'is-valid' : ''}>{dirty ? '未保存' : validation?.valid ? '已编译' : '校验中'}</em></div> : <><div className="qjs-studio-title"><Workflow size={16} /><span><strong>STRATEGY STUDIO</strong><small>.qstrategy 私密策略与 AI 工作流</small></span></div><nav><button className={tab === 'workflow' ? 'is-active' : ''} onClick={() => goTab('workflow')}><GitBranch size={13} />工作流</button><button className={tab === 'packages' ? 'is-active' : ''} onClick={loadPackages}><FileArchive size={13} />策略包</button><button className={tab === 'proof' ? 'is-active' : ''} onClick={() => goTab('proof')}><Fingerprint size={13} />ZKP 证明</button><button className={tab === 'sdk' ? 'is-active' : ''} onClick={() => goTab('sdk')}><Code2 size={13} />SDK 与格式</button></nav></>}
      <form className="qjs-auth" onSubmit={(event) => { event.preventDefault(); void save() }}>
        <input className="qjs-hidden-username" name="username" autoComplete="username" value={agentId} readOnly tabIndex={-1} aria-hidden="true" />
        <div className={`qjs-save-feedback ${saveNotice ? `is-${saveNotice.tone}` : ''}`} aria-live="polite">{saveNotice?.text ?? (agents.length ? '选择 Agent 并输入凭证后保存不可变修订' : '尚无自有 Agent · 先到 QuantJudge 创建')}</div>
        <label className="qjs-agent-select"><span>AGENT</span><select name="agent-id" autoComplete="off" value={agentId} onChange={(event) => { setAgentId(event.target.value); setSaveNotice(null) }} aria-label="选择保存工作流的 Agent"><option value="">{agents.length ? '选择我的 Agent' : '暂无可用 Agent'}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown size={12} aria-hidden="true" /></label>
        <label className="qjs-token"><KeyRound size={12} aria-hidden="true" /><input name="developer-token" type="password" autoComplete="current-password" spellCheck={false} value={token} onChange={(event) => { setToken(event.target.value); setSaveNotice(null) }} placeholder="开发者凭证…" aria-label="开发者凭证" /></label>
        <button className="qjs-save" type="submit" disabled={saving}><Save size={13} />{saving ? '保存中…' : dirty ? '保存修订' : '保存版本'}</button>
      </form>
    </header>

    {tab === 'workflow' ? <div className="qjs-workflow-layout">
      <aside className="qjs-library">
        <section><div className="qjs-side-title"><span>策略树干<em>TEMPLATES</em></span><small>替换当前草稿</small></div>{templates.map((template) => <button className={`qjs-template ${activeTemplateId === template.id ? 'is-active' : ''}`} aria-pressed={activeTemplateId === template.id} key={template.id} onClick={() => loadTemplate(template)}><span><strong>{template.name}</strong><small>{template.description}</small></span>{activeTemplateId === template.id ? <Check size={12} /> : <Play size={11} />}</button>)}</section>
        <section><div className="qjs-side-title"><span>AI 职责<em>INSERT ROLE</em></span><small>按安全阶段插入</small></div>{spec?.ai_roles.map((role) => <button className="qjs-role" key={role.id} onClick={() => addAI(role.id)}><Bot size={13} /><span><strong>{role.label}</strong><small>{role.allowed_authority.map((item) => authorityLabels[item]).join(' / ')}</small></span><Plus size={11} /></button>)}</section>
        <div className="qjs-safety-note"><LockKeyhole size={14} /><span><strong>硬风控不可被 AI 绕过</strong><small>无论模型权限多高，订单都必须经过确定性限额。</small></span></div>
      </aside>

      <main className="qjs-canvas">
        <header><div><Field label="工作流 ID" hint="版本内唯一"><input name="workflow-id" autoComplete="off" spellCheck={false} value={workflow.id} onChange={(event) => patchWorkflow({ id: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })} /></Field><Field label="工作流名称"><input name="workflow-name" autoComplete="off" value={workflow.name} onChange={(event) => patchWorkflow({ name: event.target.value })} /></Field></div><ValidationPanel validation={validation} /></header>
        <div className="qjs-flow">
          <div className="qjs-flow-summary"><span><strong>{ordered.length}</strong> 个节点</span><span><strong>{ordered.filter((node) => node.type === 'ai_guard').length}</strong> 个 AI 职责</span><span><ShieldCheck size={12} /><strong>{ordered.filter((node) => node.type === 'risk_gate').length}</strong> 道硬风控</span><code>数据 → 信号 → 仓位 → 风控 → 执行 → 证明</code></div>
          {ordered.map((node, index) => <div className="qjs-flow-row" key={node.id}>
            <button className={`qjs-node type-${node.type} ${selectedId === node.id ? 'is-selected' : ''}`} aria-pressed={selectedId === node.id} onClick={() => { setSelectedId(node.id); setRemoveArmed(false) }}>
              <i>{node.type === 'ai_guard' ? <Bot size={15} /> : node.type === 'risk_gate' ? <ShieldCheck size={15} /> : node.type === 'strategy' ? <Braces size={15} /> : node.type === 'audit' ? <Fingerprint size={15} /> : <Box size={14} />}</i>
              <span><em>{typeMeta[node.type]?.tag}</em><strong>{node.label}</strong><small>{typeMeta[node.type]?.hint}<code>#{node.id}</code></small></span>
              {node.type === 'ai_guard' ? <b>{authorityLabels[node.config.authority as StudioAIAuthority]}</b> : null}
              {node.type === 'risk_gate' ? <b className="locked"><LockKeyhole size={10} /> FINAL GATE</b> : null}
              <SlidersHorizontal size={13} />
            </button>
            {index < ordered.length - 1 ? <div className="qjs-connector"><i /><ChevronDown size={12} /><code>{workflow.edges.find((edge) => edge.source === node.id)?.condition ?? 'PASS'}</code></div> : null}
          </div>)}
        </div>
        <footer>{validation?.errors.map((error) => <span className="is-error" key={error}><X size={11} />{error}</span>)}{validation?.warnings.map((warning) => <span key={warning}><CircleAlert size={11} />{warning}</span>)}</footer>
      </main>

      <aside className="qjs-inspector">
        {selected ? <><header><div><small>{typeMeta[selected.type]?.tag} · #{selected.id}</small><strong>{selected.label}</strong></div>{selected.type === 'ai_guard' ? <div className="qjs-inspector-actions">{removeArmed ? <button className="is-confirm" onClick={removeSelected}>确认删除</button> : null}<button aria-label={removeArmed ? '取消删除 AI 节点' : '删除 AI 节点'} onClick={() => setRemoveArmed((armed) => !armed)} title={removeArmed ? '取消删除' : '删除 AI 节点'}>{removeArmed ? <X size={14} /> : <Trash2 size={14} />}</button></div> : <ShieldCheck size={16} aria-label="受工作流校验保护" />}</header>
          <section><div className="qjs-inspector-title">基础信息 <em>BASIC</em></div><Field label="节点名称"><input name="node-label" autoComplete="off" value={selected.label} onChange={(event) => patchSelected({ label: event.target.value })} /></Field><Field label="节点 ID" hint="版本内稳定"><input name="node-id" value={selected.id} disabled /></Field></section>
          {selected.type === 'ai_guard' ? <><section><div className="qjs-inspector-title">AI 责任与权限 <em>RESPONSIBILITY</em></div><Field label="责任"><select name="ai-role" value={selected.config.role as string} onChange={(event) => { const role = event.target.value as StudioAIRole; const allowed = spec?.ai_roles.find((item) => item.id === role)?.allowed_authority ?? ['advisory']; patchSelected({}, { role, authority: allowed[0] }) }}>{spec?.ai_roles.map((role) => <option value={role.id} key={role.id}>{role.label}</option>)}</select></Field><Field label="权限边界"><select name="ai-authority" value={selected.config.authority as string} onChange={(event) => patchSelected({}, { authority: event.target.value })}>{allowedAuthority.map((item) => <option value={item} key={item}>{authorityLabels[item]}</option>)}</select></Field>{selected.config.authority === 'bounded_adjustment' ? <Field label="最大调整" hint="BPS"><input name="max-adjustment-bps" type="number" inputMode="numeric" min="1" max="2000" value={selected.config.max_adjustment_bps as number ?? 100} onChange={(event) => patchSelected({}, { max_adjustment_bps: Number(event.target.value) })} /></Field> : null}</section>
            <section><div className="qjs-inspector-title">模型契约 <em>MODEL CONTRACT</em></div><Field label="Provider 引用" hint="不存密钥"><input name="provider-reference" autoComplete="off" spellCheck={false} value={selected.config.provider_ref as string} onChange={(event) => patchSelected({}, { provider_ref: event.target.value })} /></Field><Field label="超时" hint="ms"><input name="model-timeout" type="number" inputMode="numeric" min="100" max="60000" value={selected.config.timeout_ms as number} onChange={(event) => patchSelected({}, { timeout_ms: Number(event.target.value) })} /></Field><Field label="失败回退"><select name="on-model-error" value={selected.config.on_error as string} onChange={(event) => patchSelected({}, { on_error: event.target.value })}><option value="deny">拒绝交易（fail closed）</option><option value="use_baseline">使用基准策略输出</option><option value="skip">跳过本建议节点</option></select></Field><Field label="私密指令" hint="加密存储"><textarea name="private-instructions" autoComplete="off" value={selected.config.instructions as string ?? ''} onChange={(event) => patchSelected({}, { instructions: event.target.value })} /></Field></section></> : null}
          {selected.type === 'strategy' ? <section><div className="qjs-inspector-title">私密制品 <em>PRIVATE ARTIFACT</em></div><Field label="绑定策略包" hint="按 content hash 锁定"><select name="strategy-package" value={workflow.package_id ?? ''} onChange={(event) => patchWorkflow({ package_id: event.target.value || null })}><option value="">尚未绑定</option>{packages.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></Field><button className="qjs-inspector-action" onClick={loadPackages}><FileArchive size={12} />验证凭证并读取策略包</button><small className="qjs-help">运行与审计回执将同时锁定 package content hash 和 workflow graph hash。</small></section> : null}
          {selected.type === 'risk_gate' ? <section className="qjs-risk-fields"><div className="qjs-inspector-title">确定性限额 <em>HARD LIMITS</em></div>{[
            ['max_gross_exposure', '总暴露'], ['max_single_position', '单标的仓位'], ['max_daily_loss', '日损失'], ['max_drawdown', '回撤停机'], ['max_participation_rate', '成交参与率'],
          ].map(([key, label]) => <Field label={label} hint="0–1" key={key}><input name={key} type="number" inputMode="decimal" min="0.0001" max="1" step="0.01" value={selected.config[key] as number} onChange={(event) => patchSelected({}, { [key]: Number(event.target.value) })} /></Field>)}</section> : null}
          {selected.type === 'execution' ? <section><div className="qjs-inspector-title">执行模型 <em>EXECUTION</em></div><Field label="手续费率"><input name="execution-commission" type="number" inputMode="decimal" min="0" max="0.1" step="0.0001" value={selected.config.commission as number ?? 0} onChange={(event) => patchSelected({}, { commission: Number(event.target.value) })} /></Field><Field label="滑点率"><input name="execution-slippage" type="number" inputMode="decimal" min="0" max="0.1" step="0.0001" value={selected.config.slippage as number ?? 0} onChange={(event) => patchSelected({}, { slippage: Number(event.target.value) })} /></Field></section> : null}
          <div className="qjs-node-contract"><Check size={12} /><span><strong>输出将被结构化校验</strong><small>运行时记录输入摘要、决策、回退与耗时。</small></span></div>
        </> : null}
      </aside>
    </div> : null}

    {tab === 'packages' ? <div className="qjs-packages">
      <header><div><strong>私密策略包</strong><small>上传后静态校验并使用 AES-256-GCM 加密落盘；API 进程不执行用户代码。</small></div><button onClick={() => fileRef.current?.click()}><UploadCloud size={14} />选择 .qstrategy</button></header>
      <input ref={fileRef} hidden type="file" accept=".qstrategy,.zip" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
      <div className={`qjs-dropzone ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file) upload(file) }}><FileArchive size={27} /><strong>{uploading ? '正在进行结构、入口与安全校验…' : '拖入 .qstrategy 策略包'}</strong><span>最大 10 MB · 解压最大 50 MB · 禁止凭证、链接与可执行二进制</span></div>
      <div className="qjs-package-list">{packages.map((item) => <article key={item.id}><span><PackageCheck size={18} /></span><div><strong>{item.name} <em>v{item.version}</em></strong><small>{item.strategy_key} · {item.language} · {item.file_count} files</small></div><code>{item.content_hash.slice(0, 12)}…</code><b><LockKeyhole size={11} /> PRIVATE</b><time>{new Date(item.created_at).toLocaleString('zh-CN')}</time>{item.warnings.length ? <p>{item.warnings.join(' · ')}</p> : null}</article>)}{!packages.length ? <div className="qjs-empty"><FileArchive size={24} />选择 Agent 并输入凭证后读取，或上传第一个策略包。</div> : null}</div>
    </div> : null}

    {tab === 'proof' ? <div className="qjs-proof">
      <header><div><strong>零知识证明发布流水线</strong><small>本地生成 witness 与 receipt；平台只验证公开 journal，不接收策略参数、salt、逐笔决策或完整净值。</small></div><span className={zkProfiles.some((item) => item.verifier_ready) ? 'is-ready' : 'is-blocked'}><ShieldCheck size={13} />{zkProfiles.some((item) => item.verifier_ready) ? 'PRODUCTION VERIFIER READY' : 'VERIFIER NOT BUILT'}</span></header>
      <section className="qjs-proof-profile">
        {zkProfiles.map((profile) => <article key={profile.id}><div><Fingerprint size={20} /><span><em>REGISTERED IMAGE</em><strong>{profile.id}</strong><code>{profile.image_id}</code></span></div><dl><div><dt>证明系统</dt><dd>{profile.proof_system}</dd></div><div><dt>覆盖范围</dt><dd>{profile.scope}</dd></div><div><dt>Guest</dt><dd>v{profile.guest_version}</dd></div><div><dt>状态</dt><dd>{profile.status}</dd></div></dl><p><ShieldCheck size={12} />证明：{profile.privacy_scope.join('；')}</p><p className="is-warning"><CircleAlert size={12} />不证明：{profile.unsupported.join('、')}</p></article>)}
        {!zkProfiles.length ? <div className="qjs-empty"><CircleAlert size={20} />尚无已激活的 proof profile；运行 zkvm/scripts/build.sh 后才允许上传。</div> : null}
      </section>
      <ol className="qjs-proof-steps">
        <li className={zkDataset ? 'is-done' : ''}><span>01</span><div><strong>锁定可信市场数据</strong><small>{assetSymbol} · {interval} · 平台公开数据根</small>{zkDataset ? <code>{zkDataset.market_data_hash}</code> : null}</div><button disabled={proofBusy} onClick={prepareDataset}>{zkDataset ? '重新登记' : '生成数据集'}</button></li>
        <li><span>02</span><div><strong>在开发者设备创建私有 witness</strong><small>参数、salt 与 nullifier nonce 只保留在本地；inspect 输出的 strategy_commitment 用于创建 Agent</small></div><code>atlas-zkvm inspect --witness witness.json</code></li>
        <li><span>03</span><div><strong>本地生成生产证明</strong><small>disable-dev-mode 已强制启用，禁止伪 receipt</small></div><code>zkvm/target/release/atlas-zkvm prove --witness witness.json --receipt proof.r0</code></li>
        <li className={zkProof ? 'is-done' : ''}><span>04</span><div><strong>上传并独立验证 receipt</strong><small>固定 image ID · 45 秒 fail-closed · 最大 16 MB</small>{zkProof ? <code>{zkProof.proof_hash}</code> : null}</div><button disabled={proofBusy || !zkDataset} onClick={() => proofFileRef.current?.click()}>{proofBusy ? '处理中…' : '选择 proof.r0'}</button><input ref={proofFileRef} hidden type="file" accept=".r0,.bin" onChange={(event) => event.target.files?.[0] && uploadProof(event.target.files[0])} /></li>
        <li className={zkProof ? '' : 'is-locked'}><span>05</span><div><strong>发布 ZKP 跑分回执</strong><small>指标和抽样曲线直接来自已验证 journal；proof/nullifier 只能使用一次</small></div><button disabled={proofBusy || !zkProof} onClick={publishProof}>发布 QuantJudge</button></li>
        <li><span>06</span><div><strong>外部钱包锚定 Supervisor</strong><small>链上仅保存回执、证明、公开输入和 nullifier 的哈希；Supervisor 源码保持只读</small></div><code>ATLASZK2 · receipt · proof · public-input · nullifier</code></li>
      </ol>
      {publishedProofReport ? <div className="qjs-proof-published"><ShieldCheck size={15} /><span><strong>ZKP 报告已发布</strong><code>{publishedProofReport}</code></span></div> : null}
      <aside className="qjs-proof-boundary"><LockKeyhole size={16} /><div><strong>隐私边界不是营销标签</strong><p>当前 profile 真正覆盖确定性、long-only、下一根 K 线开盘成交的 SMA 回测。Python 策略、AI/LLM 节点和实盘成交仍可开发，但在有对应 zkVM/zkML/交易所签名或 TEE 证明前，不会显示“ZKP 已验证”。</p>{zkDataset ? <small>{zkDataset.limitation}</small> : null}</div></aside>
    </div> : null}

    {tab === 'sdk' ? <div className="qjs-sdk">
      <header><div><strong>一种原生包，三条生产路径</strong><small>研究附件与实盘可执行物分离，不把 Notebook 假装成生产策略。</small></div><code>.qstrategy / atlas.strategy/v1</code></header>
      <div className="qjs-format-grid">{spec?.languages.map((language) => <article key={language.id} className={language.production ? '' : 'is-import'}><span>{language.id === 'python' ? <Code2 size={19} /> : language.id === 'json_dsl' ? <Braces size={19} /> : language.id === 'remote_runner' ? <Cpu size={19} /> : <FileArchive size={19} />}</span><div><em>{language.production ? 'PRODUCTION' : 'IMPORT / RESEARCH'}</em><strong>{language.label}</strong><small>{language.execution}</small></div></article>)}</div>
      <section className="qjs-contract"><div><strong>strategy.json</strong><small>版本、能力权限、参数 Schema、AI 插入点、研究门槛</small></div><i /><div><strong>BaseStrategy</strong><small>只读 StrategyContext → TargetPosition[]，网络与时钟由 Runner 注入</small></div><i /><div><strong>Workflow DAG</strong><small>AI 契约 → 硬风控 → 执行成本 → 审计承诺</small></div></section>
      <div className="qjs-code"><header><span>strategy.py</span><em>PYTHON SDK</em></header><pre>{`from atlas_strategy_sdk import BaseStrategy, StrategyContext, TargetPosition\n\nclass MyAlpha(BaseStrategy):\n    def generate_targets(self, ctx: StrategyContext):\n        bars = ctx.history("BTC-USD", 61)  # closed bars only\n        momentum = bars[-1].close / bars[0].close - 1\n        return [TargetPosition("BTC-USD", 0.2 if momentum > 0 else 0,\n                               0.8, "MOMENTUM_60")]`}</pre></div>
      <div className="qjs-sdk-note"><Sparkles size={15} /><span><strong>路径在仓库中已可用</strong><small>sdk/python · examples/strategies · docs/STRATEGY_DEVELOPMENT.md · tools/package_strategy.py</small></span></div>
    </div> : null}
  </section>
}
