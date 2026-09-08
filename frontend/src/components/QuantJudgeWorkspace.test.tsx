import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { QuantAgent, QuantReport, QuantVerification } from '../types'
import { QuantJudgeWorkspace } from './QuantJudgeWorkspace'

vi.mock('../api', () => ({ api: {
  getQuantJudgeOverview: vi.fn(), listQuantAgents: vi.fn(), getQuantChainStatus: vi.fn(),
  getQuantAgent: vi.fn(), verifyQuantReport: vi.fn(),
} }))

const report: QuantReport = {
  id: 'report-a', report_type: 'backtest', period_start: '2025-01-01', period_end: '2026-01-01',
  metrics: { total_return: 0.15, annualized_return: 0.15, max_drawdown: -0.1, sharpe: 1.2 },
  public_curve: [], decision_count: 10, decision_merkle_root: 'root', market_data_hash: 'market',
  previous_receipt_hash: null, receipt_hash: 'receipt', attestation_key_id: 'key',
  attestation_signature: 'signature', external_proof: null, evidence_level: 'platform_attested',
  chain_tx_hash: 'tx', chain_status: 'confirmed', chain_block_number: 42, score: 71,
  created_at: '2026-01-01', receipt_integrity_valid: true, public_curve_integrity_valid: true,
  privacy: { source_hidden: true, decisions_hidden: true, raw_equity_discarded: true },
}
const agent: QuantAgent = {
  id: 'alpha', rank: 1, name: 'Alpha Strategy', developer_alias: 'Developer',
  agent_type: 'traditional', category: 'timing', asset_classes: ['crypto'], description: 'Test strategy',
  risk_level: 'medium', monthly_price: 100, price_currency: 'CNY', strategy_commitment: 'commitment',
  status: 'active', is_demo: true, subscriber_count: 0, latest_report: report,
  created_at: '2026-01-01', updated_at: '2026-01-01',
}
const secondAgent: QuantAgent = { ...agent, id: 'beta', rank: 2, name: 'Beta Strategy', latest_report: { ...report, id: 'report-b' } }
const verified: QuantVerification = {
  report_id: report.id, receipt_hash: 'receipt', receipt_hash_valid: true,
  attestation_signature_valid: true, record_integrity_valid: true, public_curve_integrity_valid: true,
  calculation_verified: true, decision_merkle_root: 'root', strategy_commitment: 'commitment',
  external_proof_verified: false, chain: { status: 'failed', transaction_hash: 'tx', block_number: null },
  proof_scope: [], limitations: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: vi.fn() })
  vi.mocked(api.getQuantJudgeOverview).mockResolvedValue({ agents: 2, reports: 2, live_reports: 0,
    chain_confirmed_reports: 0, active_subscriptions: 0, median_score: 71,
    attestation: { algorithm: 'Ed25519', key_id: 'key', public_key: 'public' }, privacy_model: 'private' })
  vi.mocked(api.listQuantAgents).mockResolvedValue([agent, secondAgent])
  vi.mocked(api.getQuantChainStatus).mockResolvedValue({ connected: false, compatible: false,
    rpc_url: '', chain_id: null, block_number: null, error: null, expected_chain_id: 1,
    read_only_source_policy: true, submission_policy: 'external' })
  vi.mocked(api.getQuantAgent).mockImplementation(async (id) => id === agent.id ? agent : secondAgent)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

async function openMarket() {
  render(<QuantJudgeWorkspace onError={vi.fn()} onOpenLab={vi.fn()} />)
  await screen.findByRole('button', { name: /Alpha Strategy/ })
}

describe('QuantJudge evidence and navigation', () => {
  it('keeps keyboard focus in the publish dialog and restores it on Escape', async () => {
    await openMarket()
    const trigger = screen.getByRole('button', { name: '发布 Agent' })
    trigger.focus()
    fireEvent.click(trigger)
    expect(document.activeElement).toBe(screen.getByLabelText('Agent 名称'))
    const close = screen.getByRole('button', { name: '关闭发布窗口' })
    close.focus()
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
    expect(document.activeElement?.textContent).toBe('取消')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('never treats the presence of a signature as a completed verification', async () => {
    await openMarket()
    expect(screen.getByText('业绩证据待验证')).toBeTruthy()
    expect(screen.queryByText('平台业绩已复核')).toBeNull()
    vi.mocked(api.verifyQuantReport).mockResolvedValue(verified)
    fireEvent.click(screen.getByRole('button', { name: '验证证据' }))
    await screen.findByText('平台回执验算通过')
    // A fresh failed chain check must override a previously cached confirmation.
    expect(screen.queryByText('已确认于区块 #42')).toBeNull()
    expect(screen.getByText('平台业绩已复核')).toBeTruthy()
  })

  it('discards a late verification after selecting another strategy', async () => {
    let resolveVerification!: (value: QuantVerification) => void
    vi.mocked(api.verifyQuantReport).mockReturnValue(new Promise((resolve) => { resolveVerification = resolve }))
    await openMarket()
    fireEvent.click(screen.getByRole('button', { name: '验证证据' }))
    expect(screen.getByRole('button', { name: '正在验证…' }).hasAttribute('disabled')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: /Beta Strategy/ }))
    await act(async () => { resolveVerification(verified) })
    expect(screen.queryByText('平台回执验算通过')).toBeNull()
    expect(screen.getByRole('button', { name: '验证证据' }).hasAttribute('disabled')).toBe(false)
  })

  it('separates demos and ZKP reports and allows clearing an empty filter', async () => {
    await openMarket()
    fireEvent.change(screen.getByLabelText('证据筛选'), { target: { value: 'real' } })
    expect(screen.queryByRole('button', { name: /Alpha Strategy/ })).toBeNull()
    fireEvent.change(screen.getByLabelText('证据筛选'), { target: { value: 'zk' } })
    expect(screen.getByText('暂无符合条件的 ZKP 报告')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Alpha Strategy/ })).toBeTruthy())
  })

  it('shows unavailable rather than fabricated zero returns for an unassessed strategy', async () => {
    vi.mocked(api.listQuantAgents).mockResolvedValue([{ ...agent, latest_report: null }])
    await openMarket()
    expect(screen.queryByText('0.0%')).toBeNull()
    expect(screen.getAllByText('待评测').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '验证证据' }).hasAttribute('disabled')).toBe(true)
  })
})
