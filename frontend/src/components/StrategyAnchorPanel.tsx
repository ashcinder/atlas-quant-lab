import { useState } from 'react'
import { request } from '../request'

type Anchor = { chain_id: number; scope: string; data: string; transaction?: Record<string, string>; anchor: { status: string; transaction_hash?: string; block_number?: number } }
type Wallet = { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> }
const labels: Record<string, string> = { not_anchored: '尚未上链', pending: '待钱包签名', submitted: '等待区块确认', confirmed: '上次核验已确认', failed: '交易失败', unreachable: '链不可达，未确认' }

export default function StrategyAnchorPanel({ releaseId, owned }: { releaseId: string; owned: boolean }) {
  const [result, setResult] = useState<Anchor | null>(null)
  const [hash, setHash] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function act(work: () => Promise<Anchor>) {
    setBusy(true); setError('')
    try { const next = await work(); setResult(next); if (next.anchor.transaction_hash) setHash(next.anchor.transaction_hash) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '存证操作失败') }
    finally { setBusy(false) }
  }
  async function send() {
    const wallet = (window as Window & { ethereum?: Wallet }).ethereum
    if (!wallet) throw new Error('请使用支持以太坊接口的钱包，并连接Supervisor链1051。')
    if (Number(await wallet.request({ method: 'eth_chainId' })) !== 1051) throw new Error('请先在钱包切换到Supervisor链1051。')
    const accounts = await wallet.request({ method: 'eth_requestAccounts' }) as string[]
    if (!accounts[0]) throw new Error('钱包未提供地址')
    const prepared = await request<Anchor>(`/strategy-releases/${releaseId}/anchor/prepare`, { method: 'POST', body: JSON.stringify({ address: accounts[0] }) })
    const txHash = await wallet.request({ method: 'eth_sendTransaction', params: [prepared.transaction] }) as string
    setHash(txHash) // Retain the broadcast hash even if the following network call fails.
    return request<Anchor>(`/strategy-releases/${releaseId}/anchor/confirm`, { method: 'POST', body: JSON.stringify({ transaction_hash: txHash }) })
  }
  return <details className="runtime-anchor"><summary>策略版本上链佐证</summary>
    <p>Supervisor · 链1051。仅登记ID、版本与哈希，源码不上链；不代表收益已获证明。钱包会显示实际网络费用。</p>
    <button disabled={busy} onClick={() => void act(() => request(`/strategy-releases/${releaseId}/anchor`))}>查看登记信息</button>
    {owned && <><button disabled={busy || !!result?.anchor.transaction_hash} onClick={() => void act(send)}>钱包签名上链</button><label>交易哈希<input value={hash} onChange={event => setHash(event.target.value)} placeholder="0x…" /></label><button disabled={busy || !/^0x[0-9a-fA-F]{64}$/.test(hash)} onClick={() => void act(() => request(`/strategy-releases/${releaseId}/anchor/confirm`, { method: 'POST', body: JSON.stringify({ transaction_hash: hash }) }))}>核验链上回执</button></>}
    {result && <p role="status">{labels[result.anchor.status] ?? result.anchor.status}{result.anchor.block_number != null && ` · 区块 ${result.anchor.block_number}`}</p>}
    {error && <p role="alert">{error}</p>}
  </details>
}
