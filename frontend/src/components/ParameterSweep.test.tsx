// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ParameterSweep } from './ParameterSweep'
import { api } from '../api'
import type { BacktestResult } from '../types'
const result = (value:number) => ({ bars: [], metrics: { total_return: value } }) as unknown as BacktestResult
vi.mock('../api', () => ({ api: { runBacktest: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('ranks returns, applies the winner and rejects application to an edited draft', async () => {
  vi.mocked(api.runBacktest).mockResolvedValueOnce(result(-.1)).mockResolvedValueOnce(result(.2))
  const onApply = vi.fn(), fields = [{ key: 'params.fast', label: '快线', value: 2, integer: true }]
  const { rerender } = render(<ParameterSweep fields={fields} payload={{ params: { fast: 2 } }} onApply={onApply} />)
  fireEvent.click(screen.getByText('比较参数'))
  HTMLDialogElement.prototype.showModal = function() { this.setAttribute('open','') }; HTMLDialogElement.prototype.close = function() { this.removeAttribute('open') }
  fireEvent.click(screen.getByRole('button', { name: /比较时间区间/ }))
  const dates = [screen.getByLabelText('比较开始时间'), screen.getByLabelText('比较结束时间')]
  fireEvent.change(dates[0], { target: { value: '2024-01-01T00:00' } }); fireEvent.change(dates[1], { target: { value: '2025-01-01T00:00' } })
  fireEvent.click(screen.getByText('确认区间'))
  fireEvent.click(screen.getByRole('checkbox')); fireEvent.change(screen.getByLabelText('快线 最大值'), { target: { value: '3' } })
  fireEvent.click(screen.getByText('开始比较'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('成功 2'))
  fireEvent.click(screen.getAllByText('使用这组')[0]); expect(onApply).toHaveBeenCalledWith({ 'params.fast': 3 })
  const body = vi.mocked(api.runBacktest).mock.calls[0][0]
  expect(body.persist).toBe(false); expect(body.start).toMatch(/Z$/)
  rerender(<ParameterSweep fields={fields} payload={{ params: { fast: 5 } }} onApply={onApply} />)
  expect((screen.getAllByText('使用这组')[0] as HTMLButtonElement).disabled).toBe(true)
})
it('displays percentage ranges but submits and applies raw position values with readable results', async () => {
  vi.mocked(api.runBacktest).mockResolvedValue(result(.1))
  const fields = [{ key: 'custom_strategy.target_position', label: '持仓比例', value: .5, min: 0, max: 1, scale: 100, unit: '%' }]
  const onApply = vi.fn()
  const { container } = render(<ParameterSweep fields={fields} payload={{ custom_strategy: { target_position: .5 } }} onApply={onApply} />)
  fireEvent.click(screen.getByText('比较参数'))
  const maximum = screen.getByLabelText('持仓比例 最大值') as HTMLInputElement
  expect(maximum.disabled).toBe(true)
  expect(maximum.value).toBe('50')
  expect(screen.getByText('50%')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: '持仓比例（%）' }))
  fireEvent.change(maximum, { target: { value: '75' } })
  fireEvent.change(screen.getByLabelText('持仓比例 每次增加'), { target: { value: '25' } })
  expect(screen.getByText('将比较：50%、75%')).toBeTruthy()
  expect(screen.getByText('将比较 2 组')).toBeTruthy()
  fireEvent.click(screen.getByText('开始比较'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('成功 2'))
  expect(vi.mocked(api.runBacktest).mock.calls.map(call => (call[0].custom_strategy as {target_position:number}).target_position)).toEqual([.5, .75])
  expect(screen.getByText('持仓比例：75%')).toBeTruthy()
  expect(container.textContent).not.toContain('custom_strategy')
  fireEvent.click(screen.getAllByText('使用这组')[1])
  expect(onApply).toHaveBeenCalledWith({ 'custom_strategy.target_position': .75 })
})
it('describes a failed combination without exposing internal parameter paths', async () => {
  vi.mocked(api.runBacktest).mockRejectedValueOnce(new Error('行情暂不可用'))
  const { container } = render(<ParameterSweep fields={[{ key: 'custom_strategy.entry.period', label: '买入均线长度', value: 20, unit: '根K线' }]} payload={{ custom_strategy: { entry: { period: 20 } } }} onApply={vi.fn()} />)
  fireEvent.click(screen.getByText('比较参数'))
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByText('开始比较'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('失败 1'))
  fireEvent.click(screen.getByText('未完成的回测（1）'))
  expect(screen.getByText('买入均线长度：20根K线：行情暂不可用')).toBeTruthy()
  expect(container.textContent).not.toContain('custom_strategy')
})
