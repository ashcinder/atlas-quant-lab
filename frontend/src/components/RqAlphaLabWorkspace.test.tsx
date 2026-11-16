import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { comparisonMarket } from '../compute/client'
import { MarketPreparingError } from '../compute/market'
import { inspectPythonProject, type PythonProject } from '../compute/pythonProject'
import { listLabProjects, readLabProject, saveLabProject } from '../lab-project-library'
import { requestLabNavigation } from '../lab-navigation'
import { defaultMultiSettings, type LabBacktestSettings, type LabMinuteInterval, type LabMultiDraft, type LabMultiJob, type LabRunSummary, type LabStrategy } from '../lab-strategy-types'
import { labMultiApi, type LabIndustryCoverage } from '../lab-multi-api'
import { ApiError, request } from '../request'
import type { Asset, BacktestResult } from '../types'
import { LabMultiBacktestResult } from './LabMultiBacktest'
import { RqAlphaLabWorkspace } from './RqAlphaLabWorkspace'

vi.mock('../compute/pythonProject', () => ({ inspectPythonProject: vi.fn() }))
vi.mock('../compute/client', async original => ({ ...await original<typeof import('../compute/client')>(), comparisonMarket: vi.fn() }))
vi.mock('../lab-project-library', () => ({ listLabProjects: vi.fn(), readLabProject: vi.fn(), saveLabProject: vi.fn() }))

vi.mock('../api', () => ({ api: {
  listLabStrategies: vi.fn(), getLabStrategy: vi.fn(), createLabStrategy: vi.fn(), updateLabStrategy: vi.fn(),
  listLabRuns: vi.fn(), deleteLabRun: vi.fn(), runBacktest: vi.fn(), getRun: vi.fn(), searchAssets: vi.fn(),
} }))
vi.mock('../request', async original => ({ ...await original<typeof import('../request')>(), request: vi.fn().mockResolvedValue({ configured: false }) }))
vi.mock('../lab-multi-api', async original => {
  const module = await original<typeof import('../lab-multi-api')>()
  return { ...module, labMultiApi: { ...module.labMultiApi,
    capabilities: vi.fn(), industries: vi.fn(), jobs: vi.fn(), job: vi.fn(), preflight: vi.fn(),
    start: vi.fn(), release: vi.fn(), inspect: vi.fn(), fromRelease: vi.fn(),
  } }
})
vi.mock('./EquityChart', () => ({ EquityChart: () => <div>账户净值曲线</div> }))
vi.mock('./PublishRuntimeStrategy', () => ({ PublishRuntimeStrategy: () => null }))
vi.mock('./ResultsPanel', () => ({ ResultsPanel: ({ result }: { result: BacktestResult | null }) => <output>{result?.run_id}</output> }))

const singleSettings: LabBacktestSettings = {
  symbol: 'BTC-USD', asset_class: 'crypto', data_source: 'auto', interval: '1d', start: null, end: null, adjustment: 'auto',
  initial_capital: 100_000, commission_rate: .001, slippage_rate: .0005, spread_rate: .0005, max_position: .95, max_participation_rate: .01,
}
const source = 'def init(context):\n    context.ready = False\n\ndef handle_bar(context, bar_dict):\n    pass\n'
const nativeDraft: LabMultiDraft = { kind: 'multi_python', language: 'python', name: '原生策略', source,
  settings: { ...defaultMultiSettings, engine_id: 'rqalpha', symbols: ['600519.SS'] } }
const saved: LabStrategy = { ...nativeDraft, id: 'native-strategy', revision: 1, updated_at: '2026-11-10T00:00:00Z' }
const other: LabStrategy = { ...saved, id: 'other-native', name: '另一份原生策略', source: '# other native source' }
const legacy: LabStrategy = { id: 'legacy-single', name: '旧单股策略', source: 'def target_bps(index, close, sma):\n    return 5000', language: 'python', settings: singleSettings, revision: 2, updated_at: saved.updated_at }
const legacyMulti: LabStrategy = { ...saved, id: 'legacy-multi', name: '旧多股策略', source: 'class Strategy:\n    pass', settings: { ...nativeDraft.settings, engine_id: 'atlas_portfolio' as const } }
const assets: Asset[] = [
  { symbol: '600519.SS', name: '合成日线甲', asset_class: 'equity', exchange: 'SSE', currency: 'CNY', timezone: 'Asia/Shanghai', tags: [] },
  { symbol: '000001.SZ', name: '合成日线乙', asset_class: 'equity', exchange: 'SZSE', currency: 'CNY', timezone: 'Asia/Shanghai', tags: [] },
]
const missingMinutes = 'HF 分钟源已选定，但尚未配置通过审计的冻结快照。'
const industries: LabIndustryCoverage[] = [
  { id: 'semiconductor', name: '半导体', symbols: [{ symbol: '603986.SS', name: '合成半导体甲' }, { symbol: '600460.SS', name: '合成半导体乙' }], membership_sha256: 'd'.repeat(64), membership_note: '合成测试：ETF披露代理名单，不代表完整行业成分。', start: null, end: null, minute_intervals: [], reason: missingMinutes },
  { id: 'defense', name: '军工', symbols: [{ symbol: '600760.SS', name: '合成军工甲' }], membership_sha256: 'e'.repeat(64), start: null, end: null, minute_intervals: [], reason: missingMinutes },
  { id: 'space', name: '商业航天', symbols: [], membership_sha256: null, start: null, end: null, minute_intervals: [], reason: '商业航天名单尚未准备。' },
  { id: 'robotics', name: '机器人', symbols: [], membership_sha256: null, start: null, end: null, minute_intervals: [], reason: '机器人名单尚未准备。' },
]
const minutePeriods: LabMinuteInterval[] = ['1m', '5m', '15m', '30m', '60m']
const preparedIndustries: LabIndustryCoverage[] = industries.map(row => row.id === 'semiconductor' ? {
  ...row, as_of: '2025-01-02', start: '2025-01-02', end: '2026-08-06', reason: null,
  coverage_note: '合成测试：外边界不代表逐股连续覆盖；8月7日为部分日，之后未覆盖。',
  minute_intervals: minutePeriods,
  minute_source: { repo_id: 'neigezhu/china-a-share-1min-ohlcv', revision: 'f'.repeat(40), last_complete_day: '2026-08-06' },
  symbols: row.symbols.map(item => ({ ...item, minute_available: true, start: '2025-01-02', end: '2026-08-06', missing_sessions: 2 })),
} : row)
const straitIndustry: LabIndustryCoverage = {
  id: 'strait', name: '海峡两岸（研究池）', as_of: '2025-01-02',
  symbols: [
    { symbol: '000592.SZ', name: '平潭发展', minute_available: true, start: '2025-01-02', end: '2026-08-06', missing_sessions: 0 },
    { symbol: '603122.SS', name: '合富中国', minute_available: true, start: '2025-01-02', end: '2026-08-06', missing_sessions: 0 },
  ],
  membership_sha256: '5'.repeat(64), membership_scope: 'historical-theme-research-sample',
  membership_selected_on: '2026-11-15',
  membership_note: '合成研究池：本次整理的部分研究观察池，采用2025年前公开依据，不代表当时完整成分、关注度、无偏样本或龙头。',
  membership_evidence: {
    '000592.SZ': { name: '平潭发展', basis: 'historical-concept-news', source: 'https://example.test/historical-strait-concept', published: '2024-10-29' },
    '603122.SS': { name: '合富中国', basis: 'annual-report-business-proxy', source: 'https://example.test/annual-strait-business', published: '2023-03-22' },
  },
  start: '2025-01-02', end: '2026-08-06', minute_intervals: minutePeriods, reason: null,
  minute_source: { repo_id: 'neigezhu/china-a-share-1min-ohlcv', revision: '6'.repeat(40), last_complete_day: '2026-08-06' },
}
const props = { ownerId: 'owner-a', active: true, assets, defaults: singleSettings, onRunSaved: vi.fn() }
const nativeJob: LabMultiJob = { id: 'native-job', strategy_id: saved.id, revision: 1, status: 'succeeded', progress: 1, error: null,
  created_at: saved.updated_at, settings: nativeDraft.settings, source_sha256: 'b'.repeat(64), dataset_sha256: 'c'.repeat(64), engine_id: 'rqalpha', engine_version: '6.5.0', matching_type: 'current_bar',
  result: { initial_capital: 1_000_000, final_equity: 1_000_000, total_return: 0, max_drawdown: 0, equity: [{ time: 1735801200, equity: 1_000_000, cash: 1_000_000 }], trades: [] } }
