import { useCallback, useEffect, useRef, useState } from 'react'
import { PrivateExecutionPanel } from './PrivateExecutionPanel'
import { GuidedWorkflow } from './GuidedWorkflow'
import './guided-strategy.css'
import type { ReactNode } from 'react'
import {
  Braces, Check, ChevronDown, CircleAlert, Code2, Cpu, FileArchive,
  Fingerprint, GitBranch, KeyRound, LockKeyhole, PackageCheck,
  Save, ShieldCheck, Sparkles, Trash2, Workflow, X,
} from 'lucide-react'
import { api } from '../api'
import { LabConfirmDialog } from './LabConfirmDialog'
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
  onWorkflowSaved?: (record: StudioWorkflowRecord, developerToken: string) => void
  onEditRules?: () => void
  onDraftChange?: (dirty: boolean) => void
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
  if (!validation) return <div className="qjs-validation is-pending" aria-live="polite"><Cpu className="spin" size={15} /><span><strong>正在检查流程…</strong><small>检查步骤顺序、AI 权限与风控路径</small></span></div>
  return <div className={`qjs-validation ${validation.valid ? 'is-valid' : 'is-invalid'}`}>
    {validation.valid ? <ShieldCheck size={16} /> : <CircleAlert size={16} />}
    <span><strong>{validation.valid ? '结构校验通过' : `校验未通过 · ${validation.errors.length} 项`}</strong><small>{validation.valid ? `${validation.summary.nodes} 个节点 · ${validation.summary.ai_nodes} 个 AI 职责 · 风控路径完整` : validation.errors[0]}</small></span>
  </div>
}

