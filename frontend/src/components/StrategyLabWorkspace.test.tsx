import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { requestLabNavigation } from '../lab-navigation'
import { defaultMultiSettings, type LabBacktestSettings, type LabMultiDraft, type LabMultiJob, type LabRunSummary, type LabStrategy } from '../lab-strategy-types'
import { labMultiApi } from '../lab-multi-api'
import { ApiError, request } from '../request'
import type { Asset, BacktestResult } from '../types'
import { LabMultiBacktestResult } from './LabMultiBacktest'
import { StrategyLabWorkspace } from './StrategyLabWorkspace'

vi.mock('../api', () => ({ api: {
  listLabStrategies: vi.fn(), getLabStrategy: vi.fn(), createLabStrategy: vi.fn(), updateLabStrategy: vi.fn(),
  listLabRuns: vi.fn(), runBacktest: vi.fn(), getRun: vi.fn(), searchAssets: vi.fn(),
} }))
vi.mock('../request', async (original) => ({ ...await original<typeof import('../request')>(), request: vi.fn().mockResolvedValue({ configured: false }) }))
vi.mock('../lab-multi-api', async original => {
  const api = await original<typeof import('../lab-multi-api')>()
  return { ...api, labMultiApi: { ...api.labMultiApi, capabilities: vi.fn().mockResolvedValue({ available: false }),
    examples: vi.fn().mockResolvedValue([]), jobs: vi.fn().mockResolvedValue([]), job: vi.fn(),
    preflight: vi.fn(), start: vi.fn(), release: vi.fn(), inspect: vi.fn() } }
})
vi.mock('./EquityChart', () => ({ EquityChart: () => <div>账户净值曲线</div> }))
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
  vi.mocked(labMultiApi.capabilities).mockReset().mockResolvedValue({ available: false, reason: null })
  vi.mocked(labMultiApi.jobs).mockReset().mockResolvedValue([])
  vi.mocked(labMultiApi.job).mockReset()
  vi.mocked(labMultiApi.preflight).mockReset()
  vi.mocked(labMultiApi.start).mockReset()
  vi.mocked(labMultiApi.release).mockReset()
  vi.mocked(labMultiApi.inspect).mockReset()
  vi.mocked(request).mockReset().mockResolvedValue({ configured: false })
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
  fireEvent.click(screen.getByRole('button', { name: '单标的受限 Python' }))
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
  expect(screen.getAllByText(/当前修改尚未回测/).some(element => element.getAttribute('role') === 'status')).toBe(true)
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
  fireEvent.click(screen.getByRole('button', { name: '单标的受限 Python' }))
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

it('shows the inherited minute interval and submits the same value', async () => {
  const minute = { ...saved, settings: { ...settings, interval: '1m' as const } }
  vi.mocked(api.getLabStrategy).mockResolvedValue(minute)
  vi.mocked(api.runBacktest).mockResolvedValue({ run_id: 'minute-run' } as BacktestResult)
  await open()
  expect(screen.getByLabelText('行情周期')).toHaveValue('1m')
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await screen.findByText('minute-run')
  expect(api.runBacktest).toHaveBeenCalledWith(expect.objectContaining({ interval: '1m' }),
    expect.any(AbortSignal), props.ownerId)
})

it('creates a multi-stock draft without inheriting the single symbol', async () => {
  vi.mocked(api.createLabStrategy).mockImplementation(async (_owner, _id, draft) => ({ ...saved, ...draft }))
  render(<StrategyLabWorkspace {...props} />)
  await screen.findByRole('button', { name: '打开 我的测试策略' })
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  fireEvent.click(screen.getByRole('button', { name: 'A 股多标的 Python' }))
  expect(screen.queryByLabelText('回测标的')).toBeNull()
  for (const symbol of ['600519.SS', '000001.SZ']) {
    fireEvent.change(screen.getByLabelText('搜索或输入股票代码'), { target: { value: symbol } })
    fireEvent.click(screen.getByRole('button', { name: '加入股票池' }))
  }
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.createLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), expect.objectContaining({
    kind: 'multi_python', settings: expect.objectContaining({ symbols: ['600519.SS', '000001.SZ'] }),
  }))
})

const nativeSource = 'def init(context):\n    context.ready = False\n\ndef handle_bar(context, bar_dict):\n    pass\n'
const nativeDraft: LabMultiDraft = { kind: 'multi_python', language: 'python', name: '原生日线策略', source: nativeSource,
  settings: { ...defaultMultiSettings, symbols: ['600519.SS', '000001.SZ'], engine_id: 'rqalpha' } }
