import {useEffect,useState} from 'react'
import {request,RUNTIME_CHANGED_EVENT} from '../request'
import type{StrategyRelease,StrategySubscription}from'../types'
export function SubscribedStrategyPicker({value,onChange}:{value:string;onChange:(id:string)=>void}){
 const[releases,setReleases]=useState<StrategyRelease[]>([])
 useEffect(()=>{let active=true;const load=()=>Promise.all([request<StrategyRelease[]>('/strategy-releases'),request<StrategySubscription[]>('/strategy-subscriptions')]).then(([r,s])=>{if(active)setReleases(r.filter(x=>x.source_kind!=='private_runner'&&(x.owned||s.some(y=>y.release_id===x.id&&y.status==='active'))))}).catch(()=>{});void load();window.addEventListener(RUNTIME_CHANGED_EVENT,load);return()=>{active=false;window.removeEventListener(RUNTIME_CHANGED_EVENT,load)}},[])
 return <label className="trine-release-picker">策略来源<select value={value} onChange={e=>onChange(e.target.value)}><option value="">内置策略模板</option>{releases.map(r=><option key={r.id} value={r.id}>{r.name} · v{r.version} · {r.owned?'我开发的':'已订阅'}</option>)}</select></label>
}