const editor = () => screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement
const nativeCapabilities = { available: true, reason: null, engine_id: 'rqalpha' as const, engine_version: '6.5.0', can_release: false, minute_intervals: [], minute_reason: missingMinutes }

async function open(record: LabStrategy = saved) {
  render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: `打开 ${record.name}` }))
  await screen.findByLabelText('Python 策略代码')
}
async function create() {
  const { container } = render(<RqAlphaLabWorkspace {...props} />)
  await screen.findByRole('button', { name: `打开 ${saved.name}` })
  const native = 'from rqalpha.api import order_target_percent\n\ndef init(context):\n    context.symbols = []\n\ndef handle_bar(context, bar_dict):\n    pass\n'
  const file = new File([native], 'native.py')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode(native).buffer })
  fireEvent.change(container.querySelector('input[accept^=".py"]')!, { target: { files: [file] } })
  await screen.findByLabelText('Python 策略代码')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listLabProjects).mockReset().mockResolvedValue([])
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:isolated-source') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  vi.mocked(labMultiApi.capabilities).mockReset().mockResolvedValue(nativeCapabilities)
  vi.mocked(labMultiApi.industries).mockReset().mockResolvedValue(industries)
  vi.mocked(labMultiApi.jobs).mockReset().mockResolvedValue([])
  vi.mocked(labMultiApi.job).mockReset()
  vi.mocked(labMultiApi.preflight).mockReset()
  vi.mocked(labMultiApi.start).mockReset()
  vi.mocked(labMultiApi.release).mockReset()
  vi.mocked(labMultiApi.inspect).mockReset()
  vi.mocked(labMultiApi.fromRelease).mockReset()
  vi.mocked(request).mockReset().mockResolvedValue({ configured: false })
  vi.mocked(api.listLabStrategies).mockReset().mockResolvedValue([saved, other, legacy, legacyMulti])
  vi.mocked(api.getLabStrategy).mockReset().mockImplementation(async (_owner, id) => [saved, other, legacy, legacyMulti].find(row => row.id === id)!)
  vi.mocked(api.createLabStrategy).mockReset().mockImplementation(async (_owner, id, draft) => ({ ...draft, id, revision: 1, updated_at: saved.updated_at }))
  vi.mocked(api.updateLabStrategy).mockReset().mockImplementation(async (_owner, id, revision, draft) => ({ ...draft, id, revision: revision + 1, updated_at: saved.updated_at }))
  vi.mocked(api.listLabRuns).mockReset().mockResolvedValue([])
  vi.mocked(api.searchAssets).mockReset().mockResolvedValue([])
  vi.mocked(api.runBacktest).mockReset()
  vi.mocked(api.getRun).mockReset()
  vi.mocked(comparisonMarket).mockReset()
  window.history.replaceState(null, '', '/#research')
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('imports a native Python strategy without categories, engine or language selectors', async () => {
  await create()
  expect(screen.queryByRole('button', { name: '新建单标的策略' })).toBeNull()
  expect(screen.queryByRole('button', { name: '新建多标的策略' })).toBeNull()
  expect(screen.getByRole('heading', { name: '编辑策略' })).toBeVisible()
  expect(editor().value).toContain('def init(context):')
  expect(editor().value).toContain('context.symbols')
  expect(editor().value).not.toContain('generate_targets')
  expect(screen.queryByRole('region', { name: '新建策略类型' })).toBeNull()
  expect(screen.queryByLabelText('回测引擎')).toBeNull()
  expect(screen.queryByLabelText('策略编程语言')).toBeNull()
  expect(screen.queryByRole('button', { name: '单标的受限 Python' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'A 股多标的 Python' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'RQAlpha 原生日线 Python' })).toBeNull()
  expect(screen.getByLabelText('共享初始资金（元）')).toHaveValue(1_000_000)
  fireEvent.change(screen.getByLabelText('共享初始资金（元）'), { target: { value: '12345' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.updateLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), 1, expect.objectContaining({ kind: 'multi_python', language: 'python', settings: expect.objectContaining({ engine_id: 'rqalpha', initial_capital: 12345, interval: '1d', symbols: [] }) }))
})

it.each([
  { kind: 'multi_python', code: source },
  { kind: 'single', code: 'def init(context):\n    pass\n\ndef target(context):\n    return 0.5' },
])('saves a $kind Python file on import and adds it to the library', async ({ kind, code }) => {
  const { container } = render(<RqAlphaLabWorkspace {...props} />)
  await screen.findByRole('button', { name: `打开 ${saved.name}` })
  const file = new File([code], 'imported.py')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode(code).buffer })
  fireEvent.change(container.querySelector('input[accept^=".py"]')!, { target: { files: [file] } })
  expect(await screen.findByLabelText('Python 策略代码')).toHaveValue(code)
  expect(screen.queryByRole('region', { name: '导入策略类型' })).toBeNull()
  expect(screen.getByText('已保存')).toBeVisible()
  expect(editor().readOnly).toBe(false)
  const assistant = screen.getByRole('tab', { name: 'AI 助手' })
  fireEvent.click(assistant)
  expect(screen.getByRole('complementary', { name: 'AI 代码助手' })).toBeVisible()
  fireEvent.click(screen.getByRole('tab', { name: '回测设置' }))
  const expected = kind === 'multi_python' ? { source: code, kind } : { source: code, settings: singleSettings }
  expect(api.createLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), expect.objectContaining(expected))
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  expect(screen.getByRole('button', { name: '打开 imported' })).toBeVisible()
})

