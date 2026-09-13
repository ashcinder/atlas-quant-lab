import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type {
  CustomStrategyRecord, QuantAgent, StrategyPackageRecord, StudioTemplate,
  StudioValidation, StudioWorkflowRecord, ZkMarketDataset, ZkProofRecord,
} from '../types'
import { QuantStrategyStudio } from './QuantStrategyStudio'
import { ResearchWorkspace, type ResearchWorkspaceProps } from './ResearchWorkspace'

vi.mock('../api', () => ({ api: {
  listCustomStrategies: vi.fn(), saveCustomStrategy: vi.fn(), deleteCustomStrategy: vi.fn(),
  getStudioSpec: vi.fn(), getStudioTemplates: vi.fn(), listQuantAgents: vi.fn(), listZkProfiles: vi.fn(),
  validateStudioWorkflow: vi.fn(), saveStudioWorkflow: vi.fn(), listStrategyPackages: vi.fn(),
  createZkMarketDataset: vi.fn(), uploadZkProof: vi.fn(), publishZkReport: vi.fn(),
} }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const rule: CustomStrategyRecord = {
  id: 'saved-rule', created_at: '2026-01-01', updated_at: '2026-01-01',
  spec: { id: 'saved-rule', name: '已保存的趋势规则', description: '', target_position: 0.5,
    entry: { kind: 'condition', left: { field: 'close' }, operator: 'gt', right_value: 100 },
    exit: { kind: 'condition', left: { field: 'close' }, operator: 'lt', right_value: 90 } },
}
const researchProps: ResearchWorkspaceProps = {
  asset: null, strategies: [], interval: '1d', source: 'auto', initialCapital: 10000,
  commission: 0.001, slippage: 0, spread: 0, maxPosition: 1, maxParticipation: 0.1,
  onLoading: vi.fn(), onError: vi.fn(), onCustomResult: vi.fn(), view: 'builder', showHeader: false,
}
const template: StudioTemplate = {
  id: 'first', name: '趋势工作流', description: '基础模板', workflow: {
    schema_version: '1.0', id: 'workflow-first', name: '趋势草稿', nodes: [
      { id: 'strategy', type: 'strategy', label: '策略节点', config: {} },
      { id: 'review', type: 'ai_guard', label: '信号复核', config: {
        role: 'signal_review', authority: 'advisory', provider_ref: 'server:model',
        timeout_ms: 1000, on_error: 'deny', instructions: '原始私密指令',
      } },
    ], edges: [{ source: 'strategy', target: 'review' }],
  },
}
const secondTemplate: StudioTemplate = { ...template, id: 'second', name: '备选工作流',
  workflow: { ...template.workflow, id: 'workflow-second', name: '备选草稿' } }
const validation: StudioValidation = { valid: true, errors: [], warnings: [], graph_hash: 'graph-hash',
  topological_order: ['strategy', 'review'], summary: { nodes: 2, edges: 1, ai_nodes: 1, hard_risk_gates: 1 } }
const savedWorkflow: StudioWorkflowRecord = { id: 'revision-a', agent_id: 'agent-a', name: '趋势草稿',
  revision: 2, graph_hash: 'graph-hash-long', validation, status: 'saved', created_at: '', updated_at: '' }
const privatePackage: StrategyPackageRecord = {
  id: 'package-a', agent_id: 'agent-a', strategy_key: 'alpha', name: 'A 私密策略包', version: '1.0.0',
  language: 'python', manifest_hash: 'manifest', content_hash: 'private-hash', file_count: 2,
  expanded_bytes: 1024, warnings: [], status: 'ready', created_at: '2026-01-01',
  source_private: true, encrypted_at_rest: true,
}
const proof: ZkProofRecord = {
  id: 'proof-a', agent_id: 'agent-a', proof_profile: 'sma', image_id: 'image', public_statement: {},
  public_inputs_hash: 'inputs', proof_hash: 'A-private-proof-hash', receipt_size: 100, receipt_kind: 'groth16',
  verifier_version: '1', nullifier: 'nonce', status: 'verified', verified_at: '', private_witness_stored: false,
}
const dataset: ZkMarketDataset = {
  market_data_hash: 'dataset-a', source: 'trusted', symbol: 'BTC-USD', interval: '1d', adjustment: 'none',
  period_start: 1, period_end: 2, bar_count: 2, trust_model: 'trusted', fetched_at: '', dataset: {}, download_url: '', limitation: '',
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.listCustomStrategies).mockResolvedValue([rule])
  vi.mocked(api.getStudioSpec).mockResolvedValue({ native_format: '', archive: '', required_files: [],
    languages: [], limits: { archive_bytes: 100, expanded_bytes: 200, files: 2 }, security: {},
    ai_roles: [{ id: 'signal_review', label: '信号复核', allowed_authority: ['advisory'] }] })
  vi.mocked(api.getStudioTemplates).mockResolvedValue([template, secondTemplate])
  vi.mocked(api.listQuantAgents).mockResolvedValue([
    { id: 'agent-a', name: 'Agent A', is_demo: false }, { id: 'agent-b', name: 'Agent B', is_demo: false },
  ] as QuantAgent[])
  vi.mocked(api.listZkProfiles).mockResolvedValue([{ id: 'sma', status: 'active', verifier_ready: true,
    image_id: 'image', proof_system: 'risc0', guest_version: '1', scope: 'sma', privacy_scope: [], unsupported: [] }])
  vi.mocked(api.validateStudioWorkflow).mockResolvedValue(validation)
  vi.mocked(api.listStrategyPackages).mockResolvedValue([privatePackage])
  vi.mocked(api.createZkMarketDataset).mockResolvedValue(dataset)
})
afterEach(cleanup)

