import { expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'
import { loadChartPage, sha256, type MarketManifest } from './market'
import { chartHistorySource } from '../marketSupport'
import type { ComputeStore } from './persistence'
it('resolves history providers to the published query source', () => {
 expect(chartHistorySource('auto','hf-ohlcv')).toBe('huggingface')
 expect(chartHistorySource('auto','hf-unverified')).toBe('huggingface')
 expect(chartHistorySource('auto','baostock-disputed')).toBe('baostock')
 expect(chartHistorySource('auto','sina')).toBe('auto')
})
it('repairs a corrupt cache from the verified public chunk even when cache storage is full', async () => {
 vi.stubGlobal('crypto',webcrypto)
 const bars=[{time:1000,open:10,high:11,low:9,close:10,volume:0}]
 const bytes=new TextEncoder().encode(JSON.stringify({bars})).buffer
 const chunk={sha256:await sha256(bytes),count:1,start:1000,end:1000,url:'/chunk.json'}
 const store={get:vi.fn(async()=>new ArrayBuffer(2)),delete:vi.fn(async()=>{}),put:vi.fn(async()=>{throw new Error('quota')})} as unknown as ComputeStore
 const fetch=vi.fn(async()=>new Response(bytes));vi.stubGlobal('fetch',fetch)
 try {
  const data=await loadChartPage({asset:{symbol:'300750.SZ'},chunks:[chunk],source:'hf-ohlcv',interval:'1m',adjustment:'raw'} as MarketManifest,store)
  expect(data.bars).toEqual(bars)
  expect(fetch).toHaveBeenCalledOnce()
 } finally {vi.unstubAllGlobals()}
})
it('loads recent and older pages, then stops at the true beginning', async () => {
 vi.stubGlobal('crypto',webcrypto)
 const cache=new Map<string,ArrayBuffer>(),chunks=[]
 for(let part=0;part<4;part++){
  const bars=Array.from({length:100},(_,i)=>({time:1000+part*100000+i,open:10,high:11,low:9,close:10,volume:100}))
  const bytes=new TextEncoder().encode(JSON.stringify({bars})).buffer,hash=await sha256(bytes)
  cache.set(hash,bytes);chunks.push({sha256:hash,count:100,start:bars[0].time,end:bars.at(-1)!.time,url:'/unused'})
 }
 const store={get:vi.fn(async (_:string,key:string)=>cache.get(key))} as unknown as ComputeStore
 const manifest={asset:{symbol:'300750.SZ'},chunks,source:'hf-unverified',interval:'1m',adjustment:'raw'} as MarketManifest
 const recent=await loadChartPage(manifest,store,undefined,{},100)
 expect(recent.bars.map(b=>b.time)).toEqual(Array.from({length:100},(_,i)=>301000+i))
 const older=await loadChartPage(manifest,store,undefined,{end:recent.bars[0].time-1},100)
 expect(older.bars[0].time).toBe(201000)
 const oldest=await loadChartPage(manifest,store,undefined,{end:1099},100)
 expect(oldest.bars[0].time).toBe(1000)
 expect((await loadChartPage(manifest,store,undefined,{end:999},100)).bars).toEqual([])
 vi.unstubAllGlobals()
})
it('skips zero-volume snapshot bars and continues into the previous chunk', async () => {
 vi.stubGlobal('crypto',webcrypto)
 const cache=new Map<string,ArrayBuffer>(),chunks=[]
 for(let part=0;part<3;part++){
  const bars=Array.from({length:4},(_,i)=>({time:1000+part*100+i,open:10,high:10,low:10,close:10,volume:part===1?0:10}))
  const bytes=new TextEncoder().encode(JSON.stringify({bars})).buffer,hash=await sha256(bytes)
  cache.set(hash,bytes);chunks.push({sha256:hash,count:4,start:bars[0].time,end:bars.at(-1)!.time,url:'/unused'})
 }
 const store={get:vi.fn(async (_:string,key:string)=>cache.get(key))} as unknown as ComputeStore
 const manifest={asset:{symbol:'688012.SS'},chunks,source:'hf-unverified',interval:'5m',adjustment:'raw'} as MarketManifest
 const result=await loadChartPage(manifest,store,undefined,{},6)
 expect(result.bars.map(b=>b.time)).toEqual([1002,1003,1200,1201,1202,1203])
 const earlier=await loadChartPage(manifest,store,undefined,{end:1103},4)
 expect(earlier.bars.map(b=>b.time)).toEqual([1000,1001,1002,1003])
 vi.unstubAllGlobals()
})
