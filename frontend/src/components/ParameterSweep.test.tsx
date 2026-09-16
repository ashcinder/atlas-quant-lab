// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ParameterSweep } from './ParameterSweep'
import { request } from '../request'
vi.mock('../request', () => ({ request: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('ranks returns, applies the winner and rejects application to an edited draft', async () => {
  vi.mocked(request).mockResolvedValueOnce({ bars: [], metrics: { total_return: -.1 } }).mockResolvedValueOnce({ bars: [], metrics: { total_return: .2 } })
  const onApply = vi.fn(), fields = [{ key: 'params.fast', label: '快线', value: 2, integer: true }]
  const { container, rerender } = render(<ParameterSweep fields={fields} payload={{ params: { fast: 2 } }} onApply={onApply} />)
  fireEvent.click(screen.getByText('参数穷举 · 寻找历史收益最高组合'))
  const dates = container.querySelectorAll('input[type=datetime-local]')
  fireEvent.change(dates[0], { target: { value: '2024-01-01T00:00' } }); fireEvent.change(dates[1], { target: { value: '2025-01-01T00:00' } })
  fireEvent.click(screen.getByRole('checkbox')); fireEvent.change(screen.getByLabelText('快线 to'), { target: { value: '3' } })
  fireEvent.click(screen.getByText('开始参数穷举'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('成功 2'))
  fireEvent.click(screen.getAllByText('应用参数')[0]); expect(onApply).toHaveBeenCalledWith({ 'params.fast': 3 })
  const body = JSON.parse(vi.mocked(request).mock.calls[0][1]!.body as string)
  expect(body.persist).toBe(false); expect(body.start).toMatch(/Z$/)
  rerender(<ParameterSweep fields={fields} payload={{ params: { fast: 5 } }} onApply={onApply} />)
  expect((screen.getAllByText('应用参数')[0] as HTMLButtonElement).disabled).toBe(true)
})
