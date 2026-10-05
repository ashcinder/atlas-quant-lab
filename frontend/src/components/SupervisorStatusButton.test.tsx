import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SupervisorStatusButton } from './SupervisorStatusButton'

const mocks = vi.hoisted(() => ({ request: vi.fn(), walletAddress: vi.fn() }))
vi.mock('../request', () => ({ request: mocks.request }))
vi.mock('../supervisorWallet', () => ({ WALLET_EVENT: 'trine-wallet-changed', walletAddress: mocks.walletAddress }))

beforeEach(() => {
  mocks.request.mockReset()
  mocks.walletAddress.mockReset()
})
afterEach(cleanup)

it('ignores a late balance response for the previous wallet', async () => {
  const firstAddress = '0x1111111111111111111111111111111111111111'
  const secondAddress = '0x2222222222222222222222222222222222222222'
  let currentAddress = firstAddress
  let resolveFirst!: (value: unknown) => void
  let resolveSecond!: (value: unknown) => void
  const first = new Promise((resolve) => { resolveFirst = resolve })
  const second = new Promise((resolve) => { resolveSecond = resolve })
  mocks.walletAddress.mockImplementation(() => currentAddress)
  mocks.request.mockImplementation((path: string) => path.includes(firstAddress) ? first : second)

  render(<SupervisorStatusButton expanded />)
  await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(1))
  currentAddress = secondAddress
  act(() => window.dispatchEvent(new Event('trine-wallet-changed')))
  await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(2))
  await act(async () => resolveSecond({ balance_bkc: '2', network_label: 'Supervisor Test' }))
  expect(await screen.findByText('2 BKC')).toBeTruthy()
  expect(screen.getByText('0x222222…222222')).toBeTruthy()

  await act(async () => resolveFirst({ balance_bkc: '1', network_label: 'Old Network' }))
  expect(screen.getByText('2 BKC')).toBeTruthy()
  expect(screen.queryByText('1 BKC')).toBeNull()
  expect(screen.queryByText('Old Network')).toBeNull()
})

it('aborts an in-flight balance request when unmounted', async () => {
  mocks.walletAddress.mockReturnValue('0x3333333333333333333333333333333333333333')
  mocks.request.mockReturnValue(new Promise(() => undefined))
  const view = render(<SupervisorStatusButton />)
  await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(1))
  const signal = mocks.request.mock.calls[0][1].signal as AbortSignal
  expect(signal.aborted).toBe(false)
  view.unmount()
  expect(signal.aborted).toBe(true)
})
