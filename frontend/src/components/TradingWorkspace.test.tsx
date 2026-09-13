import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import TradingWorkspace from './TradingWorkspace'

vi.mock('../request', async (importOriginal) => ({ ...await importOriginal<object>(), request: vi.fn() }))
const caps = { authorized: true, user_id: 'test-user', venues: [{ venue: 'binance', mode: 'demo', configured: true, can_trade: true }] }
const preview = { id: 'aq-test', order: { venue: 'binance', symbol: 'BTC-USDT', side: 'buy', quantity: '0.001', price: '10000' }, mode: 'demo', expires: 9999999999, state: 'preview', result: {} }
beforeEach(() => {
  vi.resetAllMocks()
  window.history.replaceState(null, '', '#/trading')
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
  await screen.findByText('当前用户未绑定')
  expect(screen.queryByRole('button', { name: '预览订单' })).toBeNull()
  expect(screen.queryByRole('button', { name: '验证连接' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看接入指引' }))
  expect(screen.getByText('ATLAS_TRADING_OWNER_ID')).toBeTruthy()
  expect(screen.getByText('miniQMT · 等待客户端接入')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '人工下单' }))
  expect((await screen.findByRole('button', { name: '预览订单' }) as HTMLButtonElement).disabled).toBe(true)
})

async function prepare() {
  render(<TradingWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: '人工下单' }))
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
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect((await screen.findByRole('alert')).textContent).toContain('不要重复下单')
  fireEvent.click(screen.getByRole('button', { name: /查看委托/ }))
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
  fireEvent.click(screen.getByRole('button', { name: /^策略运行/ }))
  fireEvent.click(await screen.findByRole('button', { name:'运行详情' }))
  expect(await screen.findByRole('img', { name: '动量测试 净值曲线，共 2 个快照' })).toBeTruthy()
  expect(screen.getByText('费用 0.5 USD')).toBeTruthy()
})

const bothVenues = { ...caps, venues: [...caps.venues, { venue: 'okx', mode: 'live', configured: true, can_trade: false }] }
function connectionMock(account: () => Promise<unknown>, capabilities = bothVenues) {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return capabilities
    if (path.endsWith('/account')) return account()
    return []
  })
}

it('separates configured credentials, verified connection and trading permission', async () => {
  connectionMock(async () => ({ balances: [] }))
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  fireEvent.click(screen.getByRole('button', { name: '欧易 OKX' }))
  expect(screen.getByText('实盘环境 · 下单将使用真实资金')).toBeTruthy()
  expect(screen.getByText('交易权限：提交未启用 · 可验证连接')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '验证连接' }))
  await screen.findByText('连接验证成功')
  expect(screen.getByText('暂无余额记录。连接已验证成功。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '人工下单' }))
  await screen.findByRole('dialog')
  expect((screen.getByRole('button', { name: '预览订单' }) as HTMLButtonElement).disabled).toBe(true)
})

it('shows balance results and clears them when changing venues', async () => {
  connectionMock(async () => ({ balances: [{ asset: 'BTC', available: '1.234', locked: '0.02' }] }))
  render(<TradingWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '验证连接' }))
  await screen.findByText('1.234')
  expect(screen.getByText('0.02')).toBeTruthy()
  expect(screen.getByText(/查询于/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '欧易 OKX' }))
  expect(screen.queryByText('1.234')).toBeNull()
  expect(screen.getByText('已配置，待验证')).toBeTruthy()
})

it('keeps a connection failure local and allows retry', async () => {
  let attempts = 0
  connectionMock(async () => { if (!attempts++) throw new Error('连接超时'); return { balances: [] } })
  render(<TradingWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '验证连接' }))
  const message = await screen.findByText('连接超时')
  expect(message.closest('[aria-label="账户与连接"]')?.getAttribute('aria-label')).toBe('账户与连接')
  fireEvent.click(screen.getByRole('button', { name: '重试连接' }))
  await screen.findByText('连接验证成功')
  expect(screen.queryByText('连接超时')).toBeNull()
})

