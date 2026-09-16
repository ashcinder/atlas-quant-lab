// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import ProofPage from './ProofPage'
import { request } from '../request'
vi.mock('../request', () => ({ request: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const proof = { id: 'qzp_test', image_id: 'image', proof_hash: 'hash', public_inputs_hash: 'inputs', proof_profile: 'v2', receipt_size: 500, public_statement: { metrics: {} } }
it('requires a fresh verifier response before showing success', async () => {
  vi.mocked(request).mockResolvedValueOnce(proof).mockResolvedValueOnce({ valid: true, image_id: 'image', proof_hash: 'hash', journal: {}, verification_seconds: .1, verified_at: 'now' })
  render(<ProofPage proofId="qzp_test" />)
  fireEvent.click(await screen.findByText('验证 Proof'))
  expect(await screen.findByText('本次密码学验证通过')).toBeTruthy()
  expect(vi.mocked(request).mock.calls[1][1]?.method).toBe('POST')
})
it('does not show verified when image binding mismatches', async () => {
  vi.mocked(request).mockResolvedValueOnce(proof).mockResolvedValueOnce({ valid: true, image_id: 'other', proof_hash: 'hash' })
  render(<ProofPage proofId="qzp_test" />)
  fireEvent.click(await screen.findByText('验证 Proof'))
  expect((await screen.findByRole('alert')).textContent).toContain('不一致')
  expect(screen.queryByText('本次密码学验证通过')).toBeNull()
})
