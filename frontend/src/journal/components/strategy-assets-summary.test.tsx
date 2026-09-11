import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { request } from '../../request'
import StrategyAssetsSummary from './strategy-assets-summary'
vi.mock('../../request', () => ({ request: vi.fn(), RUNTIME_CHANGED_EVENT: 'atlas-runtime-changed' }))
afterEach(cleanup)

it('keeps venue balances separate from strategy allocations', async () => {
  vi.mocked(request).mockResolvedValue({ accounts: [], runs: [],
    totals: { 'exchange_test:USDT': { environment: 'exchange_test', currency: 'USDT', equity: '200', profit: '0' } },
    account_assets: [{ account_id: 'test', name: 'Binance 测试', environment: 'exchange_test', valuation_complete: true, known_value_usdt: '1000', total_value_usdt: '1000', synced_at: null }] })
  render(<StrategyAssetsSummary />)
  expect(await screen.findByText('1,000 USDT')).toBeTruthy()
  expect(screen.queryByText('1,200 USDT')).toBeNull()
  expect(screen.getByRole('meter', { name: 'Binance 测试 资产占比' }).getAttribute('value')).toBe('1')
})

it('does not display incomplete balances as a complete zero total', async () => {
  vi.mocked(request).mockResolvedValue({ accounts: [], runs: [], totals: {},
    account_assets: [{ account_id: 'test', name: 'OKX 测试', environment: 'exchange_test', valuation_complete: false, known_value_usdt: '100', total_value_usdt: null, synced_at: null }] })
  render(<StrategyAssetsSummary />)
  expect(await screen.findByText('估值待补全')).toBeTruthy()
  expect(screen.getByText('已知部分 100.00 USDT；请同步余额与价格')).toBeTruthy()
  expect(screen.queryByRole('meter')).toBeNull()
})
