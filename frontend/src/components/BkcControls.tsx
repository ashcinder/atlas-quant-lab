import { useEffect, useRef, useState } from 'react'
import { connectBkc, sendBkcOrder, walletMessage, walletProvider, type ChainOrder } from '../bkcWallet'
import { request } from '../request'
import { userStorageKey } from '../storage'
import './quant-controls.css'

export function BkcWallet() {
  const [address, setAddress] = useState(''), [balance, setBalance] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => {
    try {
      const provider = walletProvider(), reset = () => { setAddress(''); setBalance('') }
      provider.on?.('accountsChanged', reset); provider.on?.('chainChanged', reset)
      return () => { provider.removeListener?.('accountsChanged', reset); provider.removeListener?.('chainChanged', reset) }
    } catch { /* connect on demand */ }
  }, [])
  async function connect() {
    if (busy) return; setBusy(true); setError('')
    try {
      const { provider, address: account } = await connectBkc()
      const value = BigInt(await provider.request({ method: 'eth_getBalance', params: [account, 'latest'] }) as string)
      setAddress(account); setBalance(`${value / 10n ** 18n}.${(value % 10n ** 18n).toString().padStart(18, '0').slice(0, 4)}`)
    } catch (cause) { setError(walletMessage(cause)) } finally { setBusy(false) }
  }
  return <div className="bkc-wallet-bar"><span>Supervisor · BKC</span><button disabled={busy} onClick={() => void connect()}>{busy ? '连接中…' : address ? `${address.slice(0, 6)}…${address.slice(-4)} · ${balance} BKC · 刷新` : '连接 MetaMask'}</button>{error && <small role="alert">{error}</small>}</div>
}

type Offer = { amount_bkc: string; recipient: string; terms: string }
const stateLabels: Record<string, string> = { pending: '待钱包确认', submitted: '已广播，等待确认', confirmed: '链上已确认', failed: '交易失败' }
export function ChainOrderPanel({ kind, resourceId, onConfirmed }: { kind: 'subscription' | 'report'; resourceId: string; onConfirmed?: () => void }) {
  const storageKey = userStorageKey(`atlas:bkc-order:${kind}:${resourceId}`)
  const [order, setOrder] = useState<ChainOrder | null>(null), [hash, setHash] = useState(() => { try { return JSON.parse(localStorage.getItem(storageKey) || 'null')?.hash || '' } catch { return '' } }), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const [review, setReview] = useState(false)
  useEffect(() => { if (review) dialog.current?.showModal(); else if (dialog.current?.open) dialog.current.close() }, [review])
  useEffect(() => {
    let active = true
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
      if (saved?.id) { request<ChainOrder>(`/bkc-orders/${saved.id}`).then(value => { if (active) { setOrder(value); setHash(value.transaction_hash || saved.hash || '') } }).catch(() => undefined) }
    } catch { /* recover via server preparation */ }
    return () => { active = false }
  }, [storageKey])
  const remember = (next: ChainOrder, tx = '') => { try { localStorage.setItem(storageKey, JSON.stringify({ id: next.id, hash: tx })) } catch { /* keep hash in UI */ } }
  async function act(work: () => Promise<void>) { if (busy) return; setBusy(true); setError(''); try { await work() } catch (cause) { setError(walletMessage(cause)) } finally { setBusy(false) } }
  async function prepare() {
    const { address } = await connectBkc()
    const path = kind === 'subscription' ? `/strategy-releases/${resourceId}/bkc-order` : `/runs/${resourceId}/anchor-order`
    const next = await request<ChainOrder>(path, { method: 'POST', body: JSON.stringify({ address }) })
    setOrder(next); setHash(next.transaction_hash || hash); remember(next, next.transaction_hash || hash)
    if (!next.transaction_hash && !hash) setReview(true)
  }
  async function confirm(tx = hash, current = order) {
    if (!current || !tx) return
    const next = await request<ChainOrder>(`/bkc-orders/${current.id}/confirm`, { method: 'POST', body: JSON.stringify({ transaction_hash: tx }) })
    setOrder(next); remember(next, tx)
    if (next.status === 'confirmed') onConfirmed?.()
  }
  async function send() {
    if (!order) return
    const tx = await sendBkcOrder(order)
    setHash(tx); remember(order, tx); setReview(false)
    await confirm(tx, order)
  }
  const value = order ? BigInt(order.transaction.value) : 0n
  const amount = `${value / 10n ** 18n}.${(value % 10n ** 18n).toString().padStart(18, '0').replace(/0+$/, '') || '0'}`
  return <div className="bkc-order-panel">
    <button disabled={busy || !!hash || order?.status === 'confirmed'} onClick={() => void act(prepare)}>{busy ? '处理中…' : kind === 'report' ? '公开回测收益并上链' : '使用 BKC 订阅此版本'}</button>
    {order && <><small role="status">{stateLabels[order.status] || order.status}{order.block_number != null ? ` · 区块 ${order.block_number}` : ''}</small><label>交易哈希<input aria-label="BKC交易哈希" value={hash} onChange={e => setHash(e.target.value)} placeholder="钱包已广播时粘贴哈希" /></label><button disabled={busy || !/^0x[0-9a-f]{64}$/i.test(hash)} onClick={() => void act(() => confirm())}>核验交易 / 恢复订单</button></>}
    {error && <p role="alert">{error}</p>}
    <dialog ref={dialog} className="atlas-indicator-dialog" onCancel={() => setReview(false)} aria-label="核对链上交易">
      <h3>{kind === 'report' ? '公开回测报告' : '订阅订单'}</h3>
      <p>{kind === 'report' ? '公开收益指标、回测配置和报告摘要。记录在 Supervisor 上；此操作是报告存证，不代表收益已通过零知识验证。' : `支付 ${amount} BKC，获得当前策略版本的使用授权。新版本单独订阅，不自动续费。`}</p>
      <p>网络：Supervisor · 1051</p><p className="break-anywhere">收款地址：{order?.transaction.to}</p>
      {kind === 'report' && <pre>{JSON.stringify(order?.payload, null, 2)}</pre>}
      <small>MetaMask 将显示交易金额与网络费用。</small><div><button disabled={busy} onClick={() => setReview(false)}>返回</button><button disabled={busy} onClick={() => void act(send)}>在 MetaMask 中确认</button></div>
    </dialog>
  </div>
}

