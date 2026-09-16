import { afterEach, expect, it, vi } from 'vitest'
import { request } from './request'
import { connectBkc, sendBkcOrder, type ChainOrder } from './bkcWallet'
vi.mock('./request', () => ({ request: vi.fn() }))
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks() })
const address = '0x'+'a'.repeat(40)
it('rejects another Supervisor instance with the same chain ID', async () => {
  vi.mocked(request).mockResolvedValue({ chain_id:1051, genesis_hash:'0x123', rpc_url:'http://localhost:42515' })
  const rpc = vi.fn(async ({ method }: { method: string }) => method === 'eth_chainId' ? '0x41b' : { hash:'0x456' })
  vi.stubGlobal('ethereum', { request:rpc })
  await expect(connectBkc()).rejects.toThrow('另一个实例')
  expect(rpc.mock.calls.some(([x]) => x.method === 'eth_requestAccounts')).toBe(false)
})
it('never sends an order from a different active wallet', async () => {
  vi.mocked(request).mockResolvedValue({ chain_id:1051, genesis_hash:'0x123' })
  const rpc = vi.fn(async ({ method }: { method: string }) => method === 'eth_chainId' ? '0x41b' : method === 'eth_getBlockByNumber' ? { hash:'0x123' } : [address])
  vi.stubGlobal('ethereum', { request:rpc })
  await expect(sendBkcOrder({ signer:'0x'+'b'.repeat(40), genesis:'0x123' } as ChainOrder)).rejects.toThrow('切回')
  expect(rpc.mock.calls.some(([x]) => x.method === 'eth_sendTransaction')).toBe(false)
})
