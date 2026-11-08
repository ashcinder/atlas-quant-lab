import type { Adjustment, Asset, Bar, DataSource, Interval } from '../types'
import type { MarketInput } from './model'
import type { ComputeStore } from './persistence'
import { request } from '../request'
export interface MarketChunk {sha256:string;count:number;start:number;end:number;url:string}
export interface MarketManifest {status:'ready';schema:'atlas.market/v1';dataset_id:string;asset:Asset;interval:Interval;adjustment:Adjustment;source:string;source_note:string|null;fetched_at:number;is_stale:boolean;start:number;end:number;count:number;chunks:MarketChunk[];coverage?:{start:number;end:number;basis:string};conversions?:Record<string,string>}
export interface MarketQuery {symbol:string;asset_class:string;interval:Interval;adjustment:Adjustment;data_source:DataSource;start?:string;end?:string}
export class MarketPreparingError extends Error {constructor(message='历史数据尚未发布，请等待数据准备完成后重试'){super(message);this.name='MarketPreparingError'}}
export function validateManifest(raw:unknown):MarketManifest {
 if(!raw||typeof raw!=='object')throw new Error('行情清单格式无效')
 if('status'in raw&&raw.status==='preparing')throw new MarketPreparingError('message'in raw&&typeof raw.message==='string'?raw.message:undefined)
 const m=raw as MarketManifest
 if(m.status!=='ready'||m.schema!=='atlas.market/v1'||!m.dataset_id||!m.asset?.symbol||!Array.isArray(m.chunks)||!m.chunks.length||!Number.isInteger(m.count)||m.count<1||!Number.isFinite(m.start)||!Number.isFinite(m.end)||m.end<m.start)throw new Error('行情清单格式无效')
 let total=0,previous=-Infinity
 for(const c of m.chunks){if(!/^[a-f\d]{64}$/.test(c.sha256)||!Number.isInteger(c.count)||c.count<1||!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.end<c.start||c.start<=previous||typeof c.url!=='string'||!c.url)throw new Error('行情分块清单无效或顺序重叠');total+=c.count;previous=c.end}
 if(m.coverage&&(!Number.isFinite(m.coverage.start)||!Number.isFinite(m.coverage.end)||m.coverage.start>m.coverage.end))throw new Error('行情查询覆盖范围无效')
 if(total!==m.count||m.chunks[0].start!==m.start||m.chunks.at(-1)!.end!==m.end)throw new Error('行情清单覆盖范围或数量不一致')
 return m
}
export async function fetchManifest(query:MarketQuery,store:ComputeStore,signal?:AbortSignal):Promise<MarketManifest>{
 const params=new URLSearchParams(Object.entries(query).filter(([,v])=>v!==undefined) as [string,string][])
 // A cached query resolves offline only when the network is unavailable; explicit
 // preparing/missing/authorization errors are never replaced by another dataset.
 let raw:unknown
 try{raw=await request<unknown>(`/market/manifest?${params}`,{signal})}
 catch(error){if(signal?.aborted)throw error;const kind=error&&typeof error==='object'&&'kind'in error?error.kind:null;if(kind!=='network')throw error;const cached=await store.get<MarketManifest>('manifests',`query:${params}`);if(!cached)throw error;return validateManifest(cached)}
 const manifest=validateManifest(raw);await store.put('manifests',manifest.dataset_id,manifest);await store.put('manifests',`query:${params}`,manifest);return manifest
}
export async function fetchDatasetManifest(id:string,store:ComputeStore,signal?:AbortSignal):Promise<MarketManifest>{
 const cached=await store.get<MarketManifest>('manifests',id);if(cached){const manifest=validateManifest(cached);if(manifest.dataset_id!==id)throw new Error('缓存中的数据集版本不符');return manifest}
 const manifest=validateManifest(await request<unknown>(`/market/datasets/${encodeURIComponent(id)}`,{signal}));if(manifest.dataset_id!==id)throw new Error('服务返回了错误的数据集版本');await store.put('manifests',id,manifest);return manifest
}
export async function sha256(buffer:ArrayBuffer):Promise<string>{if(!globalThis.crypto?.subtle)throw new Error('当前浏览器缺少安全摘要能力，请在 HTTPS 或本机环境运行');return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),b=>b.toString(16).padStart(2,'0')).join('')}
export async function decodeChunk(buffer:ArrayBuffer,chunk:MarketChunk):Promise<Bar[]>{
 if(await sha256(buffer)!==chunk.sha256)throw new Error('行情分块哈希校验失败，输入未被替换')
 let raw:unknown;try{raw=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(buffer))}catch{throw new Error('行情分块无法解析')}
 if(!raw||typeof raw!=='object'||!('bars'in raw)||!Array.isArray(raw.bars)||raw.bars.length!==chunk.count)throw new Error('行情分块数量不符')
 const bars=raw.bars as Bar[]
 for(let i=0;i<bars.length;i++){const b=bars[i];if(!b||![b.time,b.open,b.high,b.low,b.close,b.volume].every(Number.isFinite)||!Number.isInteger(b.time)||b.open<=0||b.high<=0||b.low<=0||b.close<=0||b.volume<0||b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close)||(i>0&&b.time<=bars[i-1].time))throw new Error('行情分块包含缺失、无效或乱序的K线')}
 if(bars[0].time!==chunk.start||bars.at(-1)!.time!==chunk.end)throw new Error('行情分块覆盖范围不符');return bars
}
export async function loadMarket(manifest:MarketManifest,store:ComputeStore,signal?:AbortSignal):Promise<MarketInput>{
 const bars:Bar[]=[]
 for(const chunk of manifest.chunks){if(signal?.aborted)throw signal.reason??new DOMException('请求已取消','AbortError');let bytes=await store.get<ArrayBuffer>('chunks',chunk.sha256)
  if(bytes){try{bars.push(...await decodeChunk(bytes,chunk));continue}catch(error){await store.delete('chunks',chunk.sha256);throw error}}
  const url=new URL(chunk.url,globalThis.location?.origin??'http://localhost');if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error('行情下载地址无效')
  const response=await fetch(url,{credentials:'omit',signal});if(!response.ok)throw new Error(`行情分块下载失败（HTTP ${response.status}）`);bytes=await response.arrayBuffer();const decoded=await decodeChunk(bytes,chunk);await store.put('chunks',chunk.sha256,bytes);bars.push(...decoded)
 }
 if(bars.length!==manifest.count)throw new Error('行情数据集不完整')
 return {asset:manifest.asset,bars,source:manifest.source,source_note:manifest.source_note,interval:manifest.interval,adjustment:manifest.adjustment,fetched_at:manifest.fetched_at,last_bar_time:manifest.end,is_stale:manifest.is_stale}
}