it('ignores a late balance response from the previous venue and prevents duplicate queries', async () => {
  let resolve!: (value: unknown) => void
  const pending = new Promise((done) => { resolve = done })
  connectionMock(() => pending)
  render(<TradingWorkspace />)
  const verify = await screen.findByRole('button', { name: '验证连接' })
  fireEvent.click(verify); fireEvent.click(verify)
  expect((screen.getByRole('button', { name: '正在验证…' }) as HTMLButtonElement).disabled).toBe(true)
  expect(vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/account'))).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '欧易 OKX' }))
  await act(async () => resolve({ balances: [{ asset: 'OLD', available: '99', locked: '0' }] }))
  expect(screen.queryByText('OLD')).toBeNull()
  expect(screen.queryByText('连接验证成功')).toBeNull()
  expect((screen.getByRole('button', { name: '验证连接' }) as HTMLButtonElement).disabled).toBe(false)
})

it('locks venue switching while reviewing an order and restores it on return', async () => {
  await prepare()
  expect((screen.getByRole('button', { name: '欧易 OKX' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '返回修改' }))
  expect((screen.getByRole('button', { name: '欧易 OKX' }) as HTMLButtonElement).disabled).toBe(false)
})

it('offers inline configuration guidance for unconfigured credentials', async () => {
  connectionMock(async () => ({ balances: [] }), { ...caps, venues: [{ ...caps.venues[0], configured: false, can_trade: false }] })
  render(<TradingWorkspace />)
  await screen.findByText('账户未配置')
  fireEvent.click(screen.getByRole('button', { name: '查看接入指引' }))
  expect(screen.getByText('ATLAS_BINANCE_API_KEY')).toBeTruthy()
  expect(screen.getByText('test-user')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '重新检测配置' }))
  await waitFor(() => expect(vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/capabilities')).length).toBe(2))
})

it('preserves keyboard focus on the venue button after switching', async () => {
  connectionMock(async () => ({ balances: [] }))
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  const okx = screen.getByRole('button', { name: '欧易 OKX' })
  okx.focus()
  fireEvent.click(okx)
  await waitFor(() => expect(okx.getAttribute('aria-pressed')).toBe('true'))
  expect(document.activeElement).toBe(okx)
})

it('keeps forms out of the overview and opens each task on demand', async () => {
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  expect(screen.queryByLabelText('分配资金')).toBeNull()
  expect(screen.queryByLabelText('交易对')).toBeNull()
  fireEvent.click(screen.getAllByRole('button', { name: '新建运行' })[0])
  expect(await screen.findByRole('dialog')).toBeTruthy()
  expect(screen.getByLabelText('分配资金')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '关闭操作面板' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: /^委托记录/ }))
  expect(await screen.findByText('每一笔委托，都有迹可循')).toBeTruthy()
})

it('retains an order preview when the panel is closed and reopened', async () => {
  await prepare()
  fireEvent.click(screen.getByRole('button', { name: '关闭操作面板' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '人工下单' }))
  expect(await screen.findByRole('heading', { name: '核对模拟订单' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '欧易 OKX' }) as HTMLButtonElement).disabled).toBe(true)
})

