import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../../request'
import TradingAssetsPanel from './trading-assets-panel'

vi.mock('../../request', async (importOriginal) => ({ ...await importOriginal<object>(), request: vi.fn() }))
beforeEach(() => {
  window.location.hash = '#/journal/trading?run=run-1'
  vi.mocked(request).mockResolvedValue({
    accounts: [], totals: { USD: { equity: '10100', cash: '4000', profit: '100' } }, limit: 50, offset: 0,
    runs: [{ id: 'run-1', strategy_name: '趋势规则', strategy_version: 2, symbol: 'AAPL', market: 'US', environment: 'platform_sim', return_rate: '0.01' }],
    fills: [{ id: 'fill-1', run_id: 'run-1', signal_id: 'sig-1', side: 'buy', quantity: '10', price: '150', fee: '1.5', fee_currency: 'USD', realized_pnl: '0', pnl_currency: 'USD', environment: 'platform_sim', executed_at: '2026-01-02T00:00:00Z', symbol: 'AAPL', market: 'US', strategy_name: '趋势规则', strategy_version: 2 }],
  } as never)
})
afterEach(cleanup)

it('shows linked strategy fills without writing to the manual ledger', async () => {
  render(<TradingAssetsPanel />)
  expect(await screen.findByText('10,100')).toBeTruthy()
  expect(screen.getByText('10 × 150')).toBeTruthy()
  expect(request).toHaveBeenCalledWith(expect.stringContaining('run_id=run-1'))
})

it('links an unassigned manual fill to its order and leaves unknown profit blank', async () => {
  vi.mocked(request).mockResolvedValue({
    accounts: [], runs: [], totals: {}, limit: 50, offset: 0,
    fills: [{ id: 'manual-fill', run_id: null, order_id: 'order-1', account_id: 'account-1',
      side: 'sell', quantity: '1', price: '100', fee: '0.1', fee_currency: 'USDT',
      realized_pnl: null, pnl_currency: 'USDT', symbol: 'BTC-USDT', market: 'CRYPTO',
      executed_at: '2026-01-02T00:00:00Z' }],
  } as never)
  render(<TradingAssetsPanel />)
  expect(await screen.findByText('成本待补全')).toBeTruthy()
  expect(screen.getByRole('link', { name: '人工订单' }).getAttribute('href'))
    .toBe('#/trading?account=account-1&order=order-1')
})
