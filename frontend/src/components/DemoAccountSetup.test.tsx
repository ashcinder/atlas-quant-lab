import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { request } from '../request'
import DemoAccountSetup from './DemoAccountSetup'
vi.mock('../request', () => ({ request: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('saves demo credentials through the backend then clears password fields', async () => {
  vi.mocked(request).mockResolvedValue({ configured: true, verified: true, mode: 'demo' })
  const connected = vi.fn().mockResolvedValue(undefined)
  render(<DemoAccountSetup onConnected={connected} />)
  fireEvent.click(screen.getByText('接入模拟交易账户 · 币安 / 欧易'))
  fireEvent.change(screen.getByLabelText('模拟 API Key'), { target: { value: 'test-key' } })
  fireEvent.change(screen.getByLabelText('模拟 API Secret'), { target: { value: 'test-secret' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: '验证连接并保存' }))
  await screen.findByRole('status')
  expect(request).toHaveBeenCalledWith('/trading/demo-accounts/binance', expect.objectContaining({ method: 'PUT' }))
  expect((screen.getByLabelText('模拟 API Secret') as HTMLInputElement).value).toBe('')
  await waitFor(() => expect(connected).toHaveBeenCalledTimes(1))
})

it('switching venues clears secrets and requires the OKX passphrase', () => {
  render(<DemoAccountSetup onConnected={vi.fn()} />)
  fireEvent.click(screen.getByText('接入模拟交易账户 · 币安 / 欧易'))
  fireEvent.change(screen.getByLabelText('模拟 API Key'), { target: { value: 'test-key' } })
  fireEvent.change(screen.getByLabelText('模拟交易所'), { target: { value: 'okx' } })
  expect((screen.getByLabelText('模拟 API Key') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('模拟 Passphrase') as HTMLInputElement).required).toBe(true)
  expect(request).not.toHaveBeenCalled()
})
