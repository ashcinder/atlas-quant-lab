import {useState}from'react'
import {formatEther} from 'ethers'
import {request}from'../request'
import {payOrder,WALLET_EVENT}from'../supervisorWallet'
import type{ChainOrder}from'../bkcWallet'
export function PayOrderButton({orderId,onConfirmed}:{orderId:string;onConfirmed:()=>void}){
 const[review,setReview]=useState<ChainOrder|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 async function check(){setBusy(true);setError('');try{setReview(await request<ChainOrder>(`/bkc-orders/${orderId}`))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 async function pay(){if(!review||busy)return;setBusy(true);setError('');try{if(review.transaction_hash)await request(`/bkc-orders/${orderId}/rebroadcast`,{method:'POST'}).catch(()=>undefined);const tx=review.transaction_hash||await payOrder(orderId);let state:ChainOrder|null=null;for(let i=0;i<15;i++){state=await request<ChainOrder>(`/bkc-orders/${orderId}/confirm`,{method:'POST',body:JSON.stringify({transaction_hash:tx})});setReview(state);if(state.status==='confirmed'||state.status==='failed')break;await new Promise(r=>setTimeout(r,2000))}window.dispatchEvent(new Event(WALLET_EVENT));if(state?.status==='confirmed'){setReview(null);onConfirmed()}else if(state?.status==='failed')setError('链上交易失败，未授予授权，请检查交易回执');else setError('交易仍待确认，可稍后核验；不会重复扣款')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <div className="trine-payment"><button disabled={busy} onClick={()=>void check()}>{busy?'处理中…':'支付 / 核验 BKC'}</button>{review&&<div className="trine-payment-review" role="dialog" aria-label="确认 BKC 支付"><strong>确认链上付款</strong><p>{formatEther(BigInt(review.transaction.value))} BKC + 链上手续费</p><small>收款：{review.transaction.to}</small><small>订单：{orderId}</small>{review.transaction_hash&&<small>交易：{review.transaction_hash}</small>}<button disabled={busy} onClick={()=>void pay()}>{review.transaction_hash?'核验原交易':'确认支付'}</button><button disabled={busy} onClick={()=>setReview(null)}>取消</button></div>}{error&&<p role="alert">{error}</p>}</div>
}