it('keeps the library during ZIP validation and adds a reopenable project after importing', async () => {
  const file = new File(['fixture'], 'portfolio.zip')
  const entry = { id: 'zip-project', name: file.name, updated_at: saved.updated_at }
  const inspected = { scripts: ['main.py'], sources: { 'main.py': 'print("ready")' }, files: [{ path: 'main.py', size: 14 }], root: '' }
  let finishInspection!: (project: PythonProject) => void
  vi.mocked(inspectPythonProject).mockImplementationOnce(() => new Promise(resolve => { finishInspection = resolve }))
    .mockResolvedValue(inspected)
  vi.mocked(saveLabProject).mockResolvedValue(entry)
  vi.mocked(readLabProject).mockResolvedValue(file)
  const { container } = render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.change(container.querySelector('input[accept=".zip"]')!, { target: { files: [file] } })
  const library = screen.getByRole('region', { name: '我的策略' })
  expect(within(library).getByRole('status')).toHaveTextContent('正在校验 ZIP 项目')
  expect(screen.queryByLabelText('Python 策略代码')).not.toBeInTheDocument()
  await waitFor(() => expect(inspectPythonProject).toHaveBeenCalled())
  await act(async () => finishInspection(inspected))
  expect(await screen.findByRole('combobox', { name: '运行入口' })).toHaveValue('main.py')
  expect(saveLabProject).toHaveBeenCalledWith(props.ownerId, file)
  fireEvent.click(screen.getByRole('button', { name: '返回策略库' }))
  fireEvent.click(screen.getByRole('button', { name: '打开 portfolio.zip' }))
  expect(await screen.findByRole('combobox', { name: '运行入口' })).toHaveValue('main.py')
  expect(readLabProject).toHaveBeenCalledWith(props.ownerId, entry)
  expect(saveLabProject).toHaveBeenCalledTimes(1)
})

it.each(['legacy.zip', 'legacy.qstrategy'])('rejects %s instead of creating another engine or language', async filename => {
  const { container } = render(<RqAlphaLabWorkspace {...props} />)
  const file = new File(['not a native Python file'], filename)
  fireEvent.change(container.querySelector('input[accept^=".py"]')!, { target: { files: [file] } })
  expect(await screen.findByRole('alert')).toHaveTextContent('不支持')
  expect(screen.queryByLabelText('Python 策略代码')).toBeNull()
  expect(labMultiApi.inspect).not.toHaveBeenCalled()
  expect(api.createLabStrategy).not.toHaveBeenCalled()
})

it('keeps native dirty navigation and revision conflict protection', async () => {
  vi.mocked(api.updateLabStrategy).mockRejectedValue(new ApiError('策略已在其他窗口更新。', 'http', 409))
  await open()
  fireEvent.change(editor(), { target: { value: '# keep this native source' } })
  const leave = vi.fn()
  act(() => requestLabNavigation(leave))
  const dialog = screen.getByRole('alertdialog')
  fireEvent.click(within(dialog).getByRole('button', { name: '保存并离开' }))
  await within(dialog).findByText('策略已在其他窗口更新。')
  expect(leave).not.toHaveBeenCalled()
  expect(editor()).toHaveValue('# keep this native source')
  fireEvent.click(within(dialog).getByRole('button', { name: '取消，保留当前内容' }))
  expect(screen.getByRole('button', { name: '重新加载已保存版本' })).toBeVisible()
  act(() => requestLabNavigation(leave))
  fireEvent.click(screen.getByRole('button', { name: '放弃修改' }))
  expect(leave).toHaveBeenCalledOnce()
})

