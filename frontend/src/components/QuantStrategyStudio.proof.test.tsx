import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QuantStrategyStudio } from './QuantStrategyStudio'
import { api } from '../api'
vi.mock('../api', () => ({ api: {
  getStudioSpec: vi.fn().mockResolvedValue({}),
  getStudioTemplates: vi.fn().mockResolvedValue([{ id: 'test', workflow: { name: 'Test', nodes: [], edges: [] } }]),
  listQuantAgents: vi.fn().mockResolvedValue([]),
  listZkProfiles: vi.fn().mockResolvedValue([]),
  validateStudioWorkflow: vi.fn().mockResolvedValue({ valid: true }),
  createZkMarketDataset: vi.fn().mockResolvedValue({ market_data_hash: 'test-hash' }),
} }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('submits edited UTC dates and invalidates old data on asset changes', async () => {
  const onError = vi.fn()
  const { rerender } = render(<QuantStrategyStudio onError={onError} activeTab="proof" assetSymbol="BTC-USD" />)
  fireEvent.input(await screen.findByLabelText('证明开始日期'), { target: { value: '2025-08-01' } })
  fireEvent.input(screen.getByLabelText('证明结束日期'), { target: { value: '2025-09-02' } })
  fireEvent.click(screen.getByRole('button', { name: '生成数据集' }))
  await waitFor(() => expect(api.createZkMarketDataset).toHaveBeenCalledWith('BTC-USD', 'crypto', '1d', '2025-08-01T00:00:00Z', '2025-09-02T00:00:00Z'))
  expect(await screen.findByRole('link', { name: '下载 market.json' })).toBeTruthy()
  rerender(<QuantStrategyStudio onError={onError} activeTab="proof" assetSymbol="ETH-USD" />)
  expect(screen.queryByRole('link', { name: '下载 market.json' })).toBeNull()
  expect((screen.getByRole('button', { name: '选择 proof.r0' }) as HTMLButtonElement).disabled).toBe(true)
})
