import type { Adjustment, Asset, Bar, DataSource, Interval } from '../types'
import type { MarketInput } from './model'
import type { ComputeStore } from './persistence'
import { request } from '../request'
export interface MarketChunk {sha256:string;count:number;start:number;end:number;url:string}
export interface MarketManifest {status:'ready';schema:'atlas.market/v1';dataset_id:string;asset:Asset;interval:Interval;adjustment:Adjustment;source:string;source_note:string|null;fetched_at:number;is_stale:boolean;start:number;end:number;count:number;chunks:MarketChunk[];coverage?:{start:number;end:number;basis:string};conversions?:Record<string,string>}
export interface MarketQuery {symbol:string;asset_class:string;interval:Interval;adjustment:Adjustment;data_source:DataSource;start?:string;end?:string}
export class MarketUnavailableError extends Error {}
export class MarketChunkUnavailableError extends MarketUnavailableError {
  constructor(message: string) { super(message); this.name = 'MarketChunkUnavailableError' }
}
export class MarketPreparingError extends MarketUnavailableError {constructor(message='历史数据尚未发布，请等待数据准备完成后重试'){super(message);this.name='MarketPreparingError'}}
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
 const manifest=validateManifest(raw);await store.put('manifests',manifest.dataset_id,manifest).catch(()=>undefined);await store.put('manifests',`query:${params}`,manifest).catch(()=>undefined);return manifest
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
async function loadChunk(chunk:MarketChunk,store:ComputeStore,signal?:AbortSignal):Promise<Bar[]>{
  if(signal?.aborted)throw signal.reason??new DOMException('请求已取消','AbortError')
  let bytes=await store.get<ArrayBuffer>('chunks',chunk.sha256).catch(()=>undefined)
  if(bytes){try{return await decodeChunk(bytes,chunk)}catch{await store.delete('chunks',chunk.sha256).catch(()=>undefined)}}
  const url=new URL(chunk.url,globalThis.location?.origin??'http://localhost');if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error('行情下载地址无效')
  let response: Response
  try {
    response = await fetch(url, { credentials: 'omit', signal })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new MarketChunkUnavailableError('无法连接行情分块服务')
  }
  if (!response.ok) {
    const message = `行情分块下载失败（HTTP ${response.status}）`
    if (response.status === 404 || response.status === 429 || response.status >= 500) {
      throw new MarketChunkUnavailableError(message)
    }
    throw new Error(message)
  }
  bytes = await response.arrayBuffer()
  const decoded = await decodeChunk(bytes, chunk)
  await store.put('chunks', chunk.sha256, bytes).catch(() => undefined)
  return decoded
}

export async function loadMarket(manifest:MarketManifest,store:ComputeStore,signal?:AbortSignal,range?:{start?:number;end?:number}):Promise<MarketInput>{
 const bars:Bar[]=[]
 const chunks=manifest.chunks.filter(chunk=>chunk.end>=(range?.start??-Infinity)&&chunk.start<=(range?.end??Infinity))
 if(!chunks.length)throw new MarketUnavailableError('请求区间没有已发布行情')
 for(let i=0;i<chunks.length;i+=8){
  const batch=await Promise.all(chunks.slice(i,i+8).map(chunk=>loadChunk(chunk,store,signal)))
  for(const part of batch) for(const bar of part) bars.push(bar)
 }
 if(bars.length!==chunks.reduce((count,chunk)=>count+chunk.count,0))throw new Error('行情数据集不完整')
 return {asset:manifest.asset,bars,source:manifest.source,source_note:manifest.source_note,interval:manifest.interval,adjustment:manifest.adjustment,fetched_at:manifest.fetched_at,last_bar_time:bars.at(-1)!.time,is_stale:manifest.is_stale}
}

// Chart pages are independent from backtest coverage: reaching the beginning
// returns an empty page, while backtests still require the entire requested range.
export async function loadChartPage(
  manifest: MarketManifest, store: ComputeStore, signal?: AbortSignal,
  range: { start?: number; end?: number; fromStart?: boolean } = {}, limit = 3000,
): Promise<MarketInput> {
  const start = range.start ?? -Infinity
  const end = range.end ?? Infinity
  const parts = manifest.chunks.filter(part => part.end >= start && part.start <= end)
  if (!range.fromStart) parts.reverse()
  let bars: Bar[] = []
  for (const part of parts) {
    const data = await loadMarket({ ...manifest, chunks: [part] }, store, signal)
    const page = data.bars.filter(bar => bar.time >= start && bar.time <= end
      && (manifest.source !== 'hf-unverified' || bar.volume > 0))
    bars = range.fromStart ? bars.concat(page) : page.concat(bars)
    if (bars.length >= limit) break
  }
  return {
    asset: manifest.asset, bars: range.fromStart ? bars.slice(0, limit) : bars.slice(-limit),
    source: manifest.source, source_note: manifest.source_note, interval: manifest.interval,
    adjustment: manifest.adjustment, fetched_at: manifest.fetched_at, is_stale: manifest.is_stale,
  }
}