const nativeSaved: LabStrategy = { ...nativeDraft, id: 'native-strategy', revision: 1, updated_at: saved.updated_at }
const nativeJob: LabMultiJob = { id: 'native-job', strategy_id: nativeSaved.id, revision: 1, status: 'succeeded', progress: 1,
  error: null, created_at: saved.updated_at, settings: nativeDraft.settings, source_sha256: 'b'.repeat(64),
  dataset_sha256: 'c'.repeat(64), engine_id: 'rqalpha', engine_version: '6.5.0', matching_type: 'current_bar',
  result: { initial_capital: 1_000_000, final_equity: 1_000_000, total_return: 0, max_drawdown: 0,
    equity: [{ time: 1735801200, equity: 1_000_000, cash: 1_000_000 }], trades: [] } }

function mockNativeSaved() {
  vi.mocked(api.listLabStrategies).mockResolvedValue([nativeSaved])
  vi.mocked(api.getLabStrategy).mockResolvedValue(nativeSaved)
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ available: true, reason: null, engine_id: 'rqalpha', engine_version: '6.5.0', can_release: false, matching_type: 'current_bar' })
}

async function openNative() {
  mockNativeSaved()
  render(<StrategyLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '打开 原生日线策略' }))
  await screen.findByLabelText('Python 策略代码')
}

it('creates and saves an explicit native daily draft with an untouched single-stock default', async () => {
  vi.mocked(api.createLabStrategy).mockImplementation(async (_owner, id, draft) => ({ ...draft, id, revision: 1, updated_at: saved.updated_at }))
  render(<StrategyLabWorkspace {...props} />)
  await screen.findByRole('button', { name: '打开 我的测试策略' })
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  fireEvent.click(screen.getByRole('button', { name: 'RQAlpha 原生日线 Python' }))
  expect((editor() as HTMLTextAreaElement).value).toContain('def init(context):')
  expect((editor() as HTMLTextAreaElement).value).toContain('context.symbols')
  expect((editor() as HTMLTextAreaElement).value).toContain('context.parameters')
  expect((editor() as HTMLTextAreaElement).value).not.toContain('generate_targets')
  expect(screen.getByLabelText('回测引擎')).toHaveValue('rqalpha')
  expect(screen.getByLabelText('行情周期')).toHaveValue('1d')
  expect(screen.getByLabelText('行情周期')).toBeDisabled()
  fireEvent.change(screen.getByLabelText('搜索或输入股票代码'), { target: { value: '430047.BJ' } })
  expect(screen.getByRole('button', { name: '加入股票池' })).toBeDisabled()
  for (const symbol of nativeDraft.settings.symbols) {
    fireEvent.change(screen.getByLabelText('搜索或输入股票代码'), { target: { value: symbol } })
    fireEvent.click(screen.getByRole('button', { name: '加入股票池' }))
  }
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.createLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), expect.objectContaining({
    kind: 'multi_python', settings: expect.objectContaining({ engine_id: 'rqalpha', interval: '1d', symbols: nativeDraft.settings.symbols }),
  }))
  expect(screen.queryByRole('button', { name: '创建运行版本' })).toBeNull()
  expect(labMultiApi.release).not.toHaveBeenCalled()
})

it('imports Python only after an explicit native engine choice and preserves imported code', async () => {
  vi.mocked(api.createLabStrategy).mockImplementation(async (_owner, id, draft) => ({ ...draft, id, revision: 1, updated_at: saved.updated_at }))
  const { container } = render(<StrategyLabWorkspace {...props} />)
  const file = new File([nativeSource], 'native.py')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode(nativeSource).buffer })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  expect(await screen.findByRole('region', { name: '导入策略类型' })).toBeVisible()
  expect(screen.queryByLabelText('Python 策略代码')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'RQAlpha 原生日线 Python' }))
  expect(await screen.findByLabelText('Python 策略代码')).toHaveValue(nativeSource)
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.createLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), expect.objectContaining({
    source: nativeSource, settings: expect.objectContaining({ engine_id: 'rqalpha' }),
  }))
})

