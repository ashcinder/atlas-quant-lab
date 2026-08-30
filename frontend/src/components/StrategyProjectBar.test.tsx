import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StrategyProjectBar } from './StrategyProjectBar'

const asset = {
  symbol: 'BTC-USD', name: '比特币', asset_class: 'crypto', exchange: 'CRYPTO',
  currency: 'USD', timezone: 'UTC', tags: ['crypto'],
}

describe('StrategyProjectBar', () => {
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

    fireEvent.click(screen.getAllByRole('button', { name: '创建项目' }).at(-1)!)
    expect(screen.getByDisplayValue('BTC-USD 策略研究')).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: /可证伪的投资假设/ }), {
      target: { value: 'BTC 趋势信号在真实交易成本后仍应保留正的样本外 Sharpe。' },
    })
    fireEvent.click(screen.getAllByRole('button', { name: '创建项目' }).at(-1)!)

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      asset_symbol: 'BTC-USD', interval: '1d', objective: 'sharpe',
    })))
  })
})
