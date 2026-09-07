import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { SystemStatus } from './SystemStatus'

vi.mock('../api', () => ({ api: { getHealth: vi.fn(), getQuantChainStatus: vi.fn(), listZkProfiles: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

describe('system capability status', () => {
  it('does not equate an online backend with ZKP, TEE, chain or real trading readiness', async () => {
    vi.mocked(api.getHealth).mockResolvedValue({ status: 'ok', name: 'Atlas', version: '0.3.0' })
    vi.mocked(api.listZkProfiles).mockResolvedValue([])
    vi.mocked(api.getQuantChainStatus).mockRejectedValue(new Error('unreachable'))
    render(<SystemStatus onClose={vi.fn()} />)
    expect(await screen.findByText('后端服务在线 · v0.3.0')).toBeTruthy()
    expect(screen.getAllByText('未就绪')).toHaveLength(2)
    expect(screen.getByText('未接入')).toBeTruthy()
    expect(screen.getByText('未启用')).toBeTruthy()
    expect(screen.getByText(/链连接检查失败/)).toBeTruthy()
  })

  it('still explains recovery when all services are unreachable, and supports Escape', async () => {
    vi.mocked(api.getHealth).mockRejectedValue(new Error('offline'))
    vi.mocked(api.listZkProfiles).mockRejectedValue(new Error('offline'))
    vi.mocked(api.getQuantChainStatus).mockRejectedValue(new Error('offline'))
    const close = vi.fn()
    render(<SystemStatus onClose={close} />)
    expect(await screen.findByText('无法连接后端服务')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重新检查' }).hasAttribute('disabled')).toBe(false)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(close).toHaveBeenCalledTimes(1)
  })
})
