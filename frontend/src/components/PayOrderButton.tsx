import { useRef, useState } from 'react'
import { formatEther } from 'ethers'
import { request } from '../request'
import { payOrder, WALLET_EVENT } from '../supervisorWallet'
import type { ChainOrder } from '../bkcWallet'
import { useDialogKeyboard } from './dialogKeyboard'

export function PayOrderButton({ orderId, onConfirmed }: {
  orderId: string
  onConfirmed: (order?: ChainOrder) => void
}) {
  const [review, setReview] = useState<ChainOrder | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef(false)
  const reviewRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useDialogKeyboard(Boolean(review), reviewRef, () => { if (!pending.current) setReview(null) }, undefined, false, triggerRef)

  async function act(work: () => Promise<void>) {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      await work()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '付款操作失败，请重新核验')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  async function check() {
    let order = await request<ChainOrder>(`/bkc-orders/${orderId}`)
    if (order.current_order_id && order.current_order_id !== order.id) {
      order = await request<ChainOrder>(`/bkc-orders/${order.current_order_id}`)
    }
    setReview(order)
  }

  async function retry() {
    if (!review?.transaction_hash) return
    const replacement = await request<ChainOrder>(`/bkc-orders/${review.id}/retry`, {
      method: 'POST', body: JSON.stringify({ transaction_hash: review.transaction_hash }),
    })
    setReview(replacement)
  }

  async function pay() {
    if (!review) return
    const id = review.id
    if (review.transaction_hash) {
      await request(`/bkc-orders/${id}/rebroadcast`, { method: 'POST' }).catch(() => undefined)
    }
    const hash = review.transaction_hash || await payOrder(id)
    let state: ChainOrder | null = null
    for (let attempt = 0; attempt < 15; attempt++) {
      state = await request<ChainOrder>(`/bkc-orders/${id}/confirm`, {
        method: 'POST', body: JSON.stringify({ transaction_hash: hash }),
      })
      setReview(state)
      if (state.status === 'confirmed' || state.status === 'failed') break
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    window.dispatchEvent(new Event(WALLET_EVENT))
    if (state?.status === 'confirmed') {
      setReview(null)
      onConfirmed(state)
    } else if (state?.status === 'failed') {
      setError(state.kind === 'subscription' ? '链上交易失败，未授予授权。可核验原交易已回滚后新建订单。' : '链上交易失败，请检查交易回执。')
    } else {
      setError('交易仍待确认，可稍后核验；不会重复扣款')
    }
  }

  return <div className="trine-payment">
    <button ref={triggerRef} type="button" disabled={busy} onClick={event => { event.currentTarget.focus(); void act(check) }}>{busy ? '处理中…' : '支付 / 核验 BKC'}</button>
    {review && <div ref={reviewRef} tabIndex={-1} className="trine-payment-review" role="dialog" aria-label="确认 BKC 支付">
      <strong>确认链上付款</strong>
      <p>{formatEther(BigInt(review.transaction.value))} BKC + 链上手续费</p>
      <small>收款：{review.transaction.to}</small>
      <small>订单：{review.id}</small>
      {review.transaction_hash && <small>交易：{review.transaction_hash}</small>}
      {review.previous_order_id && <small>原失败订单：{review.previous_order_id} · 交易：{review.previous_transaction_hash}</small>}
      {review.status === 'failed' && review.kind === 'subscription' && <p>原交易已失败。重新核验回滚后可创建新订单，原交易记录保留。新订单需再次确认付款。</p>}
      <button type="button" disabled={busy} onClick={() => void act(pay)}>{review.transaction_hash ? '核验原交易' : '确认支付'}</button>
      {review.status === 'failed' && review.kind === 'subscription' && !review.retry_order_id && <button type="button" disabled={busy} onClick={() => void act(retry)}>核验失败交易并新建订单</button>}
      <button type="button" disabled={busy} onClick={() => setReview(null)}>取消</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </div>
}
