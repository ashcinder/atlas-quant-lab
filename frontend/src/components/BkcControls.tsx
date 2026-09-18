import { walletAddress } from '../supervisorWallet'
import { PayOrderButton } from './PayOrderButton'
import { useEffect, useRef, useState } from 'react'
import { walletMessage, type ChainOrder } from '../bkcWallet'
import { request } from '../request'
import { userStorageKey } from '../storage'
import './quant-controls.css'


type Offer = { amount_bkc: string; recipient: string; terms: string }
const stateLabels: Record<string, string> = { pending: '待本地账户签名', submitted: '已广播，等待确认', confirmed: '链上已确认', failed: '交易失败' }
export function ChainOrderPanel({ kind, resourceId, onConfirmed }: { kind: 'subscription' | 'report'; resourceId: string; onConfirmed?: () => void }) {
  const address = walletAddress()
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
    const address = walletAddress()
    if (!/^0x[0-9a-f]{40}$/i.test(address)) throw new Error('请输入 Supervisor 本地签名账户地址')
    const path = kind === 'subscription' ? `/strategy-releases/${resourceId}/bkc-order` : `/runs/${resourceId}/anchor-order`
    const next = await request<ChainOrder>(path, { method: 'POST', body: JSON.stringify({ address }) })
    setOrder(next); setHash(next.transaction_hash || hash); remember(next, next.transaction_hash || hash)
    setReview(false)
  }
  async function confirm(tx = hash, current = order) {
    if (!current || !tx) return
    const next = await request<ChainOrder>(`/bkc-orders/${current.id}/confirm`, { method: 'POST', body: JSON.stringify({ transaction_hash: tx }) })
    setOrder(next); remember(next, tx)
    if (next.status === 'confirmed') onConfirmed?.()
  }
  const value = order ? BigInt(order.transaction.value) : 0n
  const amount = `${value / 10n ** 18n}.${(value % 10n ** 18n).toString().padStart(18, '0').replace(/0+$/, '') || '0'}`
  return <div className="bkc-order-panel">
    <small>{address ? `支付账户 ${address.slice(0,8)}…${address.slice(-6)}` : "请在设置中配置并解锁 Supervisor 账户"}</small><button disabled={busy || !!hash || order?.status === 'confirmed'} onClick={() => void act(prepare)}>{busy ? '处理中…' : kind === 'report' ? '公开回测收益并上链' : '使用 BKC 订阅此版本'}</button>
    {order && <><PayOrderButton orderId={order.id} onConfirmed={()=>{onConfirmed?.();void act(async()=>{setOrder(await request<ChainOrder>(`/bkc-orders/${order.id}`))})}}/><small role="status">{stateLabels[order.status] || order.status}{order.block_number != null ? ` · 区块 ${order.block_number}` : ''}</small><label>交易哈希<input aria-label="BKC交易哈希" value={hash} onChange={e => setHash(e.target.value)} placeholder="Supervisor 已广播的交易哈希" /></label><button disabled={busy || !/^0x[0-9a-f]{64}$/i.test(hash)} onClick={() => void act(() => confirm())}>核验交易 / 恢复订单</button></>}
    {error && <p role="alert">{error}</p>}
    <dialog ref={dialog} className="atlas-indicator-dialog" onCancel={() => setReview(false)} aria-label="核对链上交易">
      <h3>{kind === 'report' ? '公开回测报告' : '订阅订单'}</h3>
      <p>{kind === 'report' ? '公开收益指标、回测配置和报告摘要。记录在 Supervisor 上；此操作是报告存证，不代表收益已通过零知识验证。' : `支付 ${amount} BKC，获得当前策略版本的使用授权。新版本单独订阅，不自动续费。`}</p>
      <p>网络：Supervisor · 1051</p><p className="break-anywhere">收款地址：{order?.transaction.to}</p>
      {kind === 'report' && <pre>{JSON.stringify(order?.payload, null, 2)}</pre>}
      <p>使用本地 Supervisor 账户工具签名并广播以下交易，再回到此处粘贴交易哈希。平台直接向节点核验收款、金额和数据。</p><pre>{JSON.stringify(order?.transaction, null, 2)}</pre><button onClick={() => setReview(false)}>已查看，填写交易哈希</button>
    </dialog>
  </div>
}

export function BkcSubscription({ releaseId, owned, subscribed, onChanged }: { releaseId: string; owned: boolean; subscribed: boolean; onChanged: () => void }) {
  const [recipient, setRecipient] = useState(walletAddress)
  const [offer, setOffer] = useState<Offer | null>(null), [loaded, setLoaded] = useState(false), [error, setError] = useState(''), [price, setPrice] = useState('0.01'), [busy, setBusy] = useState(false)
  useEffect(() => { let active = true; request<Offer | null>(`/strategy-releases/${releaseId}/bkc-offer`).then(value => { if (active) { if (value !== null && (typeof value.amount_bkc !== 'string' || !/^0x[0-9a-f]{40}$/i.test(value.recipient))) { setError('订阅价格响应无效，请刷新'); return } setOffer(value); setLoaded(true) } }).catch(cause => { if (active) setError(walletMessage(cause)) }); return () => { active = false } }, [releaseId])
  async function setPriceOffer() {
    if (busy) return; setBusy(true); setError('')
    try {
      const receiver = recipient || walletAddress()
      if (!/^0x[0-9a-f]{40}$/i.test(receiver)) throw new Error('请输入 Supervisor 收款地址')
      const next = await request<Offer>(`/strategy-releases/${releaseId}/bkc-offer`, { method: 'PUT', body: JSON.stringify({ recipient: receiver, amount_bkc: price }) })
      setOffer(next); onChanged()
    } catch (cause) { setError(walletMessage(cause)) } finally { setBusy(false) }
  }
  return <div className="bkc-offer">
    {offer && <><strong>{offer.amount_bkc} BKC / 当前版本</strong><small>{offer.terms}</small><small className="break-anywhere">收款 {offer.recipient}</small></>}
    {owned && loaded && !offer && <details><summary>设置 BKC 订阅价格</summary><p>指定 Supervisor 收款账户。保存后此版本价格固定；已有订阅保留。</p><label>Supervisor 收款地址<input value={recipient} onChange={e=>setRecipient(e.target.value)} placeholder="0x…" /></label><label>BKC 金额<input aria-label="BKC订阅价格" inputMode="decimal" value={price} onChange={e => setPrice(e.target.value)} /></label><button disabled={busy} onClick={() => void setPriceOffer()}>固定价格与收款地址</button></details>}
    {!owned && (subscribed ? <small>已订阅此版本</small> : offer ? <ChainOrderPanel kind="subscription" resourceId={releaseId} onConfirmed={onChanged} /> : loaded ? <small>作者尚未设置 BKC 价格</small> : <small>读取订阅价格…</small>)}
    {error && <small role="alert">{error}</small>}
  </div>
}
