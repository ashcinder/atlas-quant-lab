import {useEffect,useState} from 'react'
import {ChevronRight} from 'lucide-react'
import {request,RUNTIME_CHANGED_EVENT} from '../request'
import type {StrategyRelease,StrategySubscription} from '../types'
import {BkcSubscription} from './BkcControls'
import StrategyAnchorPanel from './StrategyAnchorPanel'
import {CloudProofControl} from './CloudProofControl'
export function PublishedStrategyRows({query='',hideUnverified=false,selectedId,onSelect,onCount}:{query?:string;hideUnverified?:boolean;selectedId?:string;onSelect:(release:StrategyRelease)=>void;onCount?:(count:number)=>void}) {
 const [items,setItems]=useState<StrategyRelease[]>([]),[error,setError]=useState('')
 useEffect(()=>{let active=true;const load=()=>request<StrategyRelease[]>('/strategy-releases').then(value=>{if(active){setItems(value);setError('')}}).catch(e=>{if(active)setError(e.message)});void load();window.addEventListener(RUNTIME_CHANGED_EVENT,load);const timer=setInterval(load,15000);return()=>{active=false;clearInterval(timer);window.removeEventListener(RUNTIME_CHANGED_EVENT,load)}},[])
 const visible=hideUnverified?[]:items.filter(r=>!r.proof_id&&r.name.toLowerCase().includes(query.toLowerCase()))
 useEffect(()=>onCount?.(visible.length),[visible.length,onCount])
 return <>{error&&<p role="alert">策略版本读取失败：{error}</p>}{visible.map(r=><div role="button" tabIndex={0} key={r.id} className={`qj-agent-row ${selectedId===r.id?'is-selected':''}`} onClick={()=>onSelect(r)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(r)}}}>
 <span className="qj-agent-name"><b>—</b><span><strong>{r.name}</strong><small>v{r.version} · {r.owned?'我开发的策略':'公开策略'}</small></span><span className="qj-agent-evidence"><em>{r.proof_status==='proving'||r.proof_status==='queued'?'Proof 生成中':r.published?'无 ZKP 验证':'私有草稿'}</em></span></span>
 <span className="trine-no-report">等待收益报告</span><strong>—</strong><strong>—</strong><strong>—</strong><span className="qj-score"><span><b>—</b><small>未排名</small></span><ChevronRight size={15}/></span></div>)}</>
}
export function ReleaseMarketDetail({release,compact=false}:{release:StrategyRelease;compact?:boolean}) {
 const [subscriptions,setSubscriptions]=useState<StrategySubscription[]>([])
 const [error,setError]=useState('')
 const [published,setPublished]=useState(release.published)
 const refresh=()=>{void request<StrategySubscription[]>('/strategy-subscriptions').then(setSubscriptions).catch(e=>setError(e.message));window.dispatchEvent(new Event(RUNTIME_CHANGED_EVENT))}
 useEffect(()=>{void request<StrategySubscription[]>('/strategy-subscriptions').then(setSubscriptions).catch(e=>setError(e.message))},[release.id])
 return <section className="trine-release-detail">{!compact&&<header><small>策略版本 · v{release.version}</small><h3>{release.name}</h3><span className="trine-evidence-label">{release.proof_id?'ZKP 报告':release.proof_status==='proving'||release.proof_status==='queued'?'Proof 生成中':'无 ZKP 验证'}</span></header>}
 {!compact&&<p>{release.description||'此版本尚无公开收益报告。收益与评分将在报告提交后显示。'}</p>}
 <dl><div><dt>适用市场</dt><dd>{release.markets.join(' / ')}</dd></div><div><dt>版本指纹</dt><dd><code>{release.content_hash}</code></dd></div></dl>
 {published?<BkcSubscription releaseId={release.id} owned={release.owned} subscribed={subscriptions.some(s=>s.release_id===release.id&&s.status==='active')} onChanged={refresh}/>:release.owned&&<button onClick={()=>void request(`/strategy-releases/${release.id}/publish`,{method:'POST'}).then(()=>{setPublished(true);refresh()}).catch(e=>setError(e.message))}>公开此版本</button>}
 {release.proof_id?<a className="qj-proof-link" href={`#/proof/${release.proof_id}`}>验证 Proof ↗</a>:release.owned&&<CloudProofControl releaseId={release.id} sourceKind={release.source_kind}/>}
 <StrategyAnchorPanel releaseId={release.id} owned={release.owned} hasProof={!!release.proof_id}/>{error&&<p role="alert">{error}</p>}</section>
}
export function ProofReleaseDetail({proofId}:{proofId?:string|null}) {
 const [release,setRelease]=useState<StrategyRelease|null>(null)
 const [error,setError]=useState('')
 useEffect(()=>{let active=true;setRelease(null);if(proofId)void request<StrategyRelease[]>('/strategy-releases').then(rows=>{if(active)setRelease(rows.find(r=>r.proof_id===proofId)||null)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[proofId])
 return release?<ReleaseMarketDetail compact key={release.id} release={release}/>:<p className="trine-no-report">{error||'此报告尚未关联可订阅的运行版本。'}</p>
}
