import { useEffect, useState } from 'react'
import { request } from '../request'
import { walletAddress } from '../supervisorWallet'
import { PayOrderButton } from './PayOrderButton'
import type { ChainOrder } from '../bkcWallet'
type Anchor = {kind:string;transaction_hash:string;block_number:number;genesis:string;chain_id:number;payload:Record<string,unknown>}
export default function StrategyAnchorPanel({ releaseId, owned, hasProof=false }: { releaseId: string; owned: boolean; hasProof?:boolean }) {
 const [order,setOrder]=useState<ChainOrder|null>(null),[anchors,setAnchors]=useState<Anchor[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const load=()=>request<Anchor[]>(`/strategy-releases/${releaseId}/anchors`).then(setAnchors).catch(e=>setError(e.message))
 useEffect(()=>{void load()},[releaseId])
 async function prepare(){setBusy(true);setError('');try{const address=walletAddress();if(!address)throw new Error('请先在设置中配置 Supervisor 账户');setOrder(await request<ChainOrder>(`/strategy-releases/${releaseId}/${hasProof?'proof-anchor-order':'anchor-order'}`,{method:'POST',body:JSON.stringify({address})}))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <section className="trine-chain-card"><h4>链上记录</h4><p>{hasProof?'公开收益、市场区间、程序与 Proof 指纹共同存证。原始 Proof 可在验证页下载；存证交易不等同于链上合约验证。':'登记策略版本与哈希；源码不上链，版本存证不代表收益已获证明。'}</p>
 {anchors.length?anchors.map(a=><details key={a.transaction_hash}><summary>{a.kind==='proof_anchor'?'Proof 与收益已存证':'版本已存证'} · 区块 #{a.block_number}</summary><dl><dt>Supervisor · {a.chain_id}</dt><dd>创世块 <code>{a.genesis}</code></dd><dt>交易哈希</dt><dd><code>{a.transaction_hash}</code></dd></dl><pre>{JSON.stringify(a.payload,null,2)}</pre></details>):<small>尚无已确认的链上存证</small>}
 {(owned||hasProof)&&!anchors.some(a=>a.kind===(hasProof?'proof_anchor':'release'))&&<button disabled={busy} onClick={()=>void prepare()}>{busy?'读取中…':hasProof?'收益与 Proof 上链':'策略版本上链'}</button>}
 {order&&(order.status==='confirmed'?<p>交易已确认 · 区块 #{order.block_number}</p>:<PayOrderButton orderId={order.id} onConfirmed={()=>{void load();void prepare()}}/>)}{error&&<p role="alert">{error}</p>}</section>
}
