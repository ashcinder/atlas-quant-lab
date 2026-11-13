import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { requestLabNavigation } from '../lab-navigation'
import type { LabBacktestSettings, LabRunSummary, LabStrategy } from '../lab-strategy-types'
import { ApiError } from '../request'
import type { Asset, BacktestResult } from '../types'
import { StrategyLabWorkspace } from './StrategyLabWorkspace'

vi.mock('../api', () => ({ api: {
  listLabStrategies: vi.fn(), getLabStrategy: vi.fn(), createLabStrategy: vi.fn(), updateLabStrategy: vi.fn(),
  listLabRuns: vi.fn(), runBacktest: vi.fn(), getRun: vi.fn(), searchAssets: vi.fn(),
} }))
vi.mock('../request', async (original) => ({ ...await original<typeof import('../request')>(), request: vi.fn().mockResolvedValue({ configured: false }) }))
vi.mock('./PublishRuntimeStrategy', () => ({ PublishRuntimeStrategy: () => null }))
vi.mock('./ResultsPanel', () => ({ ResultsPanel: ({ result }: { result: BacktestResult | null }) => <output>{result?.run_id}</output> }))

const asset: Asset = { symbol: 'BTC-USD', name: '比特币', asset_class: 'crypto', exchange: 'CRYPTO', currency: 'USD', timezone: 'UTC', tags: [] }
const settings: LabBacktestSettings = {
  symbol: 'BTC-USD', asset_class: 'crypto', data_source: 'auto', interval: '1d', start: null, end: null, adjustment: 'auto',
  initial_capital: 100_000, commission_rate: 0.001, slippage_rate: 0.0005, spread_rate: 0.0005, max_position: 0.95, max_participation_rate: 0.01,
}
const saved: LabStrategy = {
  id: 'strategy-a', name: '我的测试策略', language: 'python', source: 'def target_bps(index, close, sma):\n    return 5000',
  revision: 1, updated_at: '2026-11-10T00:00:00Z', settings,
}
const another: LabStrategy = { ...saved, id: 'strategy-b', name: '另一份策略', source: '# other strategy' }
const props = { ownerId: 'owner-a', active: true, assets: [asset], defaults: settings, onRunSaved: vi.fn() }

const editor = () => screen.getByLabelText('Python 策略代码')
async function open() {
  render(<StrategyLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '打开 我的测试策略' }))
  await screen.findByLabelText('Python 策略代码')
}
beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/#research')
  vi.mocked(api.listLabStrategies).mockResolvedValue([saved, another])
  vi.mocked(api.getLabStrategy).mockImplementation(async (_owner, id) => id === saved.id ? saved : another)
  vi.mocked(api.listLabRuns).mockResolvedValue([])
})
afterEach(cleanup)

it('starts with a blank editor and saves source and backtest settings together', async () => {
  vi.mocked(api.createLabStrategy).mockImplementation(async (_owner, _id, draft) => ({ ...saved, ...draft }))
  render(<StrategyLabWorkspace {...props} />)
  await screen.findByRole('button', { name: '打开 我的测试策略' })
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  expect(editor()).toHaveValue('')
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '图形化' })).toBeNull()
  fireEvent.change(editor(), { target: { value: saved.source } })
  fireEvent.change(screen.getByLabelText('初始资金'), { target: { value: '12345' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.createLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), expect.objectContaining({ source: saved.source, settings: { ...settings, initial_capital: 12345 } }))
})

it('imports a source file as a new unsaved draft', async () => {
  const { container } = render(<StrategyLabWorkspace {...props} />)
  const file = new File(['// code'], 'range.ts')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('// code').buffer })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  expect(await screen.findByLabelText('TypeScript 策略代码')).toHaveValue('// code')
  expect(screen.getByLabelText('代码策略名称')).toHaveValue('range')
  expect(api.createLabStrategy).not.toHaveBeenCalled()
})

