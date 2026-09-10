import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import TradingWorkspace from './TradingWorkspace'

vi.mock('../request', async (importOriginal) => ({ ...await importOriginal<object>(), request: vi.fn() }))
const caps = { authorized: true, user_id: 'test-user', venues: [{ venue: 'binance', mode: 'demo', configured: true, can_trade: true }] }
const preview = { id: 'aq-test', order: { venue: 'binance', symbol: 'BTC-USDT', side: 'buy', quantity: '0.001', price: '10000' }, mode: 'demo', expires: 9999999999, state: 'preview', result: {} }
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return caps
    if (path.endsWith('/preview')) return preview
    if (path.endsWith('/confirm')) return { ...preview, state: 'submitted' }
    return []
  })
})
afterEach(cleanup)

it('keeps unconfigured accounts disconnected and trading disabled', async () => {
  vi.mocked(request).mockResolvedValue({ ...caps, authorized: false, venues: [{ venue: 'binance', mode: 'demo', configured: false, can_trade: false }] })
  render(<TradingWorkspace />)
  await screen.findByText('先绑定你的交易账户')
  expect((screen.getByRole('button', { name: '预览订单' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '连接并查询余额' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText('miniQMT · 等待客户端接入')).toBeTruthy()
})

async function prepare() {
  render(<TradingWorkspace />)
  await waitFor(() => expect((screen.getByRole('button', { name: '预览订单' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.change(screen.getByLabelText('交易对'), { target: { value: 'BTC-USDT' } })
  fireEvent.change(screen.getByLabelText('数量（基础币）'), { target: { value: '0.001' } })
  fireEvent.change(screen.getByLabelText('限价（USDT）'), { target: { value: '10000' } })
  fireEvent.click(screen.getByRole('button', { name: '预览订单' }))
  await screen.findByRole('heading', { name: '核对模拟订单' })
}

it('requires exact confirmation and freezes the order being reviewed', async () => {
  await prepare()
  expect(screen.getByLabelText('交易对').closest('fieldset')?.disabled).toBe(true)
  expect((screen.getByRole('button', { name: '确认提交订单' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('确认文字'), { target: { value: '确认模拟下单' } })
  fireEvent.click(screen.getByRole('button', { name: '确认提交订单' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/trading/orders/aq-test/confirm', expect.objectContaining({ body: JSON.stringify({ confirmation: '确认模拟下单' }) })))
  await waitFor(() => expect(screen.queryByRole('heading', { name: '核对模拟订单' })).toBeNull())
})

it('returning to edit discards confirmation and never submits', async () => {
  await prepare()
  fireEvent.change(screen.getByLabelText('确认文字'), { target: { value: '确认模拟下单' } })
  fireEvent.click(screen.getByRole('button', { name: '返回修改' }))
  expect(screen.queryByLabelText('确认文字')).toBeNull()
  expect(vi.mocked(request).mock.calls.some(([path]) => path.endsWith('/confirm'))).toBe(false)
})

it('retains the same preview after a transport failure', async () => {
  await prepare()
  vi.mocked(request).mockRejectedValue(new Error('请求超时，请先查询状态'))
  fireEvent.change(screen.getByLabelText('确认文字'), { target: { value: '确认模拟下单' } })
  fireEvent.click(screen.getByRole('button', { name: '确认提交订单' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('heading', { name: '核对模拟订单' })).toBeTruthy()
})


it('shows a prominent warning for an HTTP-success response with unknown execution state', async () => {
  await prepare()
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/confirm')) return { ...preview, state: 'unknown' }
    if (path.endsWith('/capabilities')) return caps
    if (path === '/trading/orders') return [{ ...preview, state: 'unknown' }]
    return []
  })
  fireEvent.change(screen.getByLabelText('确认文字'), { target: { value: '确认模拟下单' } })
  fireEvent.click(screen.getByRole('button', { name: '确认提交订单' }))
  expect((await screen.findByRole('alert')).textContent).toContain('不要重复下单')
  await screen.findByRole('button', { name: '查询状态' })
})


it('opens a run detail with its curve and attributed fills', async () => {
  const run = { id: 'run_aa', release_id: 'rel_aa', strategy_name: '动量测试', strategy_version: 1,
    account_name: '美股模拟', market: 'US', environment: 'platform_sim', symbol: 'AAPL', interval: '1d',
    status: 'active', initial_cash: '1000', cash: '500', quantity: '5', average_cost: '100',
    realized_pnl: '0', equity: '1050', return_rate: '0.05', currency: 'USD', mark_price: '110',
    position_value: '550', curve: [{ bar_time: 1700000000, equity: '1000' }, { bar_time: 1700100000, equity: '1050' }],
    signals: [], orders: [], fills: [{ id:'fill_aa', side:'buy', quantity:'5', price:'100', fee:'0.5', fee_currency:'USD', executed_at:'2026-09-10T00:00:00Z' }] }
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return caps
    if (path.startsWith('/trading/runs?')) return [run]
    if (path === '/trading/runs/run_aa') return run
    return []
  })
  render(<TradingWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name:'运行详情' }))
  expect(await screen.findByRole('img', { name: '动量测试 净值曲线，共 2 个快照' })).toBeTruthy()
  expect(screen.getByText('费用 0.5 USD')).toBeTruthy()
})