it('reuses the original creation identifier after a lost response and keeps newer edits', async () => {
  vi.mocked(api.createLabStrategy).mockRejectedValueOnce(new ApiError('请求超时', 'timeout'))
    .mockImplementation(async (_owner, id, draft) => ({ ...draft, id, revision: 1, updated_at: saved.updated_at }))
  render(<RqAlphaLabWorkspace {...props} />)
  await screen.findByRole('button', { name: `打开 ${saved.name}` })
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  fireEvent.change(editor(), { target: { value: '# original submission' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('请求超时')
  fireEvent.change(editor(), { target: { value: '# newer native edit' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已恢复上次保存。请再保存一次，提交后续修改。')
  expect(vi.mocked(api.createLabStrategy).mock.calls[0]).toEqual(vi.mocked(api.createLabStrategy).mock.calls[1])
  expect(editor()).toHaveValue('# newer native edit')
})

it.each([legacyMulti])('keeps $name source and settings read-only without invoking legacy mutations', async record => {
  await open(record)
  expect(screen.getByRole('heading', { name: '查看历史策略' })).toBeVisible()
  expect(editor()).toHaveAttribute('readonly')
  expect(editor()).toHaveValue(record.source)
  expect(screen.getByLabelText('代码策略名称')).toHaveAttribute('readonly')
  expect(screen.getByRole('button', { name: '保存策略' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '检查代码' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '导入代码' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '下载源码' })).toBeEnabled()
  expect(screen.getByRole('tab', { name: '历史回测' })).toBeEnabled()
  fireEvent.change(editor(), { target: { value: '# attempted legacy replacement' } })
  fireEvent.keyDown(editor(), { key: 's', ctrlKey: true })
  expect(editor()).toHaveValue(record.source)
  expect(api.updateLabStrategy).not.toHaveBeenCalled()
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(labMultiApi.start).not.toHaveBeenCalled()
  expect(labMultiApi.release).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '创建运行版本' })).toBeNull()
})

it.each([legacyMulti])('downloads the unchanged source of $name', async record => {
  await open(record)
  fireEvent.click(screen.getByRole('button', { name: '下载源码' }))
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob
  const content = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = reject
    reader.readAsText(blob)
  })
  expect(content).toBe(record.source)
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
  expect(api.updateLabStrategy).not.toHaveBeenCalled()
})

it('opens a legacy result without replacing source or rerunning it', async () => {
  const historical = { id: 'historical-run', mode: 'single', strategy_id: 'python_bounded', symbol: 'BTC-USD', created_at: saved.updated_at, total_return: .12, max_drawdown: -.02, status: 'completed', source_sha256: 'a'.repeat(64), settings: { ...singleSettings, initial_capital: 9876 } } satisfies LabRunSummary
  vi.mocked(api.listLabRuns).mockResolvedValue([historical])
  vi.mocked(api.getRun).mockResolvedValue({ run_id: historical.id } as BacktestResult)
  await open(legacy)
  fireEvent.click(screen.getByRole('tab', { name: '历史回测' }))
  fireEvent.click(await screen.findByRole('button', { name: /查看 .* 的回测/ }))
  expect(await screen.findByText('historical-run')).toBeVisible()
  expect(editor()).toHaveValue(legacy.source)
  expect(api.runBacktest).not.toHaveBeenCalled()
})

it('does not turn a copied legacy release into an unsaved Trine draft', async () => {
  vi.mocked(labMultiApi.fromRelease).mockResolvedValue(legacyMulti)
  window.history.replaceState(null, '', '/#research?copy=old-release')
  render(<RqAlphaLabWorkspace {...props} />)
  expect(await screen.findByRole('heading', { name: '查看历史策略' })).toBeVisible()
  expect(editor()).toHaveValue(legacyMulti.source)
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.getByRole('heading', { name: '我的策略' })).toBeVisible()
  expect(api.createLabStrategy).not.toHaveBeenCalled()
})

it('checks only the fixed native protocol and invalidates the conclusion after editing source', async () => {
  await open()
  vi.mocked(request).mockImplementation(async path => path === '/lab-multi/check' ? { valid: true, error: null } : { configured: false })
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  expect(await screen.findByText('语法与入口静态检查通过')).toBeVisible()
  expect(request).toHaveBeenCalledWith('/lab-multi/check', expect.objectContaining({ body: JSON.stringify({ source, engine_id: 'rqalpha' }) }))
  fireEvent.change(editor(), { target: { value: source + '# changed' } })
  expect(screen.queryByText('语法与入口静态检查通过')).toBeNull()
})

it('ignores a static check response after leaving the checked native strategy', async () => {
  await open()
  let complete!: (value: { valid: boolean; error: null }) => void
  vi.mocked(request).mockImplementation(async path => path === '/lab-multi/check' ? new Promise(resolve => { complete = resolve }) : { configured: false })
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  const checking = vi.mocked(request).mock.calls.find(([path]) => path === '/lab-multi/check')!
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  fireEvent.click(screen.getByRole('button', { name: `打开 ${other.name}` }))
  await waitFor(() => expect(editor()).toHaveValue(other.source))
  expect(checking[1]?.signal?.aborted).toBe(true)
  await act(async () => complete({ valid: true, error: null }))
  expect(screen.queryByText('语法与入口静态检查通过')).toBeNull()
})

