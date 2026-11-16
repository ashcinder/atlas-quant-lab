import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { inspectPythonProject, prepareProjectPlan, runPythonProject } from '../compute/pythonProject'
import { comparisonMarket } from '../compute/client'
import { api } from '../api'
import { request } from '../request'
import type { BacktestResult, Bar } from '../types'
import type { LabBacktestSettings } from '../lab-strategy-types'
import PythonProjectWorkspace from './PythonProjectWorkspace'

vi.mock('../compute/pythonProject', () => ({
  inspectPythonProject: vi.fn(),
  runPythonProject: vi.fn(), prepareProjectPlan: vi.fn(),
}))

vi.mock('../compute/client', () => ({ comparisonMarket: vi.fn() }))
vi.mock('../api', () => ({ api: { backtestEngines: vi.fn(), runBacktest: vi.fn() } }))
vi.mock('../request', () => ({ request: vi.fn() }))
vi.mock('./ResultsPanel', () => ({ ResultsPanel: ({ result }: { result: BacktestResult }) => <p>{result.run_id}</p> }))

const settings: LabBacktestSettings = {
  symbol: '300750.SZ', asset_class: 'equity', interval: '1d', adjustment: 'raw', data_source: 'huggingface',
  start: null, end: null, initial_capital: 100000, commission_rate: .001, slippage_rate: 0, spread_rate: 0,
  max_position: .95, max_participation_rate: .05,
}

function renderProject(code: string) {
  const file = new File(['archive'], 'strategies.zip')
  const entry = 'main.py'
  render(<PythonProjectWorkspace draftToolbar={null} draftDirty={false} incomingArchive={null}
    initialProject={{ file, root: '', scripts: [entry], files: [{ path: entry, size: 1 }], sources: { [entry]: code } }}
    comparisonContext={{ ownerId: 'owner', assets: [], settings }}
    importDisabled={false} onOpenArchive={() => undefined}>{null}</PythonProjectWorkspace>)
  return { file, entry }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('keeps the configured entry when opening a helper and changes it only on request', async () => {
  const archive = new File(['archive'], 'strategies.zip')
  const strategy = 'research/main.py'
  const helper = 'research/helpers.py'
  vi.mocked(inspectPythonProject).mockResolvedValue({
    root: 'research',
    scripts: [helper, strategy],
    files: [helper, strategy].map(path => ({ path, size: 1 })),
    sources: { [helper]: '# helper', [strategy]: '# entry' },
  })
  vi.mocked(runPythonProject).mockResolvedValue({ log: '', summaries: [], warnings: [], archive: new Blob() })

  render(<PythonProjectWorkspace draftToolbar={null} draftFilename="draft.py" draftDirty={false}
    incomingArchive={{ file: archive }} importDisabled={false} onOpenArchive={() => undefined}>
    <div>策略草稿</div>
  </PythonProjectWorkspace>)

  const editor = await screen.findByRole('region', { name: 'Python 项目工作区' })
  const entry = within(editor).getByRole('combobox', { name: '运行入口' })
  expect(entry).toHaveValue(strategy)

  const explorer = screen.getByRole('complementary', { name: '文件资源管理器' })
  fireEvent.click(within(explorer).getByRole('button', { name: 'helpers.py' }))
  expect(within(editor).getByRole('textbox', { name: '项目 Python 源码' })).toHaveValue('# helper')
  expect(entry).toHaveValue(strategy)

  fireEvent.click(within(editor).getByRole('button', { name: '运行项目脚本' }))
  await waitFor(() => expect(runPythonProject).toHaveBeenCalledWith(archive, strategy, {}, expect.any(AbortSignal)))
  await waitFor(() => expect(within(editor).getByRole('button', { name: '设为入口' })).toBeEnabled())
  fireEvent.click(within(editor).getByRole('button', { name: '设为入口' }))
  expect(entry).toHaveValue(helper)
})

it('opens the shared code assistant for the editable file in a ZIP project', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true } :
    { explanation: '降低仓位', code: 'def target(context): return 0.1' })
  renderProject('def target(context): return 0.5')
  const editor = screen.getByRole('textbox', { name: '项目 Python 源码' })
  fireEvent.change(editor, { target: { value: 'def target(context): return 0.25' } })
  expect(editor).toHaveValue('def target(context): return 0.25')
  fireEvent.click(screen.getByRole('button', { name: 'AI 助手' }))
  expect(screen.getByRole('complementary', { name: 'AI 代码助手' })).toBeVisible()
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '降低仓位' } })
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  const apply = await screen.findByRole('button', { name: '应用到编辑器' })
  expect(editor).toHaveValue('def target(context): return 0.25')
  fireEvent.click(apply)
  expect(editor).toHaveValue('def target(context): return 0.1')
  fireEvent.click(screen.getByRole('button', { name: '撤销替换' }))
  expect(editor).toHaveValue('def target(context): return 0.25')
})

