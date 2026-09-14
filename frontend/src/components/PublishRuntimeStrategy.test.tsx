import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PublishRuntimeStrategy } from './PublishRuntimeStrategy'
import { TemplateStrategyWorkspace } from './TemplateStrategyWorkspace'
import { defaultPipeline } from './ExecutionPipelinePanel'
import type { ResearchWorkspaceProps } from './ResearchWorkspace'

const request = vi.hoisted(() => vi.fn())
vi.mock('../request', () => ({ request }))
vi.mock('../api', () => ({ api: { runBacktest: vi.fn() } }))
afterEach(cleanup)
beforeEach(() => {
  request.mockReset()
  request.mockImplementation(async (path: string) => path === '/strategy-releases'
    ? { id: 'rel_one', version: 1 } : { id: 'sub_one' })
})

it('publishes the edited template parameters instead of catalog defaults', async () => {
  const props = { strategies: [{ id: 'sma_cross', name: '均线', category: '趋势', parameters: [
    { key: 'fast', label: '快速周期', kind: 'integer', default: 20, minimum: 2, maximum: 100 },
  ] }], onLoading: vi.fn(), onError: vi.fn(), onCustomResult: vi.fn() } as unknown as ResearchWorkspaceProps
  render(<TemplateStrategyWorkspace {...props} pipeline={defaultPipeline()} storageKey="test-template-publish" />)
  fireEvent.change(screen.getByLabelText('快速周期'), { target: { value: '7' } })
  fireEvent.click(screen.getByText('保存并订阅运行版本'))
  await screen.findByText('已订阅 v1 · 配置并运行')
  const body = JSON.parse(request.mock.calls[0][1].body)
  expect(body.params).toEqual({ fast: 7 })
  expect(body.published).toBe(false)
  expect(request.mock.calls[1][0]).toBe('/strategy-subscriptions')
})

it('does not duplicate a release when subscription failed and the user retries', async () => {
  request.mockReset()
  request.mockResolvedValueOnce({ id: 'rel_one', version: 1 })
    .mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ id: 'sub_one' })
  render(<PublishRuntimeStrategy draft={{ name: '测试', source_kind: 'builtin', strategy_id: 'sma_cross', params: { fast: 7 } }} />)
  fireEvent.click(screen.getByText('保存并订阅运行版本'))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByText('保存并订阅运行版本'))
  await screen.findByText('已订阅 v1 · 配置并运行')
  expect(request.mock.calls.filter(([path]) => path === '/strategy-releases')).toHaveLength(1)
})

it('does not label edited code as the version already subscribed', async () => {
  const draft = { name: 'Python', source_kind: 'python' as const, strategy_id: 'python_bounded', python_source: 'return 1000' }
  const view = render(<PublishRuntimeStrategy draft={draft} />)
  fireEvent.click(screen.getByText('保存并订阅运行版本'))
  await screen.findByText('已订阅 v1 · 配置并运行')
  view.rerender(<PublishRuntimeStrategy draft={{ ...draft, python_source: 'return 2000' }} />)
  await waitFor(() => expect(screen.queryByText('已订阅 v1 · 配置并运行')).toBeNull())
  expect(screen.getByText('保存并订阅运行版本')).toBeTruthy()
})
