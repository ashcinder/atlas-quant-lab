import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StrategyProjectBar } from './StrategyProjectBar'
import { api } from '../api'
import type { StrategyProject } from '../types'

vi.mock('../api', () => ({ api: { searchAssets: vi.fn() } }))

const asset = {
  symbol: 'BTC-USD', name: '比特币', asset_class: 'crypto', exchange: 'CRYPTO',
  currency: 'USD', timezone: 'UTC', tags: ['crypto'],
}
const stock = { ...asset, symbol: '600519.SS', name: '贵州茅台', asset_class: 'equity', currency: 'CNY' }
const project = { id: 'project', name: 'BTC 策略项目', thesis: '趋势信号在真实成本后应当保持稳定的样本外收益表现。', asset_symbol: 'BTC-USD', asset_class: 'crypto', interval: '1d', benchmark: 'BTC-USD', objective: 'sharpe', stage: 'draft', revision: 1, gates: [], completion: 0 } as unknown as StrategyProject
beforeEach(() => { vi.mocked(api.searchAssets).mockResolvedValue([asset, stock]) })
afterEach(cleanup)

describe('StrategyProjectBar', () => {
  it('asks before discarding an edited project and preserves it when cancelled', () => {
    render(<StrategyProjectBar projects={[project]} project={project} asset={asset} interval="1d" busy={false} onSelect={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} onFreeze={vi.fn()} onGoTab={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '编辑项目定义' }))
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: 'Unstored project title' } })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByRole('alertdialog').textContent).toContain('未保存')
    fireEvent.click(screen.getByRole('button', { name: '取消，保留当前内容' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect((screen.getByLabelText('项目名称') as HTMLInputElement).value).toBe('Unstored project title')
    fireEvent.click(screen.getByRole('button', { name: '关闭项目编辑器' }))
    fireEvent.click(screen.getByRole('button', { name: '放弃修改并关闭' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('creates a project from an explicit, falsifiable thesis', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined)
    render(<StrategyProjectBar
      projects={[]}
      project={null}
      asset={asset}
      interval="1d"
      busy={false}
      onSelect={vi.fn()}
      onCreate={onCreate}
      onUpdate={vi.fn()}
      onFreeze={vi.fn()}
      onGoTab={vi.fn()}
    />)

    fireEvent.click(screen.getAllByRole('button', { name: '创建策略项目' }).at(-1)!)
    expect(screen.getByDisplayValue('BTC-USD 策略研究')).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: /可证伪的投资假设/ }), {
      target: { value: 'BTC 趋势信号在真实交易成本后仍应保留正的样本外 Sharpe。' },
    })
    fireEvent.click(screen.getAllByRole('button', { name: '创建策略项目' }).at(-1)!)

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      asset_symbol: 'BTC-USD', interval: '1d', objective: 'sharpe',
    })))
  })

  it('keeps an invalid project definition in the editor with an actionable error', () => {
    render(<StrategyProjectBar
      projects={[]}
      project={null}
      asset={asset}
      interval="1d"
      busy={false}
      onSelect={vi.fn()}
      onCreate={vi.fn()}
      onUpdate={vi.fn()}
      onFreeze={vi.fn()}
      onGoTab={vi.fn()}
    />)

    fireEvent.click(screen.getAllByRole('button', { name: '创建策略项目' }).at(-1)!)
    fireEvent.change(screen.getByRole('textbox', { name: /可证伪的投资假设/ }), {
      target: { value: '太短' },
    })
    fireEvent.click(screen.getAllByRole('button', { name: '创建策略项目' }).at(-1)!)

    expect(screen.getByRole('alert').textContent).toContain('至少需要 12 个字符')
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('edits every project definition field and sends the selected asset class and interval', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    render(<StrategyProjectBar projects={[project]} project={project} asset={asset} assets={[asset, stock]} interval="15m" busy={false} onSelect={vi.fn()} onCreate={vi.fn()} onUpdate={onUpdate} onFreeze={vi.fn()} onGoTab={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '编辑项目定义' }))
    expect((screen.getByLabelText('研究周期') as HTMLSelectElement).value).toBe('1d')
    fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '茅台小时线研究' } })
    fireEvent.change(screen.getByLabelText(/可证伪的投资假设/), { target: { value: '新的趋势信号在真实交易成本后应保持稳定的样本外收益。' } })
    fireEvent.change(screen.getByLabelText('研究标的'), { target: { value: '600519.SS' } })
    fireEvent.change(screen.getByLabelText('研究周期'), { target: { value: '1h' } })
    fireEvent.change(screen.getByLabelText('基准'), { target: { value: ' 000001.ss ' } })
    fireEvent.change(screen.getByLabelText('主目标'), { target: { value: 'calmar' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并递增修订' }))
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({ name: '茅台小时线研究', thesis: '新的趋势信号在真实交易成本后应保持稳定的样本外收益。', asset_symbol: '600519.SS', asset_class: 'equity', interval: '1h', benchmark: '000001.SS', objective: 'calmar' }))
  })

  it('creates a project for a searched asset even when the global asset is not set', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined)
    render(<StrategyProjectBar projects={[]} project={null} asset={null} assets={[stock]} interval="1d" busy={false} onSelect={vi.fn()} onCreate={onCreate} onUpdate={vi.fn()} onFreeze={vi.fn()} onGoTab={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '新建策略项目' }))
    fireEvent.change(screen.getByLabelText('研究标的'), { target: { value: '贵州茅台' } })
    fireEvent.change(screen.getByLabelText('研究周期'), { target: { value: '1wk' } })
    fireEvent.click(screen.getAllByRole('button', { name: '创建策略项目' }).at(-1)!)
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ asset_symbol: '600519.SS', asset_class: 'equity', interval: '1wk' })))
  })
})