export function BkcSubscription({ releaseId, owned, subscribed, onChanged }: { releaseId: string; owned: boolean; subscribed: boolean; onChanged: () => void }) {
  const [offer, setOffer] = useState<Offer | null>(null), [loaded, setLoaded] = useState(false), [error, setError] = useState(''), [price, setPrice] = useState('0.01'), [busy, setBusy] = useState(false)
  useEffect(() => { let active = true; request<Offer | null>(`/strategy-releases/${releaseId}/bkc-offer`).then(value => { if (active) { if (value !== null && (typeof value.amount_bkc !== 'string' || !/^0x[0-9a-f]{40}$/i.test(value.recipient))) { setError('订阅价格响应无效，请刷新'); return } setOffer(value); setLoaded(true) } }).catch(cause => { if (active) setError(walletMessage(cause)) }); return () => { active = false } }, [releaseId])
  async function setPriceOffer() {
    if (busy) return; setBusy(true); setError('')
    try {
      const { address } = await connectBkc()
      const next = await request<Offer>(`/strategy-releases/${releaseId}/bkc-offer`, { method: 'PUT', body: JSON.stringify({ recipient: address, amount_bkc: price }) })
      setOffer(next); onChanged()
    } catch (cause) { setError(walletMessage(cause)) } finally { setBusy(false) }
  }
  async function freeSubscribe() {
    setBusy(true); setError('')
    try { await request('/strategy-subscriptions', { method: 'POST', body: JSON.stringify({ release_id: releaseId }) }); onChanged() } catch (cause) { setError(walletMessage(cause)) } finally { setBusy(false) }
  }
  return <div className="bkc-offer">
    {offer && <><strong>{offer.amount_bkc} BKC / 当前版本</strong><small>{offer.terms}</small><small className="break-anywhere">收款 {offer.recipient}</small></>}
    {owned && loaded && !offer && <details><summary>设置 BKC 订阅价格</summary><p>当前连接钱包作为收款人。保存后此版本价格固定；已有订阅保留。</p><label>BKC 金额<input aria-label="BKC订阅价格" inputMode="decimal" value={price} onChange={e => setPrice(e.target.value)} /></label><button disabled={busy} onClick={() => void setPriceOffer()}>固定价格与钱包收款地址</button></details>}
    {!owned && (subscribed ? <small>已订阅此版本</small> : offer ? <ChainOrderPanel kind="subscription" resourceId={releaseId} onConfirmed={onChanged} /> : loaded ? <button disabled={busy} onClick={() => void freeSubscribe()}>免费订阅</button> : <small>读取订阅价格…</small>)}
    {error && <small role="alert">{error}</small>}
  </div>
}