it('sends the selected engine to static checking and clears the conclusion when it changes', async () => {
  await openNative()
  vi.mocked(request).mockImplementation(async path => path === '/lab-multi/check'
    ? { valid: true, error: null } : { configured: false })
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  expect(await screen.findByText('语法与入口静态检查通过')).toBeVisible()
  expect(screen.getByText('仅静态检查，未运行策略。')).toBeVisible()
  expect(request).toHaveBeenCalledWith('/lab-multi/check', expect.objectContaining({
    body: JSON.stringify({ source: nativeSource, engine_id: 'rqalpha' }),
  }))
  fireEvent.change(screen.getByLabelText('回测引擎'), { target: { value: 'atlas_portfolio' } })
  expect(editor()).toHaveValue(nativeSource)
  expect(screen.queryByText('语法与入口静态检查通过')).toBeNull()
  expect(screen.getByText('未保存')).toBeVisible()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
})

it('does not unlock a changed engine from an older capabilities response', async () => {
  const atlasSaved: LabStrategy = { ...nativeDraft, id: nativeSaved.id, revision: 1, updated_at: saved.updated_at,
    settings: { ...nativeDraft.settings, engine_id: 'atlas_portfolio' as const } }
  vi.mocked(api.listLabStrategies).mockResolvedValue([atlasSaved])
  vi.mocked(api.getLabStrategy).mockResolvedValue(atlasSaved)
  vi.mocked(api.updateLabStrategy).mockImplementation(async (_owner, id, revision, draft) => ({ ...draft, id, revision: revision + 1, updated_at: saved.updated_at }))
  let oldResult!: (value: { available: boolean; reason: null }) => void
  let nativeResult!: (value: { available: boolean; reason: string | null }) => void
  vi.mocked(labMultiApi.capabilities).mockImplementation((_owner, _signal, engine) => new Promise(resolve => {
    if (engine === 'rqalpha') nativeResult = resolve
    else oldResult = resolve
  }))
  render(<StrategyLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '打开 原生日线策略' }))
  await screen.findByLabelText('回测引擎')
  await waitFor(() => expect(labMultiApi.capabilities).toHaveBeenCalledWith(props.ownerId, expect.any(AbortSignal), 'atlas_portfolio'))
  const oldSignal = vi.mocked(labMultiApi.capabilities).mock.calls[0][1]
  fireEvent.change(screen.getByLabelText('回测引擎'), { target: { value: 'rqalpha' } })
  expect(oldSignal?.aborted).toBe(true)
  await waitFor(() => expect(labMultiApi.capabilities).toHaveBeenCalledWith(props.ownerId, expect.any(AbortSignal), 'rqalpha'))
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  await act(async () => oldResult({ available: true, reason: null }))
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  await act(async () => nativeResult({ available: false, reason: '原生环境未就绪' }))
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(screen.getByText('原生环境未就绪')).toBeVisible()
  expect(editor()).toHaveValue(nativeSource)
})

it('reopens native history without executing, exposes its metadata, and blocks legacy publishing', async () => {
  mockNativeSaved()
  vi.mocked(labMultiApi.jobs).mockResolvedValue([nativeJob])
  vi.mocked(labMultiApi.job).mockResolvedValue(nativeJob)
  render(<StrategyLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '打开 原生日线策略' }))
  expect(await screen.findByText(/草稿修订 1 · 已完成 · RQAlpha 公开版 6.5.0/)).toBeVisible()
  fireEvent.click(screen.getByText('本次运行参数和源码摘要'))
  expect(screen.getByText(/引擎版本 6.5.0/)).toBeVisible()
  expect(screen.getByText(`行情 SHA-256 ${nativeJob.dataset_sha256}`)).toBeVisible()
  fireEvent.click(screen.getByText('成交明细（0）'))
  expect(screen.getByText('暂无成交。')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '历史回测' }))
  const history = screen.getByRole('region', { name: '历史回测' })
  expect(within(history).getByText('RQAlpha 公开版')).toBeVisible()
  fireEvent.click(within(history).getByRole('button', { name: /的多股回测/ }))
  await waitFor(() => expect(labMultiApi.job).toHaveBeenCalledTimes(2))
  expect(editor()).toHaveValue(nativeSource)
  expect(labMultiApi.start).not.toHaveBeenCalled()
  expect(labMultiApi.release).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '创建运行版本' })).toBeNull()
})