it('guards navigation and keeps local edits on a revision conflict', async () => {
  vi.mocked(api.updateLabStrategy).mockRejectedValue(new ApiError('策略已在其他窗口更新。', 'http', 409))
  await open()
  fireEvent.change(editor(), { target: { value: '# keep this' } })
  const leave = vi.fn()
  act(() => requestLabNavigation(leave))
  const confirmation = screen.getByRole('alertdialog')
  fireEvent.click(within(confirmation).getByRole('button', { name: '保存并离开' }))
  await within(confirmation).findByText('策略已在其他窗口更新。')
  expect(leave).not.toHaveBeenCalled()
  expect(editor()).toHaveValue('# keep this')
  fireEvent.click(within(confirmation).getByRole('button', { name: '取消，保留当前内容' }))
  expect(screen.getByRole('button', { name: '重新加载已保存版本' })).toBeVisible()
  act(() => requestLabNavigation(leave))
  fireEvent.click(screen.getByRole('button', { name: '放弃修改' }))
  expect(leave).toHaveBeenCalledOnce()
  expect(screen.getByRole('heading', { name: '我的策略' })).toBeVisible()
})

it('runs with the clicked draft and shows historical snapshots without replacing the editor', async () => {
  let finish!: (value: BacktestResult) => void
  vi.mocked(api.runBacktest).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const historical = { id: 'historical-run', mode: 'single', strategy_id: 'python_bounded', symbol: 'BTC-USD', created_at: saved.updated_at,
    total_return: 0.12, max_drawdown: -0.02, status: 'completed', source_sha256: 'a'.repeat(64), settings: { ...settings, initial_capital: 9876 } } satisfies LabRunSummary
  vi.mocked(api.listLabRuns).mockResolvedValue([historical])
  vi.mocked(api.getRun).mockResolvedValue({ run_id: historical.id } as BacktestResult)
  await open()
  fireEvent.change(editor(), { target: { value: '# run snapshot' } })
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  fireEvent.change(editor(), { target: { value: '# later edit' } })
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({ python_source: '# run snapshot', lab_strategy_id: saved.id, initial_capital: settings.initial_capital }), expect.any(AbortSignal), props.ownerId)
  await act(async () => finish({ run_id: 'current-result' } as BacktestResult))
  expect(screen.getByText('current-result')).toBeVisible()
  expect(props.onRunSaved).toHaveBeenCalledOnce()
  expect(api.updateLabStrategy).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '历史回测' }))
  fireEvent.click(await screen.findByRole('button', { name: /查看 .* 的回测/ }))
  expect(await screen.findByText('historical-run')).toBeVisible()
  fireEvent.click(screen.getByText('本次运行参数和源码摘要'))
  expect(screen.getByText(historical.source_sha256)).toBeVisible()
  expect(screen.getByText('9,876')).toBeVisible()
  expect(editor()).toHaveValue('# later edit')
})

it('ignores an old result after leaving the strategy', async () => {
  let finish!: (value: BacktestResult) => void
  vi.mocked(api.runBacktest).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  await open()
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  const signal = vi.mocked(api.runBacktest).mock.calls[0][1]
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  expect(signal?.aborted).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '打开 另一份策略' }))
  await waitFor(() => expect(editor()).toHaveValue(another.source))
  await act(async () => finish({ run_id: 'late-result' } as BacktestResult))
  expect(screen.queryByText('late-result')).toBeNull()
  expect(props.onRunSaved).not.toHaveBeenCalled()
})

it('reuses the creation identifier after a lost response and keeps newer edits', async () => {
  vi.mocked(api.createLabStrategy)
    .mockRejectedValueOnce(new ApiError('请求超时', 'timeout'))
    .mockImplementation(async (_owner, _id, draft) => ({ ...saved, ...draft }))
  render(<StrategyLabWorkspace {...props} />)
  await screen.findByRole('button', { name: '打开 我的测试策略' })
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  fireEvent.change(editor(), { target: { value: '# original submission' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('请求超时')
  fireEvent.change(editor(), { target: { value: '# newer edit' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已恢复上次保存。请再保存一次，提交后续修改。')
  const [first, retried] = vi.mocked(api.createLabStrategy).mock.calls
  expect(first).toEqual(retried)
  expect(editor()).toHaveValue('# newer edit')
  expect(screen.getByText('未保存')).toBeVisible()
})
