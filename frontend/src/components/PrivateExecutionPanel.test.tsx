import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { StrategyPackageRecord } from '../types'
import { PrivateExecutionPanel } from './PrivateExecutionPanel'

vi.mock('../api', () => ({ api: { executionCapabilities: vi.fn(), executePrivatePackage: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const packages: StrategyPackageRecord[] = [{ id: 'p1', agent_id: 'a1', name: 'Private strategy', version: '1.0', language: 'python', strategy_key: 'demo', manifest_hash: '', content_hash: '', file_count: 2, expanded_bytes: 100, warnings: [], status: 'inspected', created_at: '', source_private: true, encrypted_at_rest: true }]
const props = { agentId: 'a1', token: 'private-credential', packages, datasetHash: 'ab'.repeat(32), onDataset: vi.fn(), preparing: false }
const runButton = () => screen.getByRole('button', { name: '隔离运行策略' }) as HTMLButtonElement

describe('private execution boundaries', () => {
  it('requires capability, package and explicit operator-visibility consent, and never calls AI implicitly', async () => {
    vi.mocked(api.executionCapabilities).mockResolvedValue({ python: { configured: true }, ai: { configured: false }, tee: { execution_available: false } })
    vi.mocked(api.executePrivatePackage).mockResolvedValue({ id: 'r1', metrics: { total_return: .1, max_drawdown: -.02, sharpe: 1 }, final_equity: 110000, ai_calls: 0, ai_failed_closed: 0, warnings: [] })
    render(<PrivateExecutionPanel {...props} />)
    expect(api.executionCapabilities).not.toHaveBeenCalled()
    expect(runButton().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('执行策略包'), { target: { value: 'p1' } })
    fireEvent.click(screen.getByRole('button', { name: '检查执行环境' }))
    await screen.findByText(/已配置。实际运行/)
    expect(runButton().disabled).toBe(true)
    expect((screen.getByLabelText(/启用本地 AI/) as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText(/我理解/))
    fireEvent.click(runButton())
    await screen.findByText('研究结果 · 非证明')
    expect(api.executePrivatePackage).toHaveBeenCalledWith('a1', 'p1', 'private-credential', expect.objectContaining({ acknowledge_host_visibility: true, ai_provider: null, parameters: {} }))
    expect(document.body.textContent).not.toContain('private-credential')
  })

  it('rejects malformed parameters before sending them and blocks unavailable environments', async () => {
    vi.mocked(api.executionCapabilities).mockResolvedValue({ python: { configured: true }, ai: { configured: false }, tee: { execution_available: false } })
    render(<PrivateExecutionPanel {...props} />)
    fireEvent.change(screen.getByLabelText('执行策略包'), { target: { value: 'p1' } })
    fireEvent.click(screen.getByLabelText(/我理解/))
    fireEvent.click(screen.getByRole('button', { name: '检查执行环境' }))
    await screen.findByText(/已配置。实际运行/)
    fireEvent.change(screen.getByLabelText('执行参数覆盖'), { target: { value: '[]' } })
    fireEvent.click(runButton())
    await screen.findByText('参数必须是 JSON 对象')
    expect(api.executePrivatePackage).not.toHaveBeenCalled()
    vi.mocked(api.executionCapabilities).mockResolvedValue({ python: { configured: false }, ai: { configured: false }, tee: { execution_available: false } })
    fireEvent.click(screen.getByRole('button', { name: '检查执行环境' }))
    await waitFor(() => expect(runButton().disabled).toBe(true))
    await screen.findByText(/尚未配置独立 gVisor/)
  })
})
