import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PortfolioResult } from '../types'
import { ResultsPanel } from './ResultsPanel'

vi.mock('./EquityChart', () => ({ EquityChart: () => null }))
afterEach(cleanup)

const result: PortfolioResult = {
  run_id: 'test', created_at: '2026-09-07', valuation_currency: 'USD', data_source: 'test',
  strategy: { id: 'all_weather', name: '组合', category: '配置', description: '', suitable_for: '', risk_level: '中', mode: 'portfolio', parameters: [] },
  assets: [], weights: {}, weight_history: [], equity: [], metrics: {}, risk_contribution: {},
  correlation: { SPY: { SPY: 1, TLT: null }, TLT: { SPY: null, TLT: null } }, warnings: [],
  trades: [{ id: 1, time: 1_750_003_800, side: 'buy', reason: '再平衡', price: 50,
    quantity: 2, notional: 100, fee: 0.1, slippage_cost: 0, position_after: 2,
    cash_after: 899.9, realized_pnl: null }],
}

describe('result interpretation', () => {
  it('uses the actual portfolio valuation currency and labels intraday local time', () => {
    render(<ResultsPanel result={result} loading={false} panelMode="normal" onPanelMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('tab', { name: /交易记录/ }))
    expect(screen.getByRole('columnheader', { name: '成交额（USD）' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: '时间（本地）' })).toBeTruthy()
    expect(screen.getByText('US$100')).toBeTruthy()
  })

  it('does not invent correlation for constant series', () => {
    render(<ResultsPanel result={result} loading={false} panelMode="normal" onPanelMode={vi.fn()} />)
    fireEvent.click(screen.getByRole('tab', { name: '风险分析' }))
    expect(screen.getByRole('heading', { name: '资产相关性' })).toBeTruthy()
    expect(screen.getAllByRole('cell', { name: '—' })).toHaveLength(3)
    expect(screen.queryByText('NaN')).toBeNull()
  })
})