it('does not reopen a dismissed release form on background refresh', async () => {
  window.history.replaceState(null, '', '#/trading?release=release-test')
  render(<TradingWorkspace />)
  await screen.findByRole('dialog')
  fireEvent.click(screen.getByRole('button', { name: '关闭操作面板' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '账户概览' }))
  fireEvent.click(screen.getByRole('button', { name: '刷新全部数据' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '刷新全部数据' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.getByRole('button', { name: '账户概览' }).getAttribute('aria-current')).toBe('page')
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('creates and starts a strategy with the existing form contract', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return caps
    if (path === '/trading/accounts') return [{ id: 'test-account', name: '加密货币模拟', market: 'CRYPTO', environment: 'platform_sim', currency: 'USD' }]
    if (path === '/strategy-releases') return [{ id: 'test-release', name: '测试策略', version: 1, owned: true }]
    if (path === '/trading/runs') return { id: 'new-run' }
    return []
  })
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  fireEvent.click(screen.getAllByRole('button', { name: '新建运行' })[0])
  const start = await screen.findByRole('button', { name: '启动模拟' })
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(start)
  await waitFor(() => expect(request).toHaveBeenCalledWith('/trading/runs/new-run/start', { method: 'POST' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('button', { name: '策略运行' }).getAttribute('aria-current')).toBe('page')
  const call = vi.mocked(request).mock.calls.find(([path]) => path === '/trading/runs')
  expect(JSON.parse(call?.[1]?.body as string)).toMatchObject({ release_id: 'test-release', account_id: 'test-account', market: 'CRYPTO', environment: 'platform_sim', symbol: 'BTC-USD', initial_cash: '10000' })
})


it('preserves an edited strategy version across background refreshes of a release deep link', async () => {
  window.history.replaceState(null, '', '#/trading?release=release-a')
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return caps
    if (path === '/strategy-releases') return [{ id: 'release-a', name: '策略 A', version: 1, owned: true }, { id: 'release-b', name: '策略 B', version: 1, owned: true }]
    return []
  })
  render(<TradingWorkspace />)
  const selector = await screen.findByLabelText('策略版本')
  await screen.findByRole('option', { name: '策略 B · v1' })
  fireEvent.change(selector, { target: { value: 'release-b' } })
  await act(async () => window.dispatchEvent(new Event('atlas-runtime-changed')))
  await waitFor(() => expect(vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/capabilities')).length).toBeGreaterThan(1))
  expect((selector as HTMLSelectElement).value).toBe('release-b')
})

it('discards a slow load after the URL has changed', async () => {
  let resolveOld!: (value: unknown) => void
  let calls = 0
  const oldRequest = new Promise((resolve) => { resolveOld = resolve })
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return ++calls === 1 ? oldRequest : caps
    if (path === '/strategy-releases') return [{ id: 'release-a', name: '策略 A', version: 1, owned: true }]
    return []
  })
  render(<TradingWorkspace />)
  await waitFor(() => expect(calls).toBe(1))
  await act(async () => { window.history.replaceState(null, '', '#/trading?release=release-a'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
  await screen.findByRole('dialog')
  fireEvent.click(screen.getByRole('button', { name: '关闭操作面板' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await act(async () => resolveOld({ ...caps, authorized: false }))
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '账户概览' }))
  expect(screen.getByText('已配置，待验证')).toBeTruthy()
  expect(screen.queryByText('当前用户未绑定')).toBeNull()
})

it('accepts default risk values in the browser validity model', async () => {
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  fireEvent.click(screen.getAllByRole('button', { name: '新建运行' })[0])
  const participation = screen.getByLabelText('成交参与率') as HTMLInputElement
  expect(participation.validity.stepMismatch).toBe(false)
  expect(participation.checkValidity()).toBe(true)
})

it('opens demo account setup on demand for the selected exchange', async () => {
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  expect(screen.queryByLabelText('模拟 API Key')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '欧易 OKX' }))
  fireEvent.click(screen.getByRole('button', { name: '接入模拟账户' }))
  expect((screen.getByLabelText('模拟交易所') as HTMLSelectElement).value).toBe('okx')
  expect(screen.getByLabelText('模拟 Passphrase')).toBeTruthy()
})

it('enables automatic execution only for an exchange test run', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/capabilities')) return caps
    if (path === '/trading/accounts') return [{ id: 'test-account', name: '加密货币模拟', market: 'CRYPTO', environment: 'exchange_test', currency: 'USDT' }]
    if (path === '/strategy-releases') return [{ id: 'test-release', name: '测试策略', version: 1, owned: true }]
    if (path === '/trading/runs') return { id: 'new-run' }
    return []
  })
  render(<TradingWorkspace />)
  await screen.findByText('已配置，待验证')
  fireEvent.click(screen.getAllByRole('button', { name: '新建运行' })[0])
  fireEvent.change(screen.getByLabelText('运行环境'), { target: { value: 'exchange_test' } })
  fireEvent.click(screen.getByLabelText('自动执行模拟订单（仅测试资金）'))
  const start = await screen.findByRole('button', { name: '启动测试交易' })
  await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(start)
  await waitFor(() => expect(request).toHaveBeenCalledWith('/trading/runs/new-run/start', { method: 'POST' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('button', { name: '策略运行' }).getAttribute('aria-current')).toBe('page')
  const call = vi.mocked(request).mock.calls.find(([path]) => path === '/trading/runs')
  expect(JSON.parse(call?.[1]?.body as string)).toMatchObject({ release_id: 'test-release', account_id: 'test-account', market: 'CRYPTO', environment: 'exchange_test', demo_auto: true, symbol: 'BTC-USDT', initial_cash: '10000' })
})
