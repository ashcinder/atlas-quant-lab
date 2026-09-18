import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import StrategyRuntimeLibrary from './StrategyRuntimeLibrary'

vi.mock('../request', async (importOriginal) => ({ ...await importOriginal<object>(), request: vi.fn() }))
const release = { id: 'rel-1', name: '趋势规则', version: 1, source_kind: 'builtin', strategy_id: 'momentum', markets: ['US'], description: '趋势跟随', content_hash: 'a'.repeat(64), params: {}, custom_strategy: null, owned: false, published: true, created_at: '2026-01-01' }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/bkc-offer')) return null
    if (path === '/strategy-releases') return [release]
    if (path === '/strategy-subscriptions') return []
    if (path.startsWith('/strategies')) return []
    if (path === '/custom-strategies') return []
    return {}
  })
})
afterEach(cleanup)

it('does not grant a free subscription when the author has not set a BKC price', async () => {
  render(<StrategyRuntimeLibrary />)
  await screen.findByRole('heading', { name: '趋势规则' })
  await screen.findByText('作者尚未设置 BKC 价格')
  expect(screen.queryByRole('button', { name: '免费订阅' })).toBeNull()
  expect(vi.mocked(request).mock.calls.some(([path, options])=>path==='/strategy-subscriptions' && options?.method==='POST')).toBe(false)
})


it('includes my published strategy in discovery', async () => {
  vi.mocked(request).mockImplementation(async path => path === '/strategy-releases' ? [{...release,owned:true}] : path.endsWith('/bkc-offer') ? null : [])
  render(<StrategyRuntimeLibrary />)
  expect(await screen.findByRole('heading', {name:'趋势规则'})).toBeTruthy()
})