it('runs all three frameworks from the primary ZIP action with the same edited entry and switches reports', async () => {
  const code = 'def target(context): return 0.2'
  const edited = 'def target(context): return 0.35'
  const { file, entry } = renderProject(code)
  const bars: Bar[] = Array.from({ length: 40 }, (_, i) => ({
    time: 1735689600 + i * 86400, open: 100, high: 101, low: 99, close: 100, volume: 10_000,
  }))
  const plan = { dataset_id: 'dataset-id', source_sha256: 'fingerprint', name: 'strategies',
    start: bars[0].time, end: bars[39].time, targets: bars.map(() => 0.35) }
  vi.mocked(comparisonMarket).mockResolvedValue({ bars, datasetId: plan.dataset_id, source: 'fixture' })
  vi.mocked(prepareProjectPlan).mockResolvedValue({ source: '# project fingerprint', plan })
  vi.mocked(api.backtestEngines).mockResolvedValue([])
  vi.mocked(api.runBacktest).mockImplementation(async payload => ({
    run_id: 'report-' + String(payload.backtest_engine), trades: [], metrics: { total_return: .05, max_drawdown: -.01 },
  }) as unknown as BacktestResult)
  fireEvent.change(screen.getByRole('textbox', { name: '项目 Python 源码' }), { target: { value: edited } })

  fireEvent.click(screen.getByRole('button', { name: '运行三框架回测' }))
  await screen.findByText('3 / 3 完成')
  expect(prepareProjectPlan).toHaveBeenCalledWith(file, entry, { [entry]: edited }, bars, plan.dataset_id, expect.any(AbortSignal))
  expect(runPythonProject).not.toHaveBeenCalled()
  expect(vi.mocked(api.runBacktest).mock.calls.map(([payload]) => payload.backtest_engine)).toEqual(['atlas', 'vnpy', 'rqalpha'])
  expect(vi.mocked(api.runBacktest).mock.calls.every(([payload]) => payload.portable_plan === plan)).toBe(true)
  fireEvent.click(screen.getByRole('tab', { name: 'RQAlpha' }))
  expect(screen.getByRole('tabpanel')).toHaveTextContent('report-rqalpha')
})

it('displays the reason for all three engines when the ZIP only exposes a project script', async () => {
  renderProject("if __name__ == '__main__':\n    main()")
  fireEvent.click(screen.getByRole('button', { name: '运行三框架回测' }))
  expect(await screen.findByText('0 / 3 完成')).toBeVisible()
  expect(screen.getAllByRole('tab', { name: /已跳过/ })).toHaveLength(3)
  expect(screen.getByText(/需要入口提供 target/)).toBeVisible()
  expect(runPythonProject).not.toHaveBeenCalled()
  vi.mocked(runPythonProject).mockResolvedValue({ log: '', summaries: [], warnings: [], archive: new Blob() })
  fireEvent.click(screen.getAllByRole('button', { name: '运行项目脚本' }).at(-1)!)
  await waitFor(() => expect(runPythonProject).toHaveBeenCalledOnce())
})