async function openStudio(activeTab: 'workflow' | 'packages' | 'proof' = 'workflow', onWorkflowSaved = vi.fn()) {
  const onError = vi.fn()
  const result = render(<QuantStrategyStudio embedded activeTab={activeTab} onError={onError} onWorkflowSaved={onWorkflowSaved} />)
  await screen.findByRole('combobox', { name: '选择用于归属工作流的策略身份' })
  fireEvent.change(screen.getByRole('combobox', { name: '选择用于归属工作流的策略身份' }), { target: { value: 'agent-a' } })
  fireEvent.change(screen.getByLabelText('开发者凭证'), { target: { value: 'private-token-a' } })
  return { ...result, onError }
}

describe('rule drafts', () => {
  it('keeps an edited rule on cancel and replaces it only after confirmation', async () => {
    render(<ResearchWorkspace {...researchProps} />)
    const load = await screen.findByRole('button', { name: '载入模板 已保存的趋势规则' })
    fireEvent.change(screen.getByRole('textbox', { name: '策略名称' }), { target: { value: '尚未保存的规则' } })
    load.focus()
    fireEvent.click(load)
    expect(screen.getByRole('alertdialog')).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '取消，保留当前内容' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByDisplayValue('尚未保存的规则')).toBeTruthy()
    expect(document.activeElement).toBe(load)
    fireEvent.click(load)
    fireEvent.click(screen.getByRole('button', { name: '放弃草稿并载入' }))
    expect(screen.getByDisplayValue('已保存的趋势规则')).toBeTruthy()
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('does not mark edits made during a rule save as saved', async () => {
    const save = deferred<CustomStrategyRecord>()
    vi.mocked(api.saveCustomStrategy).mockReturnValue(save.promise)
    const onDraftChange = vi.fn()
    render(<ResearchWorkspace {...researchProps} onDraftChange={onDraftChange} />)
    await screen.findByRole('button', { name: '载入模板 已保存的趋势规则' })
    fireEvent.change(screen.getByRole('textbox', { name: '策略名称' }), { target: { value: '提交时的规则' } })
    fireEvent.click(screen.getByRole('button', { name: '保存模板' }))
    fireEvent.change(screen.getByRole('textbox', { name: '策略名称' }), { target: { value: '保存期间的新规则' } })
    await act(async () => save.resolve(rule))
    expect(screen.getByDisplayValue('保存期间的新规则')).toBeTruthy()
    expect(screen.getByText('规则草稿 · 未保存')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('新修改仍未保存')
    expect(onDraftChange).toHaveBeenLastCalledWith(true)
  })
})

describe('workflow drafts and private sessions', () => {
  it('adds contextual AI blocks and preserves the graph when removing them', async () => {
    await openStudio()
    fireEvent.click(screen.getByRole('button', { name: '让 AI 复核交易信号' }))
    expect(screen.getByRole('button', { name: /配置 信号复核 #ai_signal_review_1/ })).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/私密指令/), { target: { value: '仅在交易量支持趋势时建议买入' } })
    await waitFor(() => expect(api.validateStudioWorkflow).toHaveBeenLastCalledWith(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: 'ai_signal_review_1', config: expect.objectContaining({ instructions: '仅在交易量支持趋势时建议买入' }) })]),
      edges: [{ source: 'strategy', target: 'review' }, { source: 'review', target: 'ai_signal_review_1' }],
    })))
    fireEvent.click(screen.getByRole('button', { name: '删除 AI 节点' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(screen.queryByRole('button', { name: /#ai_signal_review_1/ })).toBeNull()
    await waitFor(() => expect(api.validateStudioWorkflow).toHaveBeenLastCalledWith(expect.objectContaining({ edges: template.workflow.edges })))
  })

  it('persists the default limit when enabling bounded AI adjustment', async () => {
    const studioSpec = await api.getStudioSpec()
    vi.mocked(api.getStudioSpec).mockResolvedValue({ ...studioSpec, ai_roles: [{ id: 'signal_review', label: '信号复核', allowed_authority: ['advisory', 'bounded_adjustment'] }] })
    await openStudio()
    fireEvent.click(screen.getByRole('button', { name: /配置 信号复核 #review/ }))
    fireEvent.change(screen.getByLabelText('允许 AI 做到哪一步'), { target: { value: 'bounded_adjustment' } })
    await waitFor(() => expect(api.validateStudioWorkflow).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ id: 'review', config: expect.objectContaining({ authority: 'bounded_adjustment', max_adjustment_bps: 100 }) })]) })))
  })

  it('shows validation request errors and retries after editing', async () => {
    vi.mocked(api.validateStudioWorkflow).mockRejectedValueOnce(new Error('配置校验失败'))
    await openStudio()
    await screen.findByText('流程检查失败')
    expect(screen.queryByText('正在检查流程…')).toBeNull()
    fireEvent.change(screen.getByRole('textbox', { name: '工作流名称' }), { target: { value: '重试检查' } })
    await screen.findByText('结构校验通过')
    expect(screen.queryByText('流程检查失败')).toBeNull()
  })

  it('renders AI risk review before the hard risk gate in saved flow order', async () => {
    vi.mocked(api.getStudioTemplates).mockResolvedValue([{ ...template, workflow: { ...template.workflow, nodes: [
      { id: 'ai-risk', type: 'ai_guard', label: 'AI 风险检查', config: { role: 'risk_control', authority: 'advisory', provider_ref: 'server:model', timeout_ms: 1000, on_error: 'deny' } },
      { id: 'risk', type: 'risk_gate', label: '不可绕过的风控', config: {} },
    ], edges: [{ source: 'ai-risk', target: 'risk' }] } }])
    await openStudio()
    const ai = screen.getByRole('button', { name: '配置 AI 风险检查 #ai-risk' })
    const gate = screen.getByRole('button', { name: '配置 不可绕过的风控 #risk' })
    expect(ai.compareDocumentPosition(gate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('stores displayed risk percentages as fractions', async () => {
    vi.mocked(api.getStudioTemplates).mockResolvedValue([{ ...template, workflow: { ...template.workflow, nodes: [
      { id: 'risk', type: 'risk_gate', label: '风险限额', config: { max_gross_exposure: 0.95, max_single_position: 0.2, max_daily_loss: 0.03, max_drawdown: 0.15, max_participation_rate: 0.1 } },
    ], edges: [] } }])
    await openStudio()
    const exposure = screen.getByRole('spinbutton', { name: /总暴露/ })
    expect((exposure as HTMLInputElement).value).toBe('95')
    fireEvent.change(exposure, { target: { value: '80' } })
    await waitFor(() => expect(api.validateStudioWorkflow).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: [expect.objectContaining({ config: expect.objectContaining({ max_gross_exposure: 0.8 }) })] })))
  })

  it('offers historical archives without a source upload input', async () => {
    const { container } = await openStudio('packages')
    expect(container.querySelector('input[type="file"]')).toBeNull()
    expect(screen.queryByText('选择 .qstrategy')).toBeNull()
    expect(screen.getByText('历史策略档案')).toBeTruthy()
  })

  it('protects private instructions from an unconfirmed template replacement', async () => {
    await openStudio()
    fireEvent.click(screen.getByRole('button', { name: /信号复核.*#review/ }))
    fireEvent.change(screen.getByLabelText(/私密指令/), { target: { value: '不能丢失的私密草稿' } })
    fireEvent.click(screen.getByRole('button', { name: '载入工作流模板 备选工作流' }))
    fireEvent.click(screen.getByRole('button', { name: '取消，保留当前内容' }))
    expect(screen.getByDisplayValue('不能丢失的私密草稿')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '载入工作流模板 备选工作流' }))
    fireEvent.click(screen.getByRole('button', { name: '放弃草稿并载入' }))
    expect(screen.getByDisplayValue('备选草稿')).toBeTruthy()
  })

  it('retains newer workflow edits when an earlier save completes', async () => {
    const save = deferred<StudioWorkflowRecord>()
    vi.mocked(api.saveStudioWorkflow).mockReturnValue(save.promise)
    await openStudio()
    fireEvent.change(screen.getByRole('textbox', { name: '工作流名称' }), { target: { value: '提交版本' } })
    await screen.findByText('结构校验通过')
    fireEvent.click(screen.getByRole('button', { name: '保存修订' }))
    fireEvent.change(screen.getByRole('textbox', { name: '工作流名称' }), { target: { value: '新编辑版本' } })
    await act(async () => save.resolve(savedWorkflow))
    expect(screen.getByDisplayValue('新编辑版本')).toBeTruthy()
    expect(screen.getByText(/新修改仍未保存/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '保存修订' })).toBeTruthy()
  })

  it('clears credentials, loaded packages, and package bindings when changing Agent', async () => {
    const { rerender, onError } = await openStudio('packages')
    fireEvent.click(screen.getByRole('button', { name: '读取策略包' }))
    await screen.findByText('A 私密策略包')
    rerender(<QuantStrategyStudio embedded activeTab="workflow" onError={onError} />)
    fireEvent.change(screen.getByRole('combobox', { name: /绑定策略包/ }), { target: { value: privatePackage.id } })
    fireEvent.change(screen.getByRole('combobox', { name: '选择用于归属工作流的策略身份' }), { target: { value: 'agent-b' } })
    expect((screen.getByLabelText('开发者凭证') as HTMLInputElement).value).toBe('')
    expect((screen.getByRole('combobox', { name: /绑定策略包/ }) as HTMLSelectElement).value).toBe('')
    expect(screen.queryByRole('option', { name: /A 私密策略包/ })).toBeNull()
  })

  it('ignores a late package response after switching away and back to the same Agent', async () => {
    const request = deferred<StrategyPackageRecord[]>()
    vi.mocked(api.listStrategyPackages).mockReturnValue(request.promise)
    await openStudio('packages')
    fireEvent.click(screen.getByRole('button', { name: '读取策略包' }))
    const agentSelect = screen.getByRole('combobox', { name: '选择用于归属工作流的策略身份' })
    fireEvent.change(agentSelect, { target: { value: 'agent-b' } })
    fireEvent.change(agentSelect, { target: { value: 'agent-a' } })
    await act(async () => request.resolve([privatePackage]))
    expect(screen.queryByText('A 私密策略包')).toBeNull()
    expect((screen.getByRole('button', { name: '读取策略包' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('ignores a late workflow save from the previous Agent', async () => {
    const save = deferred<StudioWorkflowRecord>()
    vi.mocked(api.saveStudioWorkflow).mockReturnValue(save.promise)
    const onSaved = vi.fn()
    await openStudio('workflow', onSaved)
    fireEvent.change(screen.getByRole('textbox', { name: '工作流名称' }), { target: { value: '私密草稿' } })
    await screen.findByText('结构校验通过')
    fireEvent.click(screen.getByRole('button', { name: '保存修订' }))
    fireEvent.change(screen.getByRole('combobox', { name: '选择用于归属工作流的策略身份' }), { target: { value: 'agent-b' } })
    await act(async () => save.resolve(savedWorkflow))
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByDisplayValue('私密草稿')).toBeTruthy()
    expect(screen.getByRole('button', { name: '保存修订' })).toBeTruthy()
    expect(screen.queryByText(/已保存 r2/)).toBeNull()
  })

  it('does not restore an old proof or enable publishing after an Agent switch', async () => {
    const request = deferred<ZkProofRecord>()
    vi.mocked(api.uploadZkProof).mockReturnValue(request.promise)
    const { container } = await openStudio('proof')
    fireEvent.click(screen.getByRole('button', { name: '生成数据集' }))
    await screen.findByText('dataset-a')
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['proof'], 'proof.r0')] },
    })
    await waitFor(() => expect(api.uploadZkProof).toHaveBeenCalled())
    fireEvent.change(screen.getByRole('combobox', { name: '选择用于归属工作流的策略身份' }), { target: { value: 'agent-b' } })
    await act(async () => request.resolve(proof))
    expect(screen.queryByText(proof.proof_hash)).toBeNull()
    expect(screen.queryByText('dataset-a')).toBeNull()
    expect((screen.getByRole('button', { name: '发布 QuantJudge' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
