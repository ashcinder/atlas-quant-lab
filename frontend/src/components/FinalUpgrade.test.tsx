import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { QuantAgent, QuantReport, StrategyRun } from '../types'
import BehaviorMonitor from './BehaviorMonitor'
import SummaryExport from './SummaryExport'
import { reportSummary, runSummary } from './report-summary'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const check = { rule_version: 'position_limit_v1', limit_bps: 6000, status: 'deviation' as const, reason: '实际仓位超过声明上限',
  period_start: 1700000000, period_end: 1700003600, snapshot_count: 2, latest_ratio: '0.75', peak_ratio: '0.75', deviation_count: 1,
  first_deviation_at: 1700003600, points: [{ time: 1700000000, ratio: '0.4' }, { time: 1700003600, ratio: '0.75' }] }
const run = { id: 'run-a', strategy_name: '测试策略', release_id: 'release-a', strategy_version: 1, strategy_hash: 'hash',
  valuation_at: 1700003600, valuation_status: 'recorded', valuation_complete: true, initial_cash: '1000', equity: '1100',
  return_rate: '0.1', position_value: '825', market: 'CRYPTO', symbol: 'BTC-USDT', environment: 'platform_sim', status: 'active',
  behavior_check: check, python_source: 'private-source', api_key: 'secret', account_id: 'hidden-account' } as unknown as StrategyRun

describe('final upgrade behavior and summaries', () => {
  it('shows computed deviation and the proof boundary', () => {
    render(<BehaviorMonitor run={run} />)
    expect(screen.getByText('发现仓位偏离')).toBeTruthy()
    expect(screen.getByText(/最近仓位 75.00%/)).toBeTruthy()
    expect(screen.getByRole('img', { name: '实际仓位与声明上限曲线' })).toBeTruthy()
    expect(screen.getByText(/普通规则计算/)).toBeTruthy()
  })
  it('shows unavailable rather than normal when data is missing', () => {
    render(<BehaviorMonitor run={{ ...run, behavior_check: { ...check, status: 'insufficient_data', latest_ratio: null, peak_ratio: null, points: [], reason: '尚无快照' } }} />)
    expect(screen.getByText('不可评估')).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
  })
  it('only exports allowlisted run fields and does not turn allocation into valuation', () => {
    const summary = runSummary({ ...run, valuation_at: null })
    const json = JSON.stringify(summary)
    expect(json).not.toContain('private-source'); expect(json).not.toContain('secret'); expect(json).not.toContain('hidden-account')
    expect(summary.valuation.equity).toBeNull(); expect(summary.valuation.return_rate).toBeNull()
    expect(summary.evidence.zk_proven).toBe(false)
  })
  it('does not export private report fields or manufacture a source or fee assumption', () => {
    const report = { id: 'report-a', metrics: { sharpe: 1, api_key: 'secret' }, score: 99, performance_score: null, zk_proof_id: 'proof-a',
      private_source: 'private-source' } as unknown as QuantReport
    const agent = { id: 'a', name: 'A', strategy_commitment: 'hash', api_key: 'secret' } as unknown as QuantAgent
    const summary = reportSummary(agent, report, null)
    expect(JSON.stringify(summary)).not.toMatch(/secret|private-source/)
    expect(summary.report.performance_score).toBeNull(); expect(summary.report.fees).toBeNull()
    expect(summary.evidence.verified_this_session).toBe(false)
  })
  it('prints the same summary with text nodes so user content cannot become HTML', () => {
    const doc = document.implementation.createHTMLDocument('')
    const print = vi.fn()
    vi.spyOn(window, 'open').mockReturnValue({ document: doc, focus: vi.fn(), print, opener: window } as unknown as Window)
    render(<SummaryExport title="报告摘要" identifier="a" summary={{ name: '<script>unsafe</script>', missing: null }} />)
    fireEvent.click(screen.getByRole('button', { name: '打印摘要' }))
    expect(print).toHaveBeenCalledOnce(); expect(doc.querySelector('script')).toBeNull()
    expect(doc.body.textContent).toContain('<script>unsafe</script>'); expect(doc.body.textContent).toContain('未记录')
  })
  it('explains popup blocking and supports retry', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    render(<SummaryExport title="摘要" identifier="a" summary={{ id: 'a' }} />)
    fireEvent.click(screen.getByRole('button', { name: '打印摘要' }))
    expect(screen.getByRole('alert').textContent).toContain('允许弹出窗口')
  })
})