it('runs one selected daily stock through the native queue without legacy or release calls', async () => {
  vi.mocked(labMultiApi.preflight).mockResolvedValue({ available: true, reason: null, start: 1735801200, end: 1767178800 })
  vi.mocked(labMultiApi.start).mockResolvedValue({ ...nativeJob, status: 'queued', progress: null, result: null })
  await open()
  await waitFor(() => expect(screen.getByRole('button', { name: '运行回测' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '运行回测' }))
  await waitFor(() => expect(labMultiApi.start).toHaveBeenCalledOnce())
  expect(labMultiApi.preflight).toHaveBeenCalledWith(props.ownerId, nativeDraft.settings, expect.any(AbortSignal))
  expect(api.runBacktest).not.toHaveBeenCalled()
  expect(labMultiApi.release).not.toHaveBeenCalled()
})

it('reopens native history without executing and retains its saved identity', async () => {
  vi.mocked(labMultiApi.jobs).mockResolvedValue([nativeJob])
  vi.mocked(labMultiApi.job).mockResolvedValue(nativeJob)
  await open()
  fireEvent.click(screen.getByRole('tab', { name: '回测结果' }))
  expect(await screen.findByText(/草稿修订 1 · 已完成 · RQAlpha 公开版 6.5.0/)).toBeVisible()
  fireEvent.click(screen.getByText('本次运行参数和源码摘要'))
  expect(screen.getByText(`行情 SHA-256 ${nativeJob.dataset_sha256}`)).toBeVisible()
  fireEvent.click(screen.getByRole('tab', { name: '历史回测' }))
  const history = screen.getByRole('region', { name: '历史回测' })
  fireEvent.click(within(history).getByRole('button', { name: /的回测/ }))
  await waitFor(() => expect(labMultiApi.job).toHaveBeenCalledTimes(2))
  expect(editor()).toHaveValue(source)
  expect(labMultiApi.start).not.toHaveBeenCalled()
})

it('keeps historical minute provenance and daily-settlement sampling after editing the current draft', async () => {
  const historical: LabMultiJob = { ...nativeJob, settings: { ...nativeJob.settings, interval: '30m', industry: 'semiconductor' },
    result: { ...nativeJob.result!, interval: '30m', minute_digest: '1'.repeat(64), daily_digest: '2'.repeat(64), minute_adapter_version: 'atlas.rqalpha.minutes/v1',
      industry_snapshot: { industry: 'semiconductor', membership_sha256: '3'.repeat(64), as_of: '2025-01-02', published: '2024-10-25', effective: '2024-09-30', selection_mode: 'static-pool-with-dated-entry-eligibility' },
      minute_source: { repo_id: 'neigezhu/china-a-share-1min-ohlcv', revision: '4'.repeat(40), license_declared: 'apache-2.0', last_complete_day: '2026-08-06', timezone: 'Asia/Singapore', price_adjustment: 'none', volume_unit: 'shares', turnover_unit: 'CNY', start: '2025-01-02', end: '2026-08-06', bar_convention: 'end-label-session-local/v1', extra_session_policy: 'retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders', provenance_note: '合成来源说明：摘要不证明上游身份' },
    },
  }
  vi.mocked(labMultiApi.jobs).mockResolvedValue([historical])
  vi.mocked(labMultiApi.job).mockResolvedValue(historical)
  await open()
  expect(screen.getByRole('combobox', { name: /^行情周期/ })).toHaveValue('1d')
  fireEvent.change(screen.getByLabelText('共享初始资金（元）'), { target: { value: '7777' } })
  fireEvent.click(screen.getByRole('tab', { name: '回测结果' }))
  expect(await screen.findByText('30 分钟 · current_bar 收盘价撮合')).toBeVisible()
  expect(screen.getByText('执行行情：30 分钟；净值、持仓、账户与风险指标按原生日结采样，不按分钟根数年化。')).toBeVisible()
  fireEvent.click(screen.getByText('本次运行参数和源码摘要'))
  expect(screen.getByText('4'.repeat(40))).toBeVisible()
  expect(screen.getByText('1'.repeat(64))).toBeVisible()
  expect(screen.getByText('2'.repeat(64))).toBeVisible()
  expect(screen.getByText('3'.repeat(64))).toBeVisible()
  expect(screen.getByText(/只使用完整交易日，不填充缺根/)).toBeVisible()
  expect(labMultiApi.start).not.toHaveBeenCalled()
})

it('rejects capabilities identifying a different engine without offering a switch', async () => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ available: true, reason: null, engine_id: 'atlas_portfolio' })
  await open()
  expect(await screen.findByText('执行环境返回的引擎不匹配，请重试。')).toBeVisible()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(screen.queryByLabelText('回测引擎')).toBeNull()
})

it('offers exactly four industry pools and does not silently populate every member', async () => {
  await open()
  const industry = screen.getByRole('combobox', { name: /^行业股票池/ })
  expect(within(industry).getAllByRole('option').map(row => row.textContent)).toEqual(['不指定行业（日线）', '半导体', '军工', '商业航天', '机器人'])
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(industry, { target: { value: 'semiconductor' } })
  expect(screen.getByText(/已核验成员 2 只/)).toBeVisible()
  expect(screen.getByText(/ETF披露代理名单/)).toBeVisible()
  expect(screen.getByText(/成员版本 SHA-256/)).toHaveTextContent('d'.repeat(64))
  expect(screen.queryByRole('list', { name: '已选股票' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '加入行业股票池（2只）' }))
  expect(within(screen.getByRole('list', { name: '已选股票' })).getAllByRole('listitem')).toHaveLength(2)
  fireEvent.change(screen.getByLabelText('搜索或输入股票代码'), { target: { value: '600519.SS' } })
  expect(screen.getByRole('button', { name: '加入股票池' })).toBeDisabled()
  fireEvent.change(industry, { target: { value: 'defense' } })
  expect(screen.queryByRole('list', { name: '已选股票' })).toBeNull()
})

it('adds the configured strait research pool without replacing the original four choices', async () => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: minutePeriods, minute_reason: null })
  vi.mocked(labMultiApi.industries).mockResolvedValue([...preparedIndustries, straitIndustry])
  await create()
  const industry = screen.getByRole('combobox', { name: /^行业股票池/ })
  await within(industry).findByRole('option', { name: '海峡两岸（研究池）' })
  expect(within(industry).getAllByRole('option').map(row => row.textContent)).toEqual(['不指定行业（日线）', '半导体', '军工', '商业航天', '机器人', '海峡两岸（研究池）'])
  fireEvent.change(industry, { target: { value: 'strait' } })
  expect(screen.getByText(/研究样本 2 只/)).toBeVisible()
  expect(screen.getByText(straitIndustry.membership_note!)).toBeVisible()
  expect(within(screen.getByRole('combobox', { name: /^行情目录/ })).getByRole('option', { name: '000592.SZ · 平潭发展' })).toBeEnabled()
  const period = screen.getByRole('combobox', { name: /^行情周期/ })
  for (const minutes of [1, 5, 15, 30, 60]) expect(within(period).getByRole('option', { name: `${minutes} 分钟` })).toBeEnabled()
  fireEvent.click(screen.getByText('查看题材样本依据'))
  expect(screen.getByText(/本次样本整理日期：2026-11-15/)).toBeVisible()
  expect(screen.getByText(/历史概念报道 · 公开日期 2024-10-29/)).toBeVisible()
  expect(screen.getByText(/年报两岸业务代理 · 公开日期 2023-03-22/)).toBeVisible()
  expect(screen.getByText(/不等于福建区域股/)).toBeVisible()
  expect(screen.getByText('https://example.test/annual-strait-business').closest('a')).toBeNull()
  fireEvent.change(period, { target: { value: '5m' } })
  fireEvent.click(screen.getByRole('button', { name: '加入行业股票池（2只）' }))
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.updateLabStrategy).toHaveBeenCalledWith(props.ownerId, expect.any(String), 1, expect.objectContaining({
    settings: expect.objectContaining({ industry: 'strait', interval: '5m', symbols: ['000592.SZ', '603122.SS'] }),
  }))
  expect(screen.getByRole('button', { name: '运行回测' })).toBeEnabled()
})

