import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import TradingWorkspace from './TradingWorkspace'

vi.mock('../request', () => ({ request: vi.fn() }))
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
    return [{ ...preview, state: 'unknown' }]
  })
  fireEvent.change(screen.getByLabelText('确认文字'), { target: { value: '确认模拟下单' } })
  fireEvent.click(screen.getByRole('button', { name: '确认提交订单' }))
  expect((await screen.findByRole('alert')).textContent).toContain('不要重复下单')
  await screen.findByRole('button', { name: '查询状态' })
})
