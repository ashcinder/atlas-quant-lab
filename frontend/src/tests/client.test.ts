import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { idbHarness } from './idb-harness'
import type { WorkerInput, WorkerOutput } from '../compute/worker'
const mocks=vi.hoisted(()=>({request:vi.fn(),manifest:vi.fn(),load:vi.fn(),dataset:vi.fn()}))
vi.mock('../request',()=>({request:mocks.request}))
vi.mock('../compute/market',()=>({fetchManifest:mocks.manifest,loadMarket:mocks.load,fetchDatasetManifest:mocks.dataset}))
const asset={symbol:'T',name:'Test',asset_class:'crypto',exchange:'test',currency:'USD',timezone:'UTC',tags:[]},bar={time:1700000000,open:100,high:102,low:99,close:101,volume:10}
const result={run_id:'local-run',created_at:'2026-11-05T00:00:00Z',asset,interval:'1d',strategy:{},data_source:'fixture',source_note:null,bars:[bar],indicators:{rsi14:[{time:bar.time,value:50}]},trades:[],equity:[{time:bar.time,equity:100,benchmark:100,drawdown:0,exposure:0}],metrics:{},regime_metrics:{},warnings:[]}
let owner={owner_id:'a',session_scope:'s-a'},holdWorker=false,workerInstances:MockWorker[]=[]
class MockWorker {onmessage:((event:MessageEvent<WorkerOutput>)=>void)|null=null;onerror:((event:Event)=>void)|null=null;terminated=false;constructor(){workerInstances.push(this)}terminate(){this.terminated=true}postMessage(m:WorkerInput){if(m.type!=='start'||holdWorker)return;setTimeout(()=>{if(!this.terminated)this.onmessage?.({data:{type:'complete',id:m.id,result:m.task.kind==='indicators'?result.indicators:structuredClone(result)}} as unknown as MessageEvent<WorkerOutput>)},0)}}
let client:typeof import('../compute/client'),h:ReturnType<typeof idbHarness>,events:EventTarget
beforeEach(async()=>{
 vi.resetModules();vi.clearAllMocks();owner={owner_id:'a',session_scope:'s-a'};holdWorker=false;workerInstances=[];h=idbHarness();events=new EventTarget();vi.stubGlobal('window',events);vi.stubGlobal('Worker',MockWorker);vi.stubGlobal('indexedDB',h.indexedDB);const local=new Map<string,string>();vi.stubGlobal('sessionStorage',{getItem:(k:string)=>local.get(k)??null,setItem:(k:string,v:string)=>local.set(k,v)})
 const manifest={dataset_id:'data',asset,interval:'1d',adjustment:'raw',source:'fixture',source_note:null,fetched_at:bar.time,is_stale:false,start:bar.time,end:bar.time,count:1,chunks:[]}
 mocks.manifest.mockResolvedValue(manifest);mocks.load.mockResolvedValue({asset,bars:[bar],source:'fixture',interval:'1d'});mocks.dataset.mockResolvedValue(manifest)
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>{if(path==='/compute/identity')return {...owner};if(path.startsWith('/compute/capabilities'))return {execution_location:'browser',available:true,strategy_version:null};if(path==='/compute/runs'){const body=JSON.parse(options?.body as string);return {...body.result,run_id:'server-run',bars:[],indicators:{},compute:{dataset_ids:['data']}}}if(path.startsWith('/runs/'))return {...result,bars:[],indicators:{},compute:{dataset_ids:['data']}};throw new Error(`unexpected ${path}`)})
 client=await import('../compute/client')
})
afterEach(()=>{client?.cancelAllComputations();vi.unstubAllGlobals()})
describe('browser facade lifecycle',()=>{
 it('returns immediate full result while server durable record keeps dataset references',async()=>{const r=await client.runBacktest({symbol:'T',strategy_id:'dca',base_currency:'CNY',api_key:'never store'});expect(r.run_id).toBe('server-run');expect(r.bars).toEqual([bar]);expect(r.indicators).toEqual(result.indicators);expect(mocks.dataset).not.toHaveBeenCalled();const sent=mocks.request.mock.calls.find(c=>c[0]==='/compute/runs');expect(JSON.parse(sent?.[1].body).request.api_key).toBeUndefined();const database=h.databases.get('atlas.compute.v1:a')!;expect((database.get('runs')!.get('server-run') as {result:{bars:unknown[]}}).result.bars).toEqual([])})
 it('hydrates only the saved run time window using nested compute dataset refs',async()=>{mocks.load.mockResolvedValue({asset,bars:[{...bar,time:bar.time-86400},bar,{...bar,time:bar.time+86400}],source:'fixture'});const r=await client.getRunHydrated<import('../types').BacktestResult>('server-run');expect(r.bars).toEqual([bar]);expect(mocks.dataset).toHaveBeenCalledWith('data',expect.anything())})
 it('terminates a running worker when auth emits its existing session lock event',async()=>{holdWorker=true;const running=client.runBacktest({symbol:'T',strategy_id:'dca'});const rejected=expect(running).rejects.toThrow('取消');await vi.waitFor(()=>expect(workerInstances.length).toBe(1));events.dispatchEvent(new Event('trine-session-lock'));await rejected;expect(workerInstances[0].terminated).toBe(true);expect(mocks.request.mock.calls.some(c=>c[0]==='/compute/runs')).toBe(false)})
 it('refuses cross-session results and isolates the next user database',async()=>{const captured=await client.getComputeIdentity();owner={owner_id:'b',session_scope:'s-b'};await expect(client.assertComputeIdentity(captured)).rejects.toThrow('会话已改变');await client.runBacktest({symbol:'T',strategy_id:'dca'});expect(h.databases.has('atlas.compute.v1:b')).toBe(true);expect(h.databases.get('atlas.compute.v1:b')?.get('runs')?.has('server-run')).toBe(true)})
 it('fails unsupported browser capability without invoking legacy backtest APIs',async()=>{vi.stubGlobal('Worker',undefined);await expect(client.runBacktest({symbol:'T',strategy_id:'dca'})).rejects.toThrow('Web Worker');expect(mocks.request.mock.calls.some(c=>c[0]==='/backtests')).toBe(false)})
})