it('does not expose an unconfigured strait pool while retaining the original four choices', async () => {
  await create()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  const industry = screen.getByRole('combobox', { name: /^行业股票池/ })
  expect(within(industry).queryByRole('option', { name: '海峡两岸（研究池）' })).toBeNull()
  expect(within(industry).getAllByRole('option')).toHaveLength(5)
  expect(screen.queryByText('查看题材样本依据')).toBeNull()
})

it.each(['runtime', 'pool'])('keeps strait minute periods gated when %s coverage is absent', async missing => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: missing === 'runtime' ? [] : minutePeriods })
  vi.mocked(labMultiApi.industries).mockResolvedValue([...preparedIndustries, { ...straitIndustry, minute_intervals: missing === 'pool' ? [] : minutePeriods }])
  await create()
  const industry = screen.getByRole('combobox', { name: /^行业股票池/ })
  await within(industry).findByRole('option', { name: '海峡两岸（研究池）' })
  fireEvent.change(industry, { target: { value: 'strait' } })
  const period = screen.getByRole('combobox', { name: /^行情周期/ })
  for (const minutes of [1, 5, 15, 30, 60]) expect(within(period).getByRole('option', { name: `${minutes} 分钟（数据未就绪）` })).toBeDisabled()
  expect(within(period).getByRole('option', { name: '日线' })).toBeEnabled()
})

it('shows the full-minute data gap and disables all five minute periods while daily remains available', async () => {
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'semiconductor' } })
  const period = screen.getByRole('combobox', { name: /^行情周期/ })
  expect(period).toBeEnabled()
  expect(within(period).getByRole('option', { name: '日线' })).toBeEnabled()
  for (const minutes of [1, 5, 15, 30, 60]) expect(within(period).getByRole('option', { name: `${minutes} 分钟（数据未就绪）` })).toBeDisabled()
  expect(screen.getAllByText(missingMinutes).length).toBeGreaterThan(0)
  expect(screen.getByText(/分钟覆盖：尚未核验完整历史覆盖/)).toBeVisible()
})

it('opens all five minute periods only with compatible runtime and industry coverage', async () => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: minutePeriods, minute_reason: null })
  vi.mocked(labMultiApi.industries).mockResolvedValue(preparedIndustries)
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'semiconductor' } })
  const period = screen.getByRole('combobox', { name: /^行情周期/ })
  for (const minutes of [1, 5, 15, 30, 60]) expect(within(period).getByRole('option', { name: `${minutes} 分钟` })).toBeEnabled()
  fireEvent.change(period, { target: { value: '60m' } })
  expect(screen.getByText(/开始时间不晚于09:30，结束时间不早于15:00/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '加入行业股票池（2只）' }))
  expect(screen.getByText(/名单时点 2025-01-02/)).toBeVisible()
  expect(screen.getByText(/完整日上限 2026-08-06/)).toBeVisible()
  expect(screen.getByText(`来源固定版本 ${'f'.repeat(40)}`)).toBeVisible()
  const coverage = screen.getByLabelText('已选股票分钟覆盖')
  expect(within(coverage).getAllByText(/缺口 2 日/)).toHaveLength(2)
  expect(within(coverage).getByText(/不会自动缩短区间或填充缺根/)).toBeVisible()
  fireEvent.change(screen.getByLabelText('结束时间（北京时间）'), { target: { value: '2026-11-13T15:00' } })
  expect(screen.getByLabelText('结束时间（北京时间）')).toHaveValue('2026-11-13T15:00')
})

it.each(['runtime', 'industry'])('keeps all minute periods locked when %s lacks support', async missing => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: missing === 'runtime' ? [] : minutePeriods })
  vi.mocked(labMultiApi.industries).mockResolvedValue(missing === 'industry' ? industries : preparedIndustries)
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'semiconductor' } })
  const period = screen.getByRole('combobox', { name: /^行情周期/ })
  for (const minutes of [1, 5, 15, 30, 60]) expect(within(period).getByRole('option', { name: `${minutes} 分钟（数据未就绪）` })).toBeDisabled()
  expect(within(period).getByRole('option', { name: '日线' })).toBeEnabled()
})

it('keeps unavailable minute members valid for daily but requires manual removal after changing to minutes', async () => {
  const record: LabStrategy = { ...saved, settings: { ...nativeDraft.settings, industry: 'semiconductor' as const, symbols: ['600460.SS'] } }
  vi.mocked(api.getLabStrategy).mockResolvedValue(record)
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: minutePeriods, minute_reason: null })
  vi.mocked(labMultiApi.industries).mockResolvedValue(preparedIndustries.map(row => row.id === 'semiconductor' ? {
    ...row, symbols: row.symbols.map(item => item.symbol === '600460.SS' ? { ...item, minute_available: false, start: null, end: null, minute_reason: '合成分钟文件未准备' } : item),
  } : row))
  await open()
  await waitFor(() => expect(screen.getByRole('button', { name: '运行回测' })).toBeEnabled())
  expect(screen.getByRole('button', { name: '检查行情覆盖' })).toBeEnabled()
  fireEvent.change(screen.getByRole('combobox', { name: /^行情周期/ }), { target: { value: '1m' } })
  expect(within(screen.getByRole('list', { name: '已选股票' })).getByText('600460.SS')).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent('分钟覆盖不匹配')
  expect(screen.getByRole('button', { name: '检查行情覆盖' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(labMultiApi.start).not.toHaveBeenCalled()
})

it('adds only minute-covered industry members while retaining daily choices', async () => {
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: minutePeriods, minute_reason: null })
  vi.mocked(labMultiApi.industries).mockResolvedValue(preparedIndustries.map(row => row.id === 'semiconductor' ? {
    ...row, symbols: row.symbols.map(item => ({ ...item, minute_available: item.symbol === '603986.SS' })),
  } : row))
  await create()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'semiconductor' } })
  expect(screen.getByRole('button', { name: '加入行业股票池（2只）' })).toBeEnabled()
  expect(within(screen.getByRole('combobox', { name: /^行情目录/ })).getByRole('option', { name: /600460.SS/ })).toBeEnabled()
  fireEvent.change(screen.getByRole('combobox', { name: /^行情周期/ }), { target: { value: '5m' } })
  expect(within(screen.getByRole('combobox', { name: /^行情目录/ })).queryByRole('option', { name: /600460.SS/ })).toBeNull()
  fireEvent.change(screen.getByLabelText('搜索或输入股票代码'), { target: { value: '600460.SS' } })
  expect(screen.getByRole('button', { name: '加入股票池' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '加入行业股票池（1只）' }))
  expect(within(screen.getByRole('list', { name: '已选股票' })).getAllByRole('listitem')).toHaveLength(1)
  expect(within(screen.getByRole('list', { name: '已选股票' })).getByText('603986.SS')).toBeVisible()
})

