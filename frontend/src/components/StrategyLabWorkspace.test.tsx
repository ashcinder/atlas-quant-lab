import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import type { Asset, StrategyProject } from '../types'
import { StrategyLabWorkspace } from './StrategyLabWorkspace'

vi.mock('../api', () => ({ api: { listStrategyProjects: vi.fn(), updateStrategyProject: vi.fn(), searchAssets: vi.fn() } }))
vi.mock('./CodeStrategyWorkspace', () => ({ CodeStrategyWorkspace: () => <textarea aria-label="代码编辑器" defaultValue="def target_bps(): pass" /> }))
vi.mock('./TemplateStrategyWorkspace', () => ({ TemplateStrategyWorkspace: () => { throw new Error('模板不应加载') } }))
vi.mock('./ExecutionPipelinePanel', () => ({ ExecutionPipelinePanel: () => null }))
vi.mock('./QuantStrategyStudio', () => ({ QuantStrategyStudio: () => null }))
const aapl: Asset = { symbol: 'AAPL', name: 'Apple', asset_class: 'equity', exchange: 'NASDAQ', currency: 'USD', timezone: 'UTC', tags: [] }
const btc: Asset = { ...aapl, symbol: 'BTC-USD', name: '比特币', asset_class: 'crypto', exchange: 'CRYPTO' }
const project = { id: 'a', name: 'AAPL 研究', thesis: '趋势信号在交易成本后应当保持稳定的样本外风险调整收益。', asset_symbol: 'AAPL', asset_class: 'equity', interval: '1d', benchmark: 'SPY', objective: 'sharpe', stage: 'draft', revision: 1, gates: [], completion: 0 } as unknown as StrategyProject
const other = { ...project, id: 'b', name: 'BTC研究', asset_symbol: 'BTC-USD', asset_class: 'crypto', interval: '4h' as const }
const props = { asset: aapl, assets: [aapl, btc], interval: '1d' as const, strategies: [], source: 'auto' as const, initialCapital: 10000, commission: 0.001, slippage: 0, spread: 0, maxPosition: 1, maxParticipation: 0.1, onLoading: vi.fn(), onError: vi.fn(), onCustomResult: vi.fn(), initialTab: 'overview' as const }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.listStrategyProjects).mockResolvedValue([project, other]); vi.mocked(api.searchAssets).mockResolvedValue([aapl, btc]) })
afterEach(cleanup)

it('synchronizes the actual research context after editing the project asset and interval', async () => {
  const onContext = vi.fn()
  vi.mocked(api.updateStrategyProject).mockImplementation(async (_id, _revision, payload) => ({ ...project, ...payload, revision: 2 }))
  render(<StrategyLabWorkspace {...props} onResearchContextChange={onContext} />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑项目定义' }))
  fireEvent.change(screen.getByLabelText('研究标的'), { target: { value: 'BTC-USD' } })
  fireEvent.change(screen.getByLabelText('研究周期'), { target: { value: '1h' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并递增修订' }))
  await waitFor(() => expect(onContext).toHaveBeenCalledWith(btc, '1h'))
  expect(api.updateStrategyProject).toHaveBeenCalledWith('a', 1, expect.objectContaining({ asset_symbol: 'BTC-USD', asset_class: 'crypto', interval: '1h' }))
})

it('does not restore an old project context when its save completes after selecting another project', async () => {
  let finish!: (value: StrategyProject) => void
  vi.mocked(api.updateStrategyProject).mockReturnValue(new Promise(resolve => { finish = resolve }))
  const onContext = vi.fn()
  render(<StrategyLabWorkspace {...props} onResearchContextChange={onContext} />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑项目定义' }))
  fireEvent.click(screen.getByRole('button', { name: '保存并递增修订' }))
  fireEvent.change(screen.getByLabelText('选择策略项目'), { target: { value: 'b' } })
  expect(onContext).toHaveBeenLastCalledWith(btc, '4h')
  await act(async () => { finish({ ...project, revision: 2 }) })
  expect(onContext).toHaveBeenCalledTimes(1)
  expect((screen.getByLabelText('选择策略项目') as HTMLSelectElement).value).toBe('b')
})


it('opens code immediately and removes template, visual, workflow and gate navigation', async () => {
  render(<StrategyLabWorkspace {...props} />)
  expect(await screen.findByRole('textbox', {name: '代码编辑器'})).toBeTruthy()
  expect(screen.queryByRole('button', {name: /模板|图形化/})).toBeNull()
  expect(screen.queryByRole('navigation', {name: '策略生命周期'})).toBeNull()
  expect(screen.queryByRole('button', {name: /门禁/})).toBeNull()
})

it('does not silently associate a different-market project with the current backtest',async()=>{
 const onContext=vi.fn()
 render(<StrategyLabWorkspace {...props} interval="1h" onResearchContextChange={onContext}/>)
 const selector=await screen.findByLabelText('选择策略项目') as HTMLSelectElement
 await waitFor(()=>expect(selector.options).toHaveLength(3))
 expect(selector.value).toBe('')
 expect(onContext).not.toHaveBeenCalled()
 fireEvent.change(selector,{target:{value:'b'}})
 expect(onContext).toHaveBeenCalledWith(btc,'4h')
})