describe('published session coverage',()=>{
 it('accepts weekend boundaries from the published query without inventing bars',async()=>{
  const first=Date.parse('2025-03-03T04:00:00Z')/1000,last=Date.parse('2025-03-07T04:00:00Z')/1000
  mocks.manifest.mockResolvedValue({dataset_id:'data',asset:{...asset,asset_class:'equity'},interval:'1d',coverage:{start:Date.parse('2025-03-01T00:00:00Z')/1000,end:Date.parse('2025-03-09T00:00:00Z')/1000},start:first,end:last})
  mocks.load.mockResolvedValue({asset,bars:[{...bar,time:first},{...bar,time:last}],source:'fixture'})
  const result=await client.getMarket('T','equity','1d','auto','raw',{start:'2025-03-01T00:00:00Z',end:'2025-03-09T00:00:00Z'})
  expect(result.bars).toHaveLength(2)
  await expect(client.getMarket('T','equity','1d','auto','raw',{start:'2025-02-28T00:00:00Z'})).rejects.toThrow('开始日期')
 })
 it('labels persist=false reports and does not store server-owned proof claims in uploads',async()=>{
  const result=await client.runBacktest({symbol:'T',strategy_id:'dca',persist:false})
  expect(result.compute).toMatchObject({execution_location:'browser',proof_status:'unverified'})
  expect(mocks.request.mock.calls.some(call=>call[0]==='/compute/runs')).toBe(false)
 })
})

it('restores only this tabs latest research and preserves account isolation',async()=>{
 await client.runBacktest({symbol:'T',strategy_id:'dca',persist:false})
 const db=h.databases.get('atlas.compute.v1:a')!,scope=(sessionStorage as Storage).getItem('atlas.compute.tab')!
 const job={id:'browser_old',status:'completed',message:'Done',created_at:'2026-01-01',updated_at:'2026-01-01',progress:1,result:null,error:null,page_scope:scope,context:{project_id:'',symbol:'T',interval:'1d',session_scope:owner.session_scope}}
 db.get('jobs')!.set(job.id,job);db.get('jobs')!.set('browser_other',{...job,id:'browser_other',page_scope:'another-tab',created_at:'2026-12-01'})
 expect((await client.getLatestResearchJob())?.id).toBe('browser_old')
 owner={owner_id:'b',session_scope:'s-b'};expect(await client.getLatestResearchJob()).toBeNull()
})

it('aborts only the requested backtest Worker without saving or cancelling another task',async()=>{
 holdWorker=true;const controller=new AbortController();const pending=client.runBacktest({symbol:'T',strategy_id:'dca',persist:false},controller.signal);const rejected=expect(pending).rejects.toThrow('取消')
 await vi.waitFor(()=>expect(workerInstances).toHaveLength(1));controller.abort();await rejected;expect(workerInstances[0].terminated).toBe(true);expect(mocks.request.mock.calls.some(c=>c[0]==='/compute/runs')).toBe(false)
})
it('rejects a copied tab scope and refuses reading or cancelling another tabs job',async()=>{
 const claimed=new Set<string>();vi.stubGlobal('navigator',{locks:{request:async(name:string,options:unknown,callback:(lock:object|null)=>Promise<void>)=>{void options;if(claimed.has(name))return callback(null);claimed.add(name);try{await callback({name})}finally{claimed.delete(name)}}}})
 holdWorker=true;const controller=new AbortController();const pending=client.runBacktest({symbol:'T',strategy_id:'dca',persist:false},controller.signal);const finished=pending.catch(()=>undefined);await vi.waitFor(()=>expect(workerInstances).toHaveLength(1))
 const scopeA=sessionStorage.getItem('atlas.compute.tab')!,db=h.databases.get('atlas.compute.v1:a')!;const foreign={id:'browser_foreign',status:'running',message:'Active in original tab',created_at:'2026-01-01',updated_at:'2026-01-01',progress:0,result:null,error:null,page_scope:scopeA,context:{project_id:'',symbol:'T',interval:'1d',session_scope:owner.session_scope}};db.get('jobs')!.set(foreign.id,foreign)
 const copied=new Map([['atlas.compute.tab',scopeA]]);vi.stubGlobal('sessionStorage',{getItem:(k:string)=>copied.get(k)??null,setItem:(k:string,v:string)=>copied.set(k,v),removeItem:(k:string)=>copied.delete(k)})
 vi.resetModules();const other=await import('../compute/client');expect(await other.getLatestResearchJob()).toBeNull();expect(sessionStorage.getItem('atlas.compute.tab')).not.toBe(scopeA);expect((db.get('jobs')!.get(foreign.id) as {status:string}).status).toBe('running')
 await expect(other.getResearchJob(foreign.id)).rejects.toThrow('当前用户');await expect(other.cancelResearchJob(foreign.id)).rejects.toThrow('当前用户');expect((db.get('jobs')!.get(foreign.id) as {status:string}).status).toBe('running');controller.abort();await finished;events.dispatchEvent(new Event('trine-session-lock'))
})
