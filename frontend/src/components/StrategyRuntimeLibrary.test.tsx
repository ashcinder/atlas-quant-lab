import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import StrategyRuntimeLibrary from './StrategyRuntimeLibrary'

vi.mock('../request', async (importOriginal) => ({ ...await importOriginal<object>(), request: vi.fn() }))
const release = { id: 'rel-1', name: '趋势规则', version: 1, source_kind: 'builtin', strategy_id: 'momentum', markets: ['US'], description: '趋势跟随', content_hash: 'a'.repeat(64), params: {}, custom_strategy: null, owned: false, created_at: '2026-01-01' }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(request).mockImplementation(async (path) => {
    if (path === '/strategy-releases') return [release]
    if (path === '/strategy-subscriptions') return []
    if (path.startsWith('/strategies')) return []
    if (path === '/custom-strategies') return []
    return {}
  })
})
afterEach(cleanup)

it('subscribes to an immutable free release and refreshes the library', async () => {
  render(<StrategyRuntimeLibrary />)
  await screen.findByRole('heading', { name: '趋势规则' })
  fireEvent.click(screen.getByRole('button', { name: '免费订阅' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/strategy-subscriptions', expect.objectContaining({ method: 'POST', body: JSON.stringify({ release_id: 'rel-1' }) })))
})
