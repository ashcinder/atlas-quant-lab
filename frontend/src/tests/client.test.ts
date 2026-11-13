import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { idbHarness } from './idb-harness'
import type { WorkerInput, WorkerOutput } from '../compute/worker'
const mocks=vi.hoisted(()=>({request:vi.fn(),manifest:vi.fn(),load:vi.fn(),dataset:vi.fn()}))
vi.mock('../request',()=>({request:mocks.request}))
vi.mock('../compute/market',()=>({fetchManifest:mocks.manifest,loadMarket:mocks.load,loadChartPage:mocks.load,fetchDatasetManifest:mocks.dataset}))
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

it('keeps the finished backtest and reopens local history when report saving returns HTTP 502',async()=>{
 const original=mocks.request.getMockImplementation()!
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>{
  if(path==='/compute/runs')throw Object.assign(new Error('服务请求失败（HTTP 502）'),{kind:'http',status:502})
  if(path==='/runs')return []
  return original(path,options)
 })
 const completed=await client.runBacktest({symbol:'T',strategy_id:'dca'})
 expect(completed.compute?.storage_status).toBe('local')
 expect(completed.equity).toEqual(result.equity)
 expect(completed.trades).toEqual(result.trades)
 expect(completed.bars).toEqual([bar])
 expect(completed.warnings.join(' ')).toContain('尚未同步')
 const history=await client.listRuns()
 expect(history).toEqual([expect.objectContaining({id:completed.run_id,status:'local'})])
 const restored=await client.getRunHydrated<import('../types').BacktestResult>(completed.run_id)
 expect(restored.equity).toEqual(completed.equity)
 expect(restored.bars).toEqual([bar])
 expect(workerInstances.filter(w=>!w.terminated)).toHaveLength(0)
 expect(mocks.request.mock.calls.filter(c=>c[0]==='/compute/runs')).toHaveLength(1)
 const otherOwner={owner_id:'b',session_scope:'s-b'};owner=otherOwner
 expect(await client.listRuns()).toEqual([])
 await expect(client.getRunHydrated(completed.run_id)).rejects.toThrow('当前用户')
})

it.each([401,403,422])('does not hide a %s rejection as a locally completed run',async(status)=>{
 const original=mocks.request.getMockImplementation()!
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>{
  if(path==='/compute/runs')throw Object.assign(new Error('denied'),{kind:'http',status})
  return original(path,options)
 })
 await expect(client.runBacktest({symbol:'T',strategy_id:'dca'})).rejects.toThrow('denied')
})

it('syncs a locally finished report after recovery without executing the strategy again',async()=>{
 const original=mocks.request.getMockImplementation()!
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>{
  if(path==='/compute/runs')throw Object.assign(new Error('502'),{kind:'http',status:502})
  if(path==='/runs')return []
  return original(path,options)
 })
 const local=await client.runBacktest({symbol:'T',strategy_id:'dca'})
 const workers=workerInstances.length
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>path==='/runs'?[]:original(path,options))
 const saved=await client.syncLocalRun(local.run_id)
 expect(saved.run_id).toBe('server-run')
 expect(saved.compute?.storage_status).toBeUndefined()
 expect(saved.warnings.join(' ')).not.toContain('尚未同步')
 expect(workerInstances).toHaveLength(workers)
 expect(await client.listRuns()).toEqual([])
 expect(h.databases.get('atlas.compute.v1:a')?.get('runs')?.has(local.run_id)).toBe(false)
})

it('keeps a local report accessible when identity and history also return temporary gateway errors',async()=>{
 const original=mocks.request.getMockImplementation()!;let unavailable=false
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>{
  if(path==='/compute/runs'){unavailable=true;throw Object.assign(new Error('502'),{kind:'http',status:502})}
  if(unavailable&&['/compute/identity','/runs'].includes(path))throw Object.assign(new Error('503'),{kind:'http',status:503})
  return original(path,options)
 })
 const local=await client.runBacktest({symbol:'T',strategy_id:'dca'})
 expect(await client.listRuns()).toEqual([expect.objectContaining({id:local.run_id})])
 expect((await client.getRunHydrated(local.run_id)).equity).toEqual(result.equity)
 await client.deleteRun(local.run_id)
 await expect(client.getRunHydrated(local.run_id)).rejects.toThrow('当前用户')
})

it('does not publish a local fallback after logout during report saving',async()=>{
 const original=mocks.request.getMockImplementation()!;let rejectSave!:(error:Error)=>void
 mocks.request.mockImplementation(async(path:string,options?:RequestInit)=>path==='/compute/runs'?new Promise((_,reject)=>{rejectSave=reject}):original(path,options))
 const pending=client.runBacktest({symbol:'T',strategy_id:'dca'}),rejected=expect(pending).rejects.toThrow()
 await vi.waitFor(()=>expect(rejectSave).toBeTypeOf('function'))
 events.dispatchEvent(new Event('trine-session-lock'))
 rejectSave(Object.assign(new Error('502'),{kind:'http',status:502}))
 await rejected
 expect(h.databases.get('atlas.compute.v1:a')?.get('runs')?.has('local_local-run')).toBe(false)
})

describe('browser facade lifecycle',()=>{
 it('returns immediate full result while server durable record keeps dataset references',async()=>{const r=await client.runBacktest({symbol:'T',strategy_id:'dca',base_currency:'CNY',api_key:'never store'});expect(r.run_id).toBe('server-run');expect(r.bars).toEqual([bar]);expect(r.indicators).toEqual(result.indicators);expect(mocks.dataset).not.toHaveBeenCalled();const sent=mocks.request.mock.calls.find(c=>c[0]==='/compute/runs');expect(JSON.parse(sent?.[1].body).request.api_key).toBeUndefined();expect(JSON.parse(sent?.[1].body).result.bars).toEqual([]);expect(JSON.parse(sent?.[1].body).result.equity).toEqual(result.equity);const database=h.databases.get('atlas.compute.v1:a')!;expect((database.get('runs')!.get('server-run') as {result:{bars:unknown[]}}).result.bars).toEqual([])})
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
  // Chart paging may reach outside coverage; strict coverage remains a backtest requirement.
  await expect(client.runBacktest({symbol:'T',asset_class:'equity',interval:'1d',adjustment:'raw',start:'2025-02-28T00:00:00Z'})).rejects.toThrow('开始日期')
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