it('uses Beijing start dates and ignores superseded membership replies without removing selected stocks', async () => {
  const record: LabStrategy = { ...saved, settings: { ...nativeDraft.settings, industry: 'semiconductor' as const, symbols: ['603986.SS'], start: '2025-01-01T16:30:00Z' } }
  vi.mocked(api.getLabStrategy).mockResolvedValue(record)
  let staleRows!: (rows: LabIndustryCoverage[]) => void
  const laterRows = preparedIndustries.map(row => row.id === 'semiconductor' ? { ...row, as_of: '2025-03-03', symbols: [{ symbol: '600760.SS', name: '合成后续名单成员' }] } : row)
  vi.mocked(labMultiApi.industries).mockImplementation(async (_owner, _signal, asOf) => asOf === '2025-02-03' ? new Promise(resolve => { staleRows = resolve }) : asOf === '2025-03-03' ? laterRows : preparedIndustries)
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledWith('owner-a', expect.any(AbortSignal), '2025-01-02'))
  fireEvent.change(screen.getByLabelText('开始时间（北京时间）'), { target: { value: '2025-02-03T09:00' } })
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledTimes(2))
  const staleSignal = vi.mocked(labMultiApi.industries).mock.calls[1][1]
  fireEvent.change(screen.getByLabelText('开始时间（北京时间）'), { target: { value: '2025-02-03T10:30' } })
  expect(labMultiApi.industries).toHaveBeenCalledTimes(2)
  fireEvent.change(screen.getByLabelText('开始时间（北京时间）'), { target: { value: '2025-03-03T09:00' } })
  expect(staleSignal?.aborted).toBe(true)
  expect(await screen.findByText(/名单时点 2025-03-03/)).toBeVisible()
  await act(async () => staleRows(preparedIndustries))
  expect(screen.getByText(/名单时点 2025-03-03/)).toBeVisible()
  expect(screen.queryByText(/名单时点 2025-01-02/)).toBeNull()
  expect(within(screen.getByRole('list', { name: '已选股票' })).getByText('603986.SS')).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent('所选日期的行业')
})

it('reloads membership when reopening another native strategy with the same owner and date', async () => {
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledOnce())
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  fireEvent.click(screen.getByRole('button', { name: `打开 ${other.name}` }))
  await waitFor(() => expect(editor()).toHaveValue(other.source))
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledTimes(2))
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'semiconductor' } })
  expect(await screen.findByText(/已核验成员 2 只/)).toBeVisible()
  expect(screen.queryByText('正在读取行业股票池…')).toBeNull()
})

it('does not unlock an inherited minute setting when declared intervals lack verified dates', async () => {
  const inherited: LabStrategy = { ...saved, settings: { ...nativeDraft.settings, interval: '1m' as const, industry: 'semiconductor' as const, symbols: ['603986.SS'] } }
  vi.mocked(api.getLabStrategy).mockResolvedValue(inherited)
  vi.mocked(labMultiApi.capabilities).mockResolvedValue({ ...nativeCapabilities, minute_intervals: ['1m'] })
  vi.mocked(labMultiApi.industries).mockResolvedValue(industries.map(row => row.id === 'semiconductor' ? { ...row, minute_intervals: ['1m'] } : row))
  await open()
  expect(screen.getByRole('combobox', { name: /^行情周期/ })).toHaveValue('1m')
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  expect(screen.getByRole('option', { name: '1 分钟（数据未就绪）' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '检查行情覆盖' })).toBeDisabled()
  expect(labMultiApi.start).not.toHaveBeenCalled()
})

it('keeps unknown or empty industry membership unavailable without inventing fallback stocks', async () => {
  await open()
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalled())
  fireEvent.change(screen.getByRole('combobox', { name: /^行业股票池/ }), { target: { value: 'space' } })
  expect(screen.getByText(/该行业股票池尚未准备/)).toBeVisible()
  expect(screen.getByRole('button', { name: '加入行业股票池（0只）' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '检查行情覆盖' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled()
})

it('surfaces industry load errors and retries explicitly', async () => {
  vi.mocked(labMultiApi.industries).mockRejectedValueOnce(new Error('行业列表暂不可用')).mockResolvedValueOnce(industries)
  await open()
  expect(await screen.findByRole('alert')).toHaveTextContent('行业列表暂不可用')
  fireEvent.click(screen.getByRole('button', { name: '重试行业股票池' }))
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByText('行业列表暂不可用')).toBeNull())
})

it('aborts an old owner industry request and clears the editor on account change', async () => {
  let oldRows!: (rows: LabIndustryCoverage[]) => void
  vi.mocked(labMultiApi.industries).mockImplementationOnce(() => new Promise(resolve => { oldRows = resolve })).mockResolvedValue(industries)
  const view = render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: `打开 ${saved.name}` }))
  await waitFor(() => expect(labMultiApi.industries).toHaveBeenCalledOnce())
  const signal = vi.mocked(labMultiApi.industries).mock.calls[0][1]
  view.rerender(<RqAlphaLabWorkspace {...props} ownerId="owner-b" />)
  expect(signal?.aborted).toBe(true)
  await act(async () => oldRows(industries))
  expect(screen.queryByLabelText('Python 策略代码')).toBeNull()
  expect(screen.getByRole('heading', { name: '我的策略' })).toBeVisible()
})