export function QuantStrategyStudio({
  onError, activeTab, embedded = false, onTabChange, onWorkflowSaved, onEditRules, onDraftChange,
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
  const [validationError, setValidationError] = useState('')
  const [agentId, setAgentId] = useState('')
  const [token, setToken] = useState('')
  const [packages, setPackages] = useState<StrategyPackageRecord[]>([])
  const [saving, setSaving] = useState(false)
  const [zkProfiles, setZkProfiles] = useState<import('../types').ZkProfile[]>([])
  const [proofProfileId, setProofProfileId] = useState('atlas_program_backtest_risc0_v2')
  const [zkDataset, setZkDataset] = useState<import('../types').ZkMarketDataset | null>(null)
  const [zkProof, setZkProof] = useState<import('../types').ZkProofRecord | null>(null)
  const [publishedProofReport, setPublishedProofReport] = useState<string | null>(null)
  const [proofBusy, setProofBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [activeTemplateId, setActiveTemplateId] = useState('')
  const [saveNotice, setSaveNotice] = useState<{ tone: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [removeArmed, setRemoveArmed] = useState(false)
  const [pendingTemplate, setPendingTemplate] = useState<StudioTemplate | null>(null)
  const [loadingPackages, setLoadingPackages] = useState(false)
  const proofFileRef = useRef<HTMLInputElement>(null)
  const validationRequest = useRef(0)
  const draftRevision = useRef(0)
  const privateSession = useRef(0)
  const packageRequest = useRef(0)
  const savingRef = useRef(false)
  const proofBusyRef = useRef(false)

  const markEdited = useCallback(() => {
    draftRevision.current += 1
    validationRequest.current += 1
    setValidation(null)
    setValidationError('')
    setDirty(true)
    setSaveNotice(null)
    setActiveTemplateId('')
  }, [])

  useEffect(() => {
    let active = true
    Promise.all([api.getStudioSpec(), api.getStudioTemplates(), api.listQuantAgents(), api.listZkProfiles()]).then(([nextSpec, nextTemplates, nextAgents, nextProfiles]) => {
      if (!active) return
      setSpec(nextSpec); setTemplates(nextTemplates); setAgents(nextAgents.filter((agent) => !agent.is_demo))
      setZkProfiles(nextProfiles)
      setProofProfileId((current) => nextProfiles.some((profile) => profile.id === current) ? current : nextProfiles[0]?.id ?? current)
      if (nextTemplates[0] && draftRevision.current === 0) {
        const first = cloneWorkflow(nextTemplates[0].workflow)
        if (first.name === '专业基线树干') first.name = '我的交易策略'
        setWorkflow(first); setSelectedId(first.nodes[0]?.id ?? ''); setActiveTemplateId(nextTemplates[0].id)
      }
    }).catch((reason) => { if (active) onError(reason instanceof Error ? reason.message : '策略工作室加载失败') })
    return () => { active = false }
  }, [onError])

  useEffect(() => () => { privateSession.current += 1; validationRequest.current += 1 }, [])
  useEffect(() => { onDraftChange?.(dirty) }, [dirty, onDraftChange])

  useEffect(() => {
    if (!workflow) return
    const requestId = ++validationRequest.current
    const timer = window.setTimeout(() => {
      api.validateStudioWorkflow(workflow).then((nextValidation) => {
        if (requestId === validationRequest.current) setValidation(nextValidation)
      }).catch((reason) => {
        if (requestId !== validationRequest.current) return
        const message = reason instanceof Error ? reason.message : '工作流校验失败'
        setValidation(null); setValidationError(message); onError(message)
      })
    }, 280)
    return () => { window.clearTimeout(timer); validationRequest.current += 1 }
  }, [onError, workflow])

  useEffect(() => {
    if (!dirty) return undefined
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const selected = workflow?.nodes.find((node) => node.id === selectedId) ?? null
  const allowedAuthority = selected?.type === 'ai_guard'
    ? spec?.ai_roles.find((role) => role.id === selected.config.role)?.allowed_authority ?? [] : []

  const loadTemplate = (template: StudioTemplate) => {
    const next = cloneWorkflow(template.workflow)
    draftRevision.current += 1
    validationRequest.current += 1
    setWorkflow(next); setSelectedId(next.nodes[0]?.id ?? ''); setValidation(null); setValidationError('')
    setActiveTemplateId(template.id); setDirty(true); setRemoveArmed(false)
    setPendingTemplate(null)
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

  const clearPrivateSession = () => {
    // Every private response belongs to the credentials used when it started.
    privateSession.current += 1
    packageRequest.current += 1
    savingRef.current = false; proofBusyRef.current = false
    setSaving(false); setLoadingPackages(false); setProofBusy(false)
    setPackages([]); setZkProof(null); setPublishedProofReport(null); setSaveNotice(null)
    if (proofFileRef.current) proofFileRef.current.value = ''
    if (workflow?.package_id) {
      markEdited()
      setWorkflow((current) => current ? { ...current, package_id: null } : current)
    }
  }
  const changeAgent = (next: string) => {
    clearPrivateSession()
    setAgentId(next); setToken(''); setZkDataset(null)
  }

  const loadPackages = async () => {
    if (!agentId || !token) { onError('需要 Agent 和开发者凭证'); return }
    const session = privateSession.current
    const request = ++packageRequest.current
    setLoadingPackages(true)
    try {
      const records = await api.listStrategyPackages(agentId, token)
      if (session !== privateSession.current || request !== packageRequest.current) return
      setPackages(records); goTab('packages')
    }
    catch (reason) { if (session === privateSession.current && request === packageRequest.current) onError(reason instanceof Error ? reason.message : '无法读取私密策略包') }
    finally { if (session === privateSession.current && request === packageRequest.current) setLoadingPackages(false) }
  }

  const save = async () => {
    if (!workflow || savingRef.current) return
    if (!agentId) { setSaveNotice({ tone: 'error', text: '请选择自己的 Agent；没有 Agent 时请先在 QuantJudge 发布页创建。' }); return }
    if (!token) { setSaveNotice({ tone: 'error', text: '请输入创建 Agent 时获得的开发者凭证。凭证只保存在当前页面内存。' }); return }
    if (!validation?.valid) { setSaveNotice({ tone: 'error', text: '等待结构校验完成，并修复所有流程或硬风控错误后再保存。' }); return }
    const revision = draftRevision.current
    const session = privateSession.current
    savingRef.current = true
    setSaving(true)
    try {
      const record = await api.saveStudioWorkflow(agentId, token, workflow, '工作室可视化修订')
      if (session !== privateSession.current) return
      const unchanged = draftRevision.current === revision
      if (unchanged) setDirty(false)
      setSaveNotice({ tone: 'success', text: unchanged ? `已保存 r${record.revision} · ${record.graph_hash.slice(0, 12)}…` : `已保存提交时的版本 r${record.revision}；你在保存期间的新修改仍未保存。` })
      onWorkflowSaved?.(record, token)
    }
    catch (reason) {
      const message = reason instanceof Error ? reason.message : '工作流保存失败'
      if (session === privateSession.current) setSaveNotice({ tone: 'error', text: `${message}；草稿已保留，请检查 Agent、凭证和网络后重试。` })
    }
    finally { if (session === privateSession.current) { savingRef.current = false; setSaving(false) } }
  }

  const prepareDataset = async () => {
    if (proofBusyRef.current) return
    const session = privateSession.current
    proofBusyRef.current = true
    setProofBusy(true)
    try {
      const dataset = await api.createZkMarketDataset(assetSymbol, assetClass, interval as import('../types').Interval)
      if (session === privateSession.current) { setZkDataset(dataset); setZkProof(null); setPublishedProofReport(null) }
    }
    catch (reason) { if (session === privateSession.current) onError(reason instanceof Error ? reason.message : '可信市场数据集生成失败') }
    finally { if (session === privateSession.current) { proofBusyRef.current = false; setProofBusy(false) } }
  }

  const uploadProof = async (file: File) => {
    if (proofBusyRef.current) return
    const profile = zkProfiles.find((item) => item.id === proofProfileId && item.status === 'active')
    if (!agentId || !token) { onError('上传证明前需要选择 Agent 并填写开发者凭证'); return }
    if (!profile?.verifier_ready) { onError('生产 verifier 尚未构建或 profile 未激活'); return }
    const session = privateSession.current
    proofBusyRef.current = true
    setProofBusy(true)
    try {
      const proof = await api.uploadZkProof(agentId, token, profile.id, file)
      if (session === privateSession.current) { setZkProof(proof); setPublishedProofReport(null) }
    }
    catch (reason) { if (session === privateSession.current) onError(reason instanceof Error ? reason.message : 'ZKP receipt 验证失败') }
    finally { if (session === privateSession.current) { proofBusyRef.current = false; setProofBusy(false) } }
  }

  const publishProof = async () => {
    if (!agentId || !token || !zkProof || proofBusyRef.current) return
    const session = privateSession.current
    proofBusyRef.current = true
    setProofBusy(true)
    try {
      const report = await api.publishZkReport(agentId, token, zkProof.id)
      if (session === privateSession.current) setPublishedProofReport(`${report.id} · ${report.evidence_level ?? 'zk_verified'}`)
    } catch (reason) { if (session === privateSession.current) onError(reason instanceof Error ? reason.message : 'ZKP 报告发布失败') }
    finally { if (session === privateSession.current) { proofBusyRef.current = false; setProofBusy(false) } }
  }

  if (!workflow) return <div className="qjs-loading"><Cpu className="spin" size={22} />加载策略开发套件…</div>

  return <section className={`qjs-shell ${embedded ? 'is-embedded' : ''}`}>
    {pendingTemplate ? <LabConfirmDialog title="替换未保存的工作流？" description={`载入“${pendingTemplate.name}”会替换当前节点、配置和私密指令。取消后可以先保存当前修订。`} confirmLabel="放弃草稿并载入" destructive onCancel={() => setPendingTemplate(null)} onConfirm={() => loadTemplate(pendingTemplate)} /> : null}
    <header className="qjs-toolbar guided-toolbar">
      {embedded ? <div className="qjs-embedded-context"><Fingerprint size={14} aria-hidden="true" /><span><strong>私密工作区</strong><small>提示词和凭证不进入公开结果</small></span><em className={dirty ? 'is-dirty' : validation?.valid ? 'is-valid' : ''}>{validationError ? '检查失败' : dirty ? '未保存' : validation?.valid ? '结构有效' : '校验中'}</em></div> : <><div className="qjs-studio-title"><Workflow size={16} /><span><strong>STRATEGY STUDIO</strong><small>可视化策略与 AI 积木</small></span></div><nav><button className={tab === 'workflow' ? 'is-active' : ''} onClick={() => goTab('workflow')}><GitBranch size={13} />工作流</button><button className={tab === 'packages' ? 'is-active' : ''} onClick={loadPackages}><FileArchive size={13} />策略包</button><button className={tab === 'proof' ? 'is-active' : ''} onClick={() => goTab('proof')}><Fingerprint size={13} />ZKP 证明</button><button className={tab === 'sdk' ? 'is-active' : ''} onClick={() => goTab('sdk')}><Code2 size={13} />SDK 与格式</button></nav></>}
      <details className="guided-save-settings" open={tab !== 'workflow' || undefined}><summary><Save size={14} />保存与私密账户设置</summary><form className="qjs-auth" onSubmit={(event) => { event.preventDefault(); void save() }}>
        <input className="qjs-hidden-username" name="username" autoComplete="username" value={agentId} readOnly tabIndex={-1} aria-hidden="true" />
        <div className={`qjs-save-feedback ${saveNotice ? `is-${saveNotice.tone}` : ''}`} aria-live="polite">{saveNotice?.text ?? (agents.length ? '选择 Agent 并输入凭证后保存不可变修订' : '尚无自有 Agent · 先到 QuantJudge 创建')}</div>
        <label className="qjs-agent-select"><span>AGENT</span><select name="agent-id" autoComplete="off" value={agentId} onChange={(event) => changeAgent(event.target.value)} aria-label="选择保存工作流的 Agent"><option value="">{agents.length ? '选择我的 Agent' : '暂无可用 Agent'}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown size={12} aria-hidden="true" /></label>
        <label className="qjs-token"><KeyRound size={12} aria-hidden="true" /><input name="developer-token" type="password" autoComplete="current-password" spellCheck={false} value={token} onChange={(event) => { clearPrivateSession(); setToken(event.target.value) }} placeholder="开发者凭证…" aria-label="开发者凭证" /></label>
        <button className="qjs-save" type="submit" disabled={saving}><Save size={13} />{saving ? '保存中…' : dirty ? '保存修订' : '保存版本'}</button>
      </form></details>
    </header>

    {tab === 'workflow' ? <GuidedWorkflow workflow={workflow} selectedId={selectedId} templates={templates} activeTemplateId={activeTemplateId} saving={saving}
      availableRoles={spec?.ai_roles.map((role) => role.id) ?? []}
      onTemplate={(template) => dirty ? setPendingTemplate(template) : loadTemplate(template)}
      onSelect={(node) => { setSelectedId(node.id); setRemoveArmed(false) }} onAddAI={addAI}
      onName={(name) => patchWorkflow({ name })} onEditRules={onEditRules}
      validation={validationError ? <div className="guided-validation-error" role="alert"><strong>流程检查失败</strong><p>{validationError}</p><small>请修正配置后重试；修改任意字段会重新检查。</small></div> : <ValidationPanel validation={validation} />}
      diagnostics={<div className="guided-diagnostics">{validation?.errors.map((error) => <p role="alert" key={error}>{error}</p>)}{validation?.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
      inspector={      <div className="guided-inspector">
        {selected ? <><header><div><small>{selected.type === 'ai_guard' ? 'AI 积木 · 编排预览' : '步骤设置'}</small><strong>{selected.label}</strong></div>{selected.type === 'ai_guard' ? <div className="qjs-inspector-actions">{removeArmed ? <button className="is-confirm" onClick={removeSelected}>确认删除</button> : null}<button aria-label={removeArmed ? '取消删除 AI 节点' : '删除 AI 节点'} onClick={() => setRemoveArmed((armed) => !armed)} title={removeArmed ? '取消删除' : '删除 AI 节点'}>{removeArmed ? <X size={14} /> : <Trash2 size={14} />}</button></div> : <ShieldCheck size={16} aria-label="受工作流校验保护" />}</header>
          <section><div className="qjs-inspector-title">命名这个积木</div><Field label="节点名称"><input name="node-label" autoComplete="off" value={selected.label} onChange={(event) => patchSelected({ label: event.target.value })} /></Field><details className="guided-advanced"><summary>高级设置</summary><Field label="节点 ID"><input name="node-id" value={selected.id} disabled /></Field><Field label="工作流 ID"><input value={workflow.id} onChange={(event) => patchWorkflow({ id: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })} /></Field></details></section>
          {selected.type === 'ai_guard' ? <><section><div className="qjs-inspector-title">让 AI 做什么</div><Field label="责任"><select name="ai-role" value={selected.config.role as string} onChange={(event) => { const role = event.target.value as StudioAIRole; const allowed = spec?.ai_roles.find((item) => item.id === role)?.allowed_authority ?? ['advisory']; patchSelected({}, { role, authority: allowed[0] }) }}>{spec?.ai_roles.map((role) => <option value={role.id} key={role.id}>{role.label}</option>)}</select></Field><Field label="允许 AI 做到哪一步"><select name="ai-authority" value={selected.config.authority as string} onChange={(event) => patchSelected({}, { authority: event.target.value, ...(event.target.value === 'bounded_adjustment' ? { max_adjustment_bps: selected.config.max_adjustment_bps ?? 100 } : {}) })}>{allowedAuthority.map((item) => <option value={item} key={item}>{authorityLabels[item]}</option>)}</select></Field>{selected.config.authority === 'bounded_adjustment' ? <Field label="最大调整" hint="基点 · 100 = 1%"><input name="max-adjustment-bps" type="number" inputMode="numeric" min="1" max="2000" value={selected.config.max_adjustment_bps as number ?? 100} onChange={(event) => patchSelected({}, { max_adjustment_bps: Number(event.target.value) })} /></Field> : null}</section>
            <section><div className="qjs-inspector-title">给 AI 的指令</div><Field label="私密指令" hint="加密存储"><textarea name="private-instructions" autoComplete="off" value={selected.config.instructions as string ?? ''} onChange={(event) => patchSelected({}, { instructions: event.target.value })} /></Field><p className="guided-field-help">描述要考虑的信息和判断标准。接入模型后，AI 将按这些指令输出建议。</p><details className="guided-advanced"><summary>模型与异常处理</summary><Field label="Provider 引用" hint="不存密钥"><input name="provider-reference" autoComplete="off" spellCheck={false} value={selected.config.provider_ref as string} onChange={(event) => patchSelected({}, { provider_ref: event.target.value })} /></Field><Field label="超时" hint="ms"><input name="model-timeout" type="number" inputMode="numeric" min="100" max="60000" value={selected.config.timeout_ms as number} onChange={(event) => patchSelected({}, { timeout_ms: Number(event.target.value) })} /></Field><Field label="失败回退"><select name="on-model-error" value={selected.config.on_error as string} onChange={(event) => patchSelected({}, { on_error: event.target.value })}><option value="deny">拒绝交易（fail closed）</option><option value="use_baseline">使用基准策略输出</option><option value="skip">跳过本建议节点</option></select></Field></details></section></> : null}
          {selected.type === 'strategy' ? <section><div className="qjs-inspector-title">买入与卖出条件</div><p className="guided-field-help">通过指标和条件制定交易规则，不需要编写代码。规则编辑与回测在独立页面完成；当前画布只保存流程编排。</p>{onEditRules ? <button className="guided-primary" onClick={onEditRules}>打开交易规则</button> : null}<details className="guided-advanced"><summary>已有历史档案</summary><Field label="绑定策略包"><select value={workflow.package_id ?? ''} onChange={(event) => patchWorkflow({ package_id: event.target.value || null })}><option value="">尚未绑定</option>{packages.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></Field><button className="qjs-inspector-action" onClick={loadPackages}>读取历史档案</button></details></section> : null}
          {selected.type === 'market_data' ? <section><div className="qjs-inspector-title">行情口径</div><p className="guided-field-help">当前研究标的：{assetSymbol} · {interval}。标的与周期沿用行情工作区。</p><Field label="价格复权"><select value={selected.config.adjustment as string ?? 'auto'} onChange={(event) => patchSelected({}, { adjustment: event.target.value })}><option value="auto">自动处理</option><option value="none">不复权</option></select></Field></section> : null}
          {selected.type === 'feature_engine' ? <section><div className="qjs-inspector-title">避免未来数据</div><p className="guided-field-help">判断只能使用当时已经出现的数据。具体指标在交易规则中配置。</p></section> : null}
          {selected.type === 'position_sizer' ? <section><div className="qjs-inspector-title">资金分配</div><Field label="基础仓位方式"><select value={selected.config.method as string ?? 'volatility_target'} onChange={(event) => patchSelected({}, { method: event.target.value })}><option value="volatility_target">按波动率控制风险</option><option value="equal_weight">等权分配</option><option value="fixed">固定仓位</option></select></Field><p className="guided-field-help">此处配置流程意图；实际规则回测的目标仓位请在交易规则中设置。</p></section> : null}
          {selected.type === 'risk_gate' ? <section className="qjs-risk-fields"><div className="qjs-inspector-title">交易必须遵守的限额</div>{[
            ['max_gross_exposure', '总暴露'], ['max_single_position', '单标的仓位'], ['max_daily_loss', '日损失'], ['max_drawdown', '回撤停机'], ['max_participation_rate', '成交参与率'],
          ].map(([key, label]) => <Field label={label} hint="%" key={key}><input name={key} type="number" inputMode="decimal" min="0.01" max="100" step="1" value={Number(((selected.config[key] as number) * 100).toFixed(4))} onChange={(event) => patchSelected({}, { [key]: Number(event.target.value) / 100 })} /></Field>)}</section> : null}
          {selected.type === 'execution' ? <section><div className="qjs-inspector-title">计入真实交易成本</div><Field label="手续费率"><input name="execution-commission" type="number" inputMode="decimal" min="0" max="0.1" step="0.0001" value={selected.config.commission as number ?? 0} onChange={(event) => patchSelected({}, { commission: Number(event.target.value) })} /></Field><Field label="滑点率"><input name="execution-slippage" type="number" inputMode="decimal" min="0" max="0.1" step="0.0001" value={selected.config.slippage as number ?? 0} onChange={(event) => patchSelected({}, { slippage: Number(event.target.value) })} /></Field></section> : null}
          <div className="qjs-node-contract"><Check size={12} /><span><strong>配置会进行结构校验</strong><small>结构有效不代表策略盈利，也不代表 AI 已运行。</small></span></div>
        </> : null}
      </div>} /> : null}

    {tab === 'packages' ? <div className="qjs-packages">
      <header><div><strong>历史策略档案</strong><small>仅查看已有档案。新策略请使用策略画布与交易规则创建。</small></div><button disabled={loadingPackages} onClick={loadPackages}>{loadingPackages ? '读取中…' : '读取策略包'}</button></header>
      <div className="qjs-package-list">{packages.map((item) => <article key={item.id}><span><PackageCheck size={18} /></span><div><strong>{item.name} <em>v{item.version}</em></strong><small>{item.strategy_key} · {item.language} · {item.file_count} files</small></div><code>{item.content_hash.slice(0, 12)}…</code><b><LockKeyhole size={11} /> PRIVATE</b><time>{new Date(item.created_at).toLocaleString('zh-CN')}</time>{item.warnings.length ? <p>{item.warnings.join(' · ')}</p> : null}</article>)}{!packages.length ? <div className="qjs-empty"><FileArchive size={24} />选择 Agent 并输入凭证后读取已有档案。</div> : null}</div>
      <PrivateExecutionPanel key={`${agentId}:${token}`} agentId={agentId} token={token} packages={packages} datasetHash={zkDataset?.market_data_hash} onDataset={prepareDataset} preparing={proofBusy} />
    </div> : null}

    {tab === 'proof' ? <div className="qjs-proof">
      <header><div><strong>零知识证明发布流水线</strong><small>本地生成 witness 与 receipt；平台只验证公开 journal，不接收策略参数、salt、逐笔决策或完整净值。</small></div><span className={zkProfiles.some((item) => item.verifier_ready) ? 'is-ready' : 'is-blocked'}><ShieldCheck size={13} />{zkProfiles.some((item) => item.verifier_ready) ? '证明验证器就绪' : '验证器尚未构建'}</span></header>
      <label className="qjs-help">证明协议<select aria-label="证明协议" value={proofProfileId} disabled={proofBusy} onChange={(event) => { setProofProfileId(event.target.value); setZkProof(null); setPublishedProofReport(null) }}>{zkProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.id}</option>)}</select></label>
      <section className="qjs-proof-profile">
        {zkProfiles.map((profile) => <article key={profile.id}><div><Fingerprint size={20} /><span><em>REGISTERED IMAGE</em><strong>{profile.id}</strong><code>{profile.image_id}</code></span></div><dl><div><dt>证明系统</dt><dd>{profile.proof_system}</dd></div><div><dt>覆盖范围</dt><dd>{profile.scope}</dd></div><div><dt>Guest</dt><dd>v{profile.guest_version}</dd></div><div><dt>状态</dt><dd>{profile.status}</dd></div></dl><p><ShieldCheck size={12} />证明：{profile.privacy_scope.join('；')}</p><p className="is-warning"><CircleAlert size={12} />不证明：{profile.unsupported.join('、')}</p></article>)}
        {!zkProfiles.length ? <div className="qjs-empty"><CircleAlert size={20} />尚无已激活的 proof profile；运行 strategy/zkvm/scripts/build.sh 后才允许上传。</div> : null}
      </section>
      <ol className="qjs-proof-steps">
        <li className={zkDataset ? 'is-done' : ''}><span>01</span><div><strong>锁定可信市场数据</strong><small>{assetSymbol} · {interval} · 平台公开数据根</small>{zkDataset ? <code>{zkDataset.market_data_hash}</code> : null}</div><button disabled={proofBusy} onClick={prepareDataset}>{zkDataset ? '重新登记' : '生成数据集'}</button></li>
        <li><span>02</span><div><strong>在开发者设备创建私有 witness</strong><small>参数、salt 与 nullifier nonce 只保留在本地；inspect 输出的 strategy_commitment 用于创建 Agent</small></div><code>atlas-zkvm inspect --profile {proofProfileId} --witness witness.json</code></li>
        <li><span>03</span><div><strong>本地生成生产证明</strong><small>disable-dev-mode 已强制启用，禁止伪 receipt</small></div><code>strategy/zkvm/target/release/atlas-zkvm prove --profile {proofProfileId} --witness witness.json --receipt proof.r0</code></li>
        <li className={zkProof ? 'is-done' : ''}><span>04</span><div><strong>上传并独立验证 receipt</strong><small>固定 image ID · 45 秒 fail-closed · 最大 16 MB</small>{zkProof ? <code>{zkProof.proof_hash}</code> : null}</div><button disabled={proofBusy || !zkDataset} onClick={() => proofFileRef.current?.click()}>{proofBusy ? '处理中…' : '选择 proof.r0'}</button><input ref={proofFileRef} hidden type="file" accept=".r0,.bin" onChange={(event) => event.target.files?.[0] && uploadProof(event.target.files[0])} /></li>
        <li className={zkProof ? '' : 'is-locked'}><span>05</span><div><strong>发布 ZKP 跑分回执</strong><small>指标和抽样曲线直接来自已验证 journal；proof/nullifier 只能使用一次</small></div><button disabled={proofBusy || !zkProof} onClick={publishProof}>发布 QuantJudge</button></li>
        <li><span>06</span><div><strong>外部钱包锚定 Supervisor</strong><small>链上仅保存回执、证明、公开输入和 nullifier 的哈希；Supervisor 源码保持只读</small></div><code>ATLASZK2 · receipt · proof · public-input · nullifier</code></li>
      </ol>
      {publishedProofReport ? <div className="qjs-proof-published"><ShieldCheck size={15} /><span><strong>ZKP 报告已发布</strong><code>{publishedProofReport}</code></span></div> : null}
      <aside className="qjs-proof-boundary"><LockKeyhole size={16} /><div><strong>当前证明覆盖范围</strong><p>可编程 v2 在固定 zkVM 中执行私密整数指令、历史价格、均线和状态寄存器，并证明下一根开盘成交及成本后的收益。它不是任意 Python / AI 推理证明。SMA v1 保留历史验证；当前重建无法复现旧 image ID，生成新证明请选择 v2。</p>{zkDataset ? <small>{zkDataset.limitation}</small> : null}</div></aside>
    </div> : null}

    {tab === 'sdk' ? <div className="qjs-sdk">
      <header><div><strong>策略格式与开发契约</strong><small>规则可直接回测；Python 包可在已配置的独立 gVisor 中进行私密研究。任意依赖、远程 Runner 和机密 TEE 执行仍需独立接入。</small></div><code>.qstrategy / atlas.strategy/v1</code></header>
      <div className="qjs-format-grid">{spec?.languages.map((language) => <article key={language.id} className={language.production ? '' : 'is-import'}><span>{language.id === 'python' ? <Code2 size={19} /> : language.id === 'json_dsl' ? <Braces size={19} /> : language.id === 'remote_runner' ? <Cpu size={19} /> : <FileArchive size={19} />}</span><div><em>{language.id === 'json_dsl' ? '规则格式' : language.production ? '执行待接入' : '研究附件'}</em><strong>{language.label}</strong><small>{language.execution}</small></div></article>)}</div>
      <section className="qjs-contract"><div><strong>strategy.json</strong><small>版本、能力权限、参数 Schema、AI 插入点、研究门槛</small></div><i /><div><strong>BaseStrategy</strong><small>只读 StrategyContext → TargetPosition[]，网络与时钟由 Runner 注入</small></div><i /><div><strong>Workflow DAG</strong><small>AI 契约 → 硬风控 → 执行成本 → 审计承诺</small></div></section>
      <div className="qjs-code"><header><span>strategy.py</span><em>PYTHON SDK</em></header><pre>{`from atlas_strategy_sdk import BaseStrategy, StrategyContext, TargetPosition\n\nclass MyAlpha(BaseStrategy):\n    def generate_targets(self, ctx: StrategyContext):\n        bars = ctx.history("BTC-USD", 61)  # closed bars only\n        momentum = bars[-1].close / bars[0].close - 1\n        return [TargetPosition("BTC-USD", 0.2 if momentum > 0 else 0,\n                               0.8, "MOMENTUM_60")]`}</pre></div>
      <div className="qjs-sdk-note"><Sparkles size={15} /><span><strong>路径在仓库中已可用</strong><small>strategy/sdk/python · strategy/examples · docs/STRATEGY_DEVELOPMENT.md · strategy/tools/package_strategy.py</small></span></div>
    </div> : null}
  </section>
}
