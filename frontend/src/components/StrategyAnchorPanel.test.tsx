import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import StrategyAnchorPanel from './StrategyAnchorPanel'

const mocks = vi.hoisted(() => ({ request: vi.fn(), walletAddress: vi.fn() }))
vi.mock('../request', () => ({ request: mocks.request }))
vi.mock('../supervisorWallet', () => ({ walletAddress: mocks.walletAddress }))
vi.mock('./PayOrderButton', () => ({ PayOrderButton: () => <span>支付交易</span> }))

const thirdParty = {
  kind: 'proof_anchor', transaction_hash: `0x${'1'.repeat(64)}`, block_number: 10,
  genesis: `0x${'2'.repeat(64)}`, chain_id: 1051,
  signer: `0x${'b'.repeat(40)}`, actor_role: 'third_party',
  is_mine: false, is_current_proof: true, payload: { proof_id: 'proof-current' },
}

beforeEach(() => {
  mocks.request.mockReset()
  mocks.walletAddress.mockReset()
  mocks.walletAddress.mockReturnValue(`0x${'a'.repeat(40)}`)
})
afterEach(cleanup)

it('shows the actor role and actual signer without letting a third party hide the author action', async () => {
  const author = {
    ...thirdParty, transaction_hash: `0x${'3'.repeat(64)}`, block_number: 9,
    signer: `0x${'a'.repeat(40)}`, actor_role: 'author', is_current_proof: false,
    payload: { proof_id: 'proof-old' },
  }
  mocks.request.mockResolvedValue([thirdParty, author])

  render(<StrategyAnchorPanel releaseId="release-1" owned hasProof />)

  expect((await screen.findAllByText('第三方存证')).length).toBeGreaterThan(0)
  expect(screen.getAllByText('作者存证').length).toBeGreaterThan(0)
  expect(screen.getAllByText('平台发起身份').length).toBe(2)
  expect(screen.getAllByText('实际签名地址').length).toBe(2)
  expect(screen.getByText(thirdParty.signer)).toBeTruthy()
  expect(screen.getByRole('button', { name: '收益与 Proof 上链' })).toBeTruthy()
})

it('hides the action only when the current user anchored the current proof', async () => {
  mocks.request.mockResolvedValue([{ ...thirdParty, is_mine: true }])

  render(<StrategyAnchorPanel releaseId="release-1" owned={false} hasProof />)

  await screen.findAllByText('第三方存证')
  expect(screen.queryByRole('button', { name: '收益与 Proof 上链' })).toBeNull()
})

it('keeps the action available when the current users anchor belongs to an older proof', async () => {
  mocks.request.mockResolvedValue([{ ...thirdParty, is_mine: true, is_current_proof: false }])

  render(<StrategyAnchorPanel releaseId="release-1" owned={false} hasProof />)

  await screen.findAllByText('第三方存证')
  expect(screen.getByRole('button', { name: '收益与 Proof 上链' })).toBeTruthy()
})