it('ignores a previous native job response after leaving its strategy', async () => {
  let complete!: (value: LabMultiJob) => void
  vi.mocked(labMultiApi.jobs).mockResolvedValue([nativeJob])
  vi.mocked(labMultiApi.job).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
  await open()
  await waitFor(() => expect(labMultiApi.job).toHaveBeenCalledOnce())
  const signal = vi.mocked(labMultiApi.job).mock.calls[0][2]
  fireEvent.click(screen.getByRole('button', { name: '我的策略' }))
  fireEvent.click(screen.getByRole('button', { name: `打开 ${other.name}` }))
  await waitFor(() => expect(editor()).toHaveValue(other.source))
  expect(signal?.aborted).toBe(true)
  await act(async () => complete(nativeJob))
  expect(screen.queryByText(/草稿修订 1 · 已完成/)).toBeNull()
})

it('keeps old task identity and indeterminate progress without relabelling it', () => {
  const oldSettings = { ...nativeDraft.settings }
  delete oldSettings.engine_id
  render(<LabMultiBacktestResult job={{ ...nativeJob, settings: oldSettings, engine_id: undefined, status: 'running', result: null, progress: null }} />)
  expect(screen.getByText(/Trine 自研引擎/)).toBeVisible()
  expect(screen.queryByText(/RQAlpha/)).toBeNull()
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('value')
})

it('opens and saves existing single-asset strategies in the unified editor', async () => {
  await open(legacy)
  expect(editor()).not.toHaveAttribute('readonly')
  fireEvent.change(editor(), { target: { value: 'def target_bps(index, close, sma):\n    return 5000' } })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('已保存')
  expect(api.updateLabStrategy).toHaveBeenCalled()
})


it('creates a common Python strategy without a framework selector', async () => {
  render(<RqAlphaLabWorkspace {...props} />)
  await screen.findByRole('button', { name: '新建策略' })
  expect(screen.queryByRole('combobox', { name: '新策略框架' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '新建策略' }))
  expect((await screen.findByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toContain('def target(context)')
  expect(screen.getByRole('button', { name: '运行三框架回测' })).toBeEnabled()
  expect(screen.queryByRole('combobox', { name: '回测引擎' })).toBeNull()
})

it('saves a new strategy once and stores completed engines in the same comparison', async () => {
  const bars = Array.from({ length: 45 }, (_, i) => ({ time: 1700000000 + i * 86400, open: 100, high: 101, low: 99, close: 100, volume: 1000 }))
  vi.mocked(comparisonMarket).mockResolvedValue({ bars, datasetId: 'published-fixture', source: 'fixture' })
  vi.mocked(api.runBacktest).mockImplementation(async payload => ({
    run_id: String(payload.backtest_engine), metrics: { total_return: .1, max_drawdown: -.01 }, trades: [],
  }) as unknown as BacktestResult)
  render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '新建策略' }))
  fireEvent.change(await screen.findByLabelText('Python 策略代码'), { target: { value: 'def target_bps(index, close, sma):\n    return 2500' } })
  fireEvent.click(screen.getByRole('tab', { name: '回测结果' }))
  expect(screen.getByRole('heading', { name: '还没有回测结果' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '前往回测设置' }))
  expect(screen.getByRole('tab', { name: '回测设置', selected: true })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '运行三框架回测' }))
  expect(screen.getByRole('tab', { name: '回测结果', selected: true })).toBeVisible()
  expect(await screen.findByText('2 / 3 完成')).toBeVisible()
  expect(await screen.findByText(/已将完成的报告保存到/)).toBeVisible()
  expect(screen.getByRole('tab', { name: /RQAlpha.*已跳过/ })).toBeVisible()
  expect(api.runBacktest).toHaveBeenCalledTimes(2)
  const first = vi.mocked(api.runBacktest).mock.calls[0][0]
  expect(first.lab_comparison_id).toMatch(/^[a-f0-9]{32}$/)
  const id = vi.mocked(api.createLabStrategy).mock.calls[0][1]
  for (const [payload] of vi.mocked(api.runBacktest).mock.calls) {
    expect(payload).toMatchObject({ persist: true, lab_strategy_id: id, lab_comparison_id: first.lab_comparison_id,
      python_source: 'def target_bps(index, close, sma):\n    return 2500' })
  }
  expect(api.createLabStrategy).toHaveBeenCalledOnce()
  expect(api.listLabRuns).not.toHaveBeenCalled()
})

it('lists matching assets as selectable search results and explains invalid parameters', async () => {
  vi.mocked(api.searchAssets).mockResolvedValue([{ symbol: '002747.SZ', name: '埃斯顿', asset_class: 'equity', currency: 'CNY' } as Asset])
  render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '新建策略' }))
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索标的' }), { target: { value: '002747' } })
  fireEvent.click(await screen.findByRole('button', { name: '002747.SZ 埃斯顿' }))
  expect(screen.getByRole('combobox', { name: '回测标的' })).toHaveValue(JSON.stringify(['002747.SZ', 'equity']))
  fireEvent.change(screen.getByRole('spinbutton', { name: '初始资金' }), { target: { value: '0' } })
  expect(screen.getByRole('button', { name: '运行三框架回测' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '运行三框架回测' })).toHaveAccessibleDescription('初始资金必须大于零。')
})

it('explains missing shared market data once and lets the user adjust settings without changing their strategy', async () => {
  vi.mocked(comparisonMarket).mockRejectedValue(new MarketPreparingError('所选周期的行情尚未发布'))
  render(<RqAlphaLabWorkspace {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '新建策略' }))
  const source = (await screen.findByLabelText<HTMLTextAreaElement>('Python 策略代码')).value
  fireEvent.click(screen.getByRole('button', { name: '运行三框架回测' }))

  const notice = await screen.findByRole('alert')
  expect(notice).toHaveTextContent('所选周期的行情尚未发布')
  expect(screen.queryByRole('region', { name: '三框架回测结果' })).not.toBeInTheDocument()
  expect(api.runBacktest).not.toHaveBeenCalled()

  fireEvent.click(within(notice).getByRole('button', { name: '调整回测设置' }))
  expect(screen.getByRole('tab', { name: '回测设置', selected: true })).toBeVisible()
  expect(screen.getByLabelText('Python 策略代码')).toHaveValue(source)
})
