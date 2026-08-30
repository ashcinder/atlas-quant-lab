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

export type StudioTab = 'workflow' | 'packages' | 'sdk'
interface Props {
  onError: (message: string) => void
  activeTab?: StudioTab
  embedded?: boolean
  onTabChange?: (tab: StudioTab) => void
  onWorkflowSaved?: (record: StudioWorkflowRecord) => void
  onPackageUploaded?: (record: StrategyPackageRecord) => void
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
  if (!validation) return <div className="qjs-validation is-pending"><Cpu size={15} /><span><strong>等待编译</strong><small>修改图后自动校验</small></span></div>
  return <div className={`qjs-validation ${validation.valid ? 'is-valid' : 'is-invalid'}`}>
    {validation.valid ? <ShieldCheck size={16} /> : <CircleAlert size={16} />}
    <span><strong>{validation.valid ? '可运行 · 风控路径完整' : `编译失败 · ${validation.errors.length} 项`}</strong><small>{validation.valid ? `${validation.summary.nodes} 节点 / ${validation.summary.ai_nodes} AI / ${validation.graph_hash.slice(0, 12)}…` : validation.errors[0]}</small></span>
  </div>
}

export function QuantStrategyStudio({ onError, activeTab, embedded = false, onTabChange, onWorkflowSaved, onPackageUploaded }: Props) {
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
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    Promise.all([api.getStudioSpec(), api.getStudioTemplates(), api.listQuantAgents()]).then(([nextSpec, nextTemplates, nextAgents]) => {
      setSpec(nextSpec); setTemplates(nextTemplates); setAgents(nextAgents.filter((agent) => !agent.is_demo))
      if (nextTemplates[0]) { const first = cloneWorkflow(nextTemplates[0].workflow); setWorkflow(first); setSelectedId(first.nodes[0]?.id ?? '') }
    }).catch((reason) => onError(reason instanceof Error ? reason.message : '策略工作室加载失败'))
  }, [onError])

  useEffect(() => {
    if (!workflow) return
    const timer = window.setTimeout(() => {
      api.validateStudioWorkflow(workflow).then(setValidation).catch((reason) => {
        setValidation(null); onError(reason instanceof Error ? reason.message : '工作流校验失败')
      })
    }, 280)
    return () => window.clearTimeout(timer)
  }, [onError, workflow])

  const selected = workflow?.nodes.find((node) => node.id === selectedId) ?? null
  const allowedAuthority = selected?.type === 'ai_guard'
    ? spec?.ai_roles.find((role) => role.id === selected.config.role)?.allowed_authority ?? [] : []

  const loadTemplate = (template: StudioTemplate) => {
    const next = cloneWorkflow(template.workflow)
    setWorkflow(next); setSelectedId(next.nodes[0]?.id ?? ''); setValidation(null)
  }

  const patchSelected = useCallback((patch: Partial<StudioWorkflowNode>, configPatch?: Record<string, unknown>) => {
    setWorkflow((current) => {
      if (!current) return current
      const nodes = current.nodes.map((node) => node.id === selectedId ? { ...node, ...patch, config: { ...node.config, ...configPatch } } : node)
      return linearize(current, nodes)
    })
  }, [selectedId])

  const addAI = (role: StudioAIRole) => {
    if (!workflow) return
    let sequence = workflow.nodes.filter((node) => node.id.startsWith(`ai_${role}_`)).length + 1
    while (workflow.nodes.some((node) => node.id === `ai_${role}_${sequence}`)) sequence += 1
    const authority = spec?.ai_roles.find((item) => item.id === role)?.allowed_authority[0] ?? 'advisory'
    const node: StudioWorkflowNode = {
      id: `ai_${role}_${sequence}`, type: 'ai_guard', label: roleLabels[role],
      config: { role, authority, provider_ref: 'server:primary-model', timeout_ms: 2500, on_error: role === 'risk_control' ? 'deny' : 'use_baseline', instructions: '仅根据输入证据返回结构化决策和 reason_codes。' },
    }
    setWorkflow(linearize(workflow, [...workflow.nodes, node])); setSelectedId(node.id)
  }

  const removeSelected = () => {
    if (!workflow || selected?.type !== 'ai_guard') return
    const remaining = workflow.nodes.filter((node) => node.id !== selectedId)
    const next = linearize(workflow, remaining)
    setWorkflow(next); setSelectedId(next.nodes[0]?.id ?? '')
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
    if (!workflow || !agentId || !token) { onError('保存需要自己的 Agent 与开发者凭证'); return }
    if (!validation?.valid) { onError('工作流尚未通过硬风控与 DAG 校验'); return }
    setSaving(true)
    try {
      const record = await api.saveStudioWorkflow(agentId, token, workflow, '工作室可视化修订')
      onWorkflowSaved?.(record)
    }
    catch (reason) { onError(reason instanceof Error ? reason.message : '工作流保存失败') }
    finally { setSaving(false) }
  }

  if (!workflow) return <div className="qjs-loading"><Cpu className="spin" size={22} />加载策略开发套件…</div>
  const ordered = orderNodes(workflow.nodes)

  return <section className={`qjs-shell ${embedded ? 'is-embedded' : ''}`}>
    <header className="qjs-toolbar">
      {embedded ? <div className="qjs-embedded-context"><Fingerprint size={14} /><span><strong>私密开发上下文</strong><small>选择 Agent 后，工作流与策略包将绑定到同一版本链</small></span></div> : <><div className="qjs-studio-title"><Workflow size={16} /><span><strong>STRATEGY STUDIO</strong><small>.qstrategy 私密策略与 AI 工作流</small></span></div><nav><button className={tab === 'workflow' ? 'is-active' : ''} onClick={() => goTab('workflow')}><GitBranch size={13} />工作流</button><button className={tab === 'packages' ? 'is-active' : ''} onClick={loadPackages}><FileArchive size={13} />策略包</button><button className={tab === 'sdk' ? 'is-active' : ''} onClick={() => goTab('sdk')}><Code2 size={13} />SDK 与格式</button></nav></>}
      <form className="qjs-auth" onSubmit={(event) => { event.preventDefault(); void save() }}>
        <input className="qjs-hidden-username" name="username" autoComplete="username" value={agentId} readOnly tabIndex={-1} aria-hidden="true" />
        <label className="qjs-agent-select"><span>AGENT</span><select value={agentId} onChange={(event) => setAgentId(event.target.value)}><option value="">选择我的 Agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown size={12} /></label>
        <label className="qjs-token"><KeyRound size={12} /><input name="developer-token" type="password" autoComplete="current-password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="开发者凭证（不持久化）" /></label>
        <button className="qjs-save" type="submit" disabled={saving || !validation?.valid}><Save size={13} />{saving ? '保存中' : '保存版本'}</button>
      </form>
    </header>

    {tab === 'workflow' ? <div className="qjs-workflow-layout">
      <aside className="qjs-library">
        <section><div className="qjs-side-title"><span>TEMPLATES</span><small>工业级树干</small></div>{templates.map((template) => <button className="qjs-template" key={template.id} onClick={() => loadTemplate(template)}><span><strong>{template.name}</strong><small>{template.description}</small></span><Play size={11} /></button>)}</section>
        <section><div className="qjs-side-title"><span>AI ROLES</span><small>插入流程</small></div>{spec?.ai_roles.map((role) => <button className="qjs-role" key={role.id} onClick={() => addAI(role.id)}><Bot size={13} /><span><strong>{role.label}</strong><small>{role.allowed_authority.map((item) => authorityLabels[item]).join(' / ')}</small></span><Plus size={11} /></button>)}</section>
        <div className="qjs-safety-note"><LockKeyhole size={14} /><span><strong>硬风控不可被 AI 绕过</strong><small>无论模型权限多高，订单都必须经过确定性限额。</small></span></div>
      </aside>

      <main className="qjs-canvas">
        <header><div><Field label="WORKFLOW ID"><input value={workflow.id} onChange={(event) => setWorkflow({ ...workflow, id: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })} /></Field><Field label="NAME"><input value={workflow.name} onChange={(event) => setWorkflow({ ...workflow, name: event.target.value })} /></Field></div><ValidationPanel validation={validation} /></header>
        <div className="qjs-flow">
          <div className="qjs-flow-ruler"><span>INGEST</span><span>ALPHA</span><span>CONTROL</span><span>EXECUTE</span><span>PROVE</span></div>
          {ordered.map((node, index) => <div className="qjs-flow-row" key={node.id}>
            <button className={`qjs-node type-${node.type} ${selectedId === node.id ? 'is-selected' : ''}`} onClick={() => setSelectedId(node.id)}>
              <i>{node.type === 'ai_guard' ? <Bot size={15} /> : node.type === 'risk_gate' ? <ShieldCheck size={15} /> : node.type === 'strategy' ? <Braces size={15} /> : node.type === 'audit' ? <Fingerprint size={15} /> : <Box size={14} />}</i>
              <span><em>{typeMeta[node.type]?.tag}</em><strong>{node.label}</strong><small>{typeMeta[node.type]?.hint}</small></span>
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
        {selected ? <><header><div><small>{typeMeta[selected.type]?.tag}</small><strong>{selected.label}</strong></div>{selected.type === 'ai_guard' ? <button onClick={removeSelected} title="删除 AI 节点"><Trash2 size={14} /></button> : <ShieldCheck size={16} />}</header>
          <section><div className="qjs-inspector-title">BASIC</div><Field label="节点名称"><input value={selected.label} onChange={(event) => patchSelected({ label: event.target.value })} /></Field><Field label="节点 ID" hint="版本内稳定"><input value={selected.id} disabled /></Field></section>
          {selected.type === 'ai_guard' ? <><section><div className="qjs-inspector-title">AI RESPONSIBILITY</div><Field label="责任"><select value={selected.config.role as string} onChange={(event) => { const role = event.target.value as StudioAIRole; const allowed = spec?.ai_roles.find((item) => item.id === role)?.allowed_authority ?? ['advisory']; patchSelected({}, { role, authority: allowed[0] }) }}>{spec?.ai_roles.map((role) => <option value={role.id} key={role.id}>{role.label}</option>)}</select></Field><Field label="权限边界"><select value={selected.config.authority as string} onChange={(event) => patchSelected({}, { authority: event.target.value })}>{allowedAuthority.map((item) => <option value={item} key={item}>{authorityLabels[item]}</option>)}</select></Field>{selected.config.authority === 'bounded_adjustment' ? <Field label="最大调整" hint="BPS"><input type="number" min="1" max="2000" value={selected.config.max_adjustment_bps as number ?? 100} onChange={(event) => patchSelected({}, { max_adjustment_bps: Number(event.target.value) })} /></Field> : null}</section>
            <section><div className="qjs-inspector-title">MODEL CONTRACT</div><Field label="Provider 引用" hint="不存密钥"><input value={selected.config.provider_ref as string} onChange={(event) => patchSelected({}, { provider_ref: event.target.value })} /></Field><Field label="超时" hint="ms"><input type="number" min="100" max="60000" value={selected.config.timeout_ms as number} onChange={(event) => patchSelected({}, { timeout_ms: Number(event.target.value) })} /></Field><Field label="失败回退"><select value={selected.config.on_error as string} onChange={(event) => patchSelected({}, { on_error: event.target.value })}><option value="deny">拒绝交易（fail closed）</option><option value="use_baseline">使用基准策略输出</option><option value="skip">跳过本建议节点</option></select></Field><Field label="私密指令" hint="加密存储"><textarea value={selected.config.instructions as string ?? ''} onChange={(event) => patchSelected({}, { instructions: event.target.value })} /></Field></section></> : null}
          {selected.type === 'strategy' ? <section><div className="qjs-inspector-title">PRIVATE ARTIFACT</div><Field label="绑定策略包" hint="按 content hash 锁定"><select value={workflow.package_id ?? ''} onChange={(event) => setWorkflow({ ...workflow, package_id: event.target.value || null })}><option value="">尚未绑定</option>{packages.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></Field><button className="qjs-inspector-action" onClick={loadPackages}><FileArchive size={12} />验证凭证并读取策略包</button><small className="qjs-help">运行与审计回执将同时锁定 package content hash 和 workflow graph hash。</small></section> : null}
          {selected.type === 'risk_gate' ? <section className="qjs-risk-fields"><div className="qjs-inspector-title">DETERMINISTIC LIMITS</div>{[
            ['max_gross_exposure', '总暴露'], ['max_single_position', '单标的仓位'], ['max_daily_loss', '日损失'], ['max_drawdown', '回撤停机'], ['max_participation_rate', '成交参与率'],
          ].map(([key, label]) => <Field label={label} hint="0–1" key={key}><input type="number" min="0.0001" max="1" step="0.01" value={selected.config[key] as number} onChange={(event) => patchSelected({}, { [key]: Number(event.target.value) })} /></Field>)}</section> : null}
          {selected.type === 'execution' ? <section><div className="qjs-inspector-title">EXECUTION MODEL</div><Field label="手续费率"><input type="number" step="0.0001" value={selected.config.commission as number ?? 0} onChange={(event) => patchSelected({}, { commission: Number(event.target.value) })} /></Field><Field label="滑点率"><input type="number" step="0.0001" value={selected.config.slippage as number ?? 0} onChange={(event) => patchSelected({}, { slippage: Number(event.target.value) })} /></Field></section> : null}
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

    {tab === 'sdk' ? <div className="qjs-sdk">
      <header><div><strong>一种原生包，三条生产路径</strong><small>研究附件与实盘可执行物分离，不把 Notebook 假装成生产策略。</small></div><code>.qstrategy / atlas.strategy/v1</code></header>
      <div className="qjs-format-grid">{spec?.languages.map((language) => <article key={language.id} className={language.production ? '' : 'is-import'}><span>{language.id === 'python' ? <Code2 size={19} /> : language.id === 'json_dsl' ? <Braces size={19} /> : language.id === 'remote_runner' ? <Cpu size={19} /> : <FileArchive size={19} />}</span><div><em>{language.production ? 'PRODUCTION' : 'IMPORT / RESEARCH'}</em><strong>{language.label}</strong><small>{language.execution}</small></div></article>)}</div>
      <section className="qjs-contract"><div><strong>strategy.json</strong><small>版本、能力权限、参数 Schema、AI 插入点、研究门槛</small></div><i /><div><strong>BaseStrategy</strong><small>只读 StrategyContext → TargetPosition[]，网络与时钟由 Runner 注入</small></div><i /><div><strong>Workflow DAG</strong><small>AI 契约 → 硬风控 → 执行成本 → 审计承诺</small></div></section>
      <div className="qjs-code"><header><span>strategy.py</span><em>PYTHON SDK</em></header><pre>{`from atlas_strategy_sdk import BaseStrategy, StrategyContext, TargetPosition\n\nclass MyAlpha(BaseStrategy):\n    def generate_targets(self, ctx: StrategyContext):\n        bars = ctx.history("BTC-USD", 61)  # closed bars only\n        momentum = bars[-1].close / bars[0].close - 1\n        return [TargetPosition("BTC-USD", 0.2 if momentum > 0 else 0,\n                               0.8, "MOMENTUM_60")]`}</pre></div>
      <div className="qjs-sdk-note"><Sparkles size={15} /><span><strong>路径在仓库中已可用</strong><small>sdk/python · examples/strategies · docs/STRATEGY_DEVELOPMENT.md · tools/package_strategy.py</small></span></div>
    </div> : null}
  </section>
}