it('labels old records as Atlas and keeps unknown progress indeterminate', () => {
  const oldSettings = { ...nativeDraft.settings }
  delete oldSettings.engine_id
  const oldJob: LabMultiJob = { ...nativeJob, settings: oldSettings, engine_id: undefined,
    engine_version: undefined, matching_type: undefined, status: 'running', progress: null, result: null }
  render(<LabMultiBacktestResult job={oldJob} />)
  expect(screen.getByText(/草稿修订 1 · 运行中 · Atlas 自研引擎/)).toBeVisible()
  expect(screen.queryByText(/RQAlpha/)).toBeNull()
  expect(screen.getByRole('progressbar', { name: '多股回测进度' })).not.toHaveAttribute('value')
})

it('ignores an old static check response after switching engine', async () => {
  await openNative()
  let complete!: (value: { valid: boolean; error: null }) => void
  vi.mocked(request).mockImplementation(async path => path === '/lab-multi/check'
    ? new Promise(resolve => { complete = resolve }) : { configured: false })
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  const checking = vi.mocked(request).mock.calls.find(([path]) => path === '/lab-multi/check')!
  fireEvent.change(screen.getByLabelText('回测引擎'), { target: { value: 'atlas_portfolio' } })
  expect(checking[1]?.signal?.aborted).toBe(true)
  await act(async () => complete({ valid: true, error: null }))
  expect(screen.queryByText('语法与入口静态检查通过')).toBeNull()
  expect(screen.queryByText('语法检查通过')).toBeNull()
})

it('rejects a capabilities response identifying another engine', async () => {
  mockNativeSaved()
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ available: true, reason: null, engine_id: 'atlas_portfolio' })
  render(<StrategyLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '打开 原生日线策略' }))
  expect(await screen.findByText('执行环境返回的引擎不匹配，请重试。')).toBeVisible()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
})

it('submits native settings without running the single-stock or release endpoints', async () => {
  await openNative()
  vi.mocked(labMultiApi.preflight).mockResolvedValue({ available: true, reason: null,
    start: 1735801200, end: 1767178800, dataset_sha256: nativeJob.dataset_sha256 })
  vi.mocked(labMultiApi.start).mockResolvedValue({ ...nativeJob, status: 'queued', progress: null, result: null })
  await waitFor(() => expect(screen.getByRole('button', { name: '运行回测' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await waitFor(() => expect(labMultiApi.start).toHaveBeenCalledOnce())
  expect(labMultiApi.preflight).toHaveBeenCalledWith(props.ownerId, nativeDraft.settings, expect.any(AbortSignal))
  expect(labMultiApi.start).toHaveBeenCalledWith(props.ownerId, nativeSaved.id, 1, expect.any(String), expect.any(AbortSignal))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(labMultiApi.release).not.toHaveBeenCalled()
})

it('keeps ZIP strategy packages on the Atlas engine with switching disabled', async () => {
  vi.mocked(labMultiApi.inspect).mockResolvedValue({ name: '旧策略包', source: '# Atlas package' })
  const { container } = render(<StrategyLabWorkspace {...props} />)
  const file = new File(['zip bytes'], 'legacy.zip')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('zip bytes').buffer })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  expect(await screen.findByLabelText('回测引擎')).toHaveValue('atlas_portfolio')
  expect(screen.getByLabelText('回测引擎')).toBeDisabled()
  expect(editor()).toHaveValue('# Atlas package')
  expect(screen.queryByRole('region', { name: '导入策略类型' })).toBeNull()
})

it('downloads the same native history identity and metadata it displays', async () => {
  const createUrl = vi.fn().mockReturnValue('blob:backtest')
  const revokeUrl = vi.fn()
  const originalCreate = URL.createObjectURL
  const originalRevoke = URL.revokeObjectURL
  URL.createObjectURL = createUrl
  URL.revokeObjectURL = revokeUrl
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  try {
    render(<LabMultiBacktestResult job={nativeJob} />)
    fireEvent.click(screen.getByRole('button', { name: '下载回测快照' }))
    const blob = createUrl.mock.calls[0][0] as Blob
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = reject
      reader.readAsText(blob)
    })
    const snapshot = JSON.parse(text)
    expect(snapshot).toMatchObject({ id: nativeJob.id, engine_id: 'rqalpha', engine_version: '6.5.0', matching_type: 'current_bar',
      source_sha256: nativeJob.source_sha256, dataset_sha256: nativeJob.dataset_sha256 })
    expect(snapshot.result).toEqual(nativeJob.result)
    expect(labMultiApi.start).not.toHaveBeenCalled()
  } finally {
    URL.createObjectURL = originalCreate
    URL.revokeObjectURL = originalRevoke
    click.mockRestore()
  }
})
