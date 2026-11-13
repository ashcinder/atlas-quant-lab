import type { Adjustment, BacktestResult, DataSource, Interval, MarketData, PortfolioResult, ResearchJob, ResearchResult, StrategyRun, RunSummary } from '../types'
import { request } from '../request'
import { ComputeStore, LOCAL_SAVE_NOTICE, type ComputeIdentity, type StoredTask, type StoredRun, type StoredResult } from './persistence'
import { fetchManifest, fetchDatasetManifest, loadMarket, loadChartPage, type MarketManifest, type MarketQuery } from './market'
import { chartHistorySource } from '../marketSupport'
import type { MarketInput } from './model'
import type { WorkerTask, WorkerInput, WorkerOutput, WorkerResult } from './worker'
export const ENGINE_VERSION='browser-ts/v1'
const LOCAL_HISTORY_INDEX='@local-history/v1'
// A small index in the same owner-scoped store avoids materializing every
// full equity curve when opening history. No database-version migration.
function temporaryServiceFailure(error:unknown):boolean{
 if(!error||typeof error!=='object')return false
 const e=error as {kind?:string;status?:number}
 return ['network','timeout'].includes(e.kind??'')||(e.kind==='http'&&[502,503,504].includes(e.status??0))
}
async function localHistory(storage:ComputeStore):Promise<RunSummary[]>{return await storage.get<RunSummary[]>('runs',LOCAL_HISTORY_INDEX)??[]}
async function removeLocalRun(storage:ComputeStore,id:string):Promise<void>{
 await storage.update<RunSummary[]>('runs',LOCAL_HISTORY_INDEX,rows=>(rows??[]).filter(r=>r.id!==id))
 await storage.delete('runs',id)
}
interface Capabilities {execution_location:'browser'|'server_private';available:boolean;strategy_version:string|null;strategy?:{strategy_id:string;params?:Record<string,unknown>;custom_strategy?:unknown;python_program?:unknown};message?:string;unavailable_reason?:string}
interface ActiveTask {worker:Worker;reject:(reason:Error)=>void;controller:AbortController}
const active=new Map<string,ActiveTask>(),controllers=new Set<AbortController>(),jobControllers=new Map<string,AbortController>()
let identity:ComputeIdentity|null=null,store:ComputeStore|null=null,initializing:Promise<ComputeStore>|null=null,generation=0
let pageScope:string|null=null,scopeReady:Promise<void>|null=null,releaseScope:(()=>void)|null=null
async function ensurePageScope():Promise<void>{
 if(scopeReady)return scopeReady
 scopeReady=(async()=>{
  if(typeof navigator==='undefined'||!navigator.locks){pageScope=crypto.randomUUID();sessionStorage.setItem('atlas.compute.tab',pageScope);return}
  const claim=async(candidate:string):Promise<void>=>new Promise((resolve,reject)=>{
   void navigator.locks.request('atlas.compute.tab:'+candidate,{ifAvailable:true},async lock=>{
    if(!lock){pageScope=crypto.randomUUID();sessionStorage.setItem('atlas.compute.tab',pageScope);await claim(pageScope);resolve();return}
    pageScope=candidate;resolve();await new Promise<void>(done=>{releaseScope=done})
   }).catch(reject)
  })
  await claim(tabScope())
 })();return scopeReady
}
function tabScope():string{if(pageScope)return pageScope;try{pageScope=sessionStorage.getItem('atlas.compute.tab');if(!pageScope){pageScope=crypto.randomUUID();sessionStorage.setItem('atlas.compute.tab',pageScope)}}catch{throw new Error('浏览器会话存储不可用，无法安全恢复计算任务')}return pageScope}
function sameIdentity(a:ComputeIdentity,b:ComputeIdentity):boolean{return a.owner_id===b.owner_id&&a.session_scope===b.session_scope}
export function cancelAllComputations():void{
 generation++
 for(const entry of active.values()){entry.controller.abort();entry.worker.terminate();entry.reject(new Error('计算已取消：页面或登录状态已改变'))}active.clear()
 for(const controller of controllers)controller.abort();controllers.clear();jobControllers.clear()
}
function invalidateSession():void{cancelAllComputations();releaseScope?.();releaseScope=null;scopeReady=null;pageScope=null;try{sessionStorage.removeItem?.('atlas.compute.tab')}catch{/* storage may be disabled */};identity=null;const previous=store;store=null;initializing=null;if(previous)void previous.close().catch(()=>undefined)}
if(typeof window!=='undefined'){window.addEventListener('trine-session-lock',invalidateSession);window.addEventListener('atlas-session-expired',invalidateSession);window.addEventListener('pagehide',cancelAllComputations)}
export async function getComputeIdentity():Promise<ComputeIdentity>{
 const started=generation;await ensurePageScope();let current:ComputeIdentity
 try{current=await request<ComputeIdentity>('/compute/identity',{cache:'no-store'})}
 catch(error){if(started!==generation)throw new Error('登录状态已改变，请重新开始计算',{cause:error});if(temporaryServiceFailure(error)&&identity)return {...identity};throw error}
 if(started!==generation)throw new Error('登录状态已改变，请重新开始计算')
 if(!current.owner_id||!current.session_scope)throw new Error('计算需要已登录的用户身份')
 if(identity&&!sameIdentity(identity,current)){invalidateSession();await ensurePageScope()}
 identity={...current};return current
}
export async function assertComputeIdentity(captured:ComputeIdentity):Promise<void>{const current=await getComputeIdentity();if(!sameIdentity(current,captured))throw new Error('登录用户或会话已改变，计算结果未保存')}
async function computeStore(captured:ComputeIdentity):Promise<ComputeStore>{
 if(!identity||!sameIdentity(identity,captured))throw new Error('登录状态已改变')
 if(store&&sameIdentity(store.identity,captured))return store
 if(!initializing){const started=generation;initializing=(async()=>{const next=new ComputeStore(captured);await next.recoverInterrupted(tabScope());if(started!==generation||!identity||!sameIdentity(identity,captured)){await next.close();throw new Error('登录状态已改变')}store=next;return next})().finally(()=>{initializing=null})}
 return initializing
}
function support():void{if(typeof Worker==='undefined')throw new Error('当前浏览器不支持 Web Worker，无法执行浏览器计算');if(typeof indexedDB==='undefined')throw new Error('当前浏览器不支持 IndexedDB，无法保存计算任务')}
async function capabilities(releaseId?:string,purpose:'backtest'|'runtime'='backtest'):Promise<Capabilities>{const result=await request<Capabilities>(`/compute/capabilities${releaseId?`?release_id=${encodeURIComponent(releaseId)}${purpose==='runtime'?'&purpose=runtime':''}`:''}`);if(!result.available)throw new Error(result.unavailable_reason??result.message??'当前策略版本不可执行');return result}
const ALLOWED_FIELDS=['portable_python','portable_plan','strategy_name','execution_model','symbol','asset_class','interval','start','end','adjustment','base_currency','data_source','strategy_id','custom_strategy','python_source','python_program','params','initial_capital','commission_rate','slippage_rate','spread_rate','max_position','max_participation_rate','stop_loss','take_profit','execution_pipeline','assets','rebalance','cash_buffer','max_asset_weight','volatility_target','experiments','objective','holdout_ratio','walk_forward','release_id','persist']
export function computePayload(payload:Record<string,unknown>):Record<string,unknown>{return structuredClone(Object.fromEntries(ALLOWED_FIELDS.filter(key=>payload[key]!==undefined).map(key=>[key,payload[key]])))}
async function resolvedPayload(payload:Record<string,unknown>,cap:Capabilities):Promise<Record<string,unknown>>{
 const resolved=computePayload(payload)
 if(cap.strategy)Object.assign(resolved,{strategy_id:cap.strategy.strategy_id,params:cap.strategy.params??{},custom_strategy:cap.strategy.custom_strategy??null,python_program:cap.strategy.python_program??undefined,python_source:undefined})
 if(resolved.python_source!=null&&resolved.python_program==null){const compiled=await request<{python_program:unknown}>('/compute/compile',{method:'POST',body:JSON.stringify({source:resolved.python_source})});resolved.python_program=compiled.python_program}
 return resolved
}
function queryFor(payload:Record<string,unknown>):MarketQuery{return {symbol:String(payload.symbol??'BTC-USD'),asset_class:String(payload.asset_class??'crypto'),interval:(payload.interval??'1d') as Interval,adjustment:(payload.adjustment??'auto') as Adjustment,data_source:(payload.data_source??'auto') as DataSource,...(payload.start?{start:String(payload.start)}:{}),...(payload.end?{end:String(payload.end)}:{})}}
function checkCoverage(manifest:MarketManifest,query:MarketQuery):void{
 const coverage=manifest.coverage??{start:manifest.start,end:manifest.end}
 if(query.start){const from=Date.parse(query.start)/1000;if(!Number.isFinite(from))throw new Error('回测开始时间无效');if(coverage.start>from)throw new Error('已发布行情未完整覆盖请求的开始日期，请调整日期或等待数据发布')}
 if(query.end){const to=Date.parse(query.end)/1000;if(!Number.isFinite(to))throw new Error('回测结束时间无效');if(coverage.end<Math.min(to,Date.now()/1000))throw new Error('已发布行情未完整覆盖请求的结束日期，请调整日期或等待数据发布')}
}
async function marketFor(payload:Record<string,unknown>,storage:ComputeStore,signal?:AbortSignal,convertBase=false):Promise<{market:MarketInput;manifest:MarketManifest}>{
 const query=queryFor(payload);let manifest=await fetchManifest(query,storage,signal);checkCoverage(manifest,query)
 const base=payload.base_currency
 if(convertBase&&typeof base==='string'&&base!==manifest.asset.currency){const converted=manifest.conversions?.[base];if(!converted)throw new Error(`缺少 ${manifest.asset.currency}→${base} 的已发布历史汇率数据集`);manifest=await fetchDatasetManifest(converted,storage,signal);if(manifest.asset.currency!==base)throw new Error('换汇数据集计价币种不符');checkCoverage(manifest,query)}
 // An immutable dataset may include broader coverage than a research window.
 const start=query.start?Date.parse(query.start)/1000:-Infinity,end=query.end?Date.parse(query.end)/1000:Infinity
 const market=await loadMarket(manifest,storage,signal,query.start||query.end?{start,end}:undefined)
 market.bars=market.bars.filter(bar=>bar.time>=start&&bar.time<=end)
 if(!market.bars.length)throw new Error('请求区间没有已发布行情')
 return {market,manifest}
}
function workerCompute<T extends WorkerResult>(task:WorkerTask,captured:ComputeIdentity,progress?:(value:number,message:string)=>void,signal?:AbortSignal,id:string=crypto.randomUUID()):Promise<T>{
 support();const started=generation
 return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(signal.reason??new Error('计算已取消'));return}
  let worker:Worker;try{worker=new Worker(new URL('./worker.ts',import.meta.url),{type:'module'})}catch{reject(new Error('浏览器无法启动计算 Worker'));return}
  const controller=new AbortController()
  const cleanup=()=>{active.delete(id);worker.terminate();controller.abort();signal?.removeEventListener('abort',abort)}
  const fail=(error:Error)=>{cleanup();reject(error)}
  const abort=()=>fail(new Error('计算已取消'))
  active.set(id,{worker,reject:fail,controller});signal?.addEventListener('abort',abort,{once:true})
  worker.onerror=()=>fail(new Error('浏览器计算 Worker 启动或运行失败，请检查浏览器能力与应用版本'))
  worker.onmessage=(event:MessageEvent<WorkerOutput>)=>{const message=event.data;if(message.id!==id)return;if(started!==generation||!identity||!sameIdentity(identity,captured)){fail(new Error('登录状态已改变，计算已停止'));return}
   if(message.type==='progress'){progress?.(message.progress,message.message);return}
   if(message.type==='error'){fail(new Error(message.message));return}
   if(message.type==='ai_review'){void(async()=>{try{await assertComputeIdentity(captured);const result=await request<{scale:number;status:string}>('/compute/ai-review',{method:'POST',body:JSON.stringify(message.input),signal:controller.signal},message.input.timeout_ms+2000);if(active.has(id))worker.postMessage({type:'ai_result',id,rpcId:message.rpcId,result} satisfies WorkerInput)}catch(error){if(active.has(id))worker.postMessage({type:'ai_result',id,rpcId:message.rpcId,error:error instanceof Error?error.message:'AI 审核失败'} satisfies WorkerInput)}})();return}
   cleanup();resolve(message.result as T)
  }
  worker.postMessage({type:'start',id,task} satisfies WorkerInput)
 })
}
async function savedResult<T extends StoredResult>(mode:StoredRun['mode'],payload:Record<string,unknown>,result:T,datasets:string[],version:string|null,captured:ComputeIdentity,storage:ComputeStore,signal?:AbortSignal):Promise<T>{
 if(signal?.aborted)throw new Error('计算已取消');await assertComputeIdentity(captured)
 const localId='run_id'in result?String(result.run_id):String(result.job_id)
 const localResult='bars'in result?{...result,bars:[],indicators:{}}:result
 await storage.put('runs',localId,{id:localId,mode,result:localResult,dataset_ids:datasets,strategy_version:version,created_at:result.created_at} satisfies StoredRun)
 const report=Object.fromEntries(Object.entries(result).filter(([key])=>key!=='compute'))
 if(mode==='single')report.bars=[] // Rehydrate immutable OHLCV by dataset_id.
 if(Array.isArray(report.warnings))report.warnings=report.warnings.filter(w=>w!==LOCAL_SAVE_NOTICE)
 let saved:T
 try{saved=await request<T>('/compute/runs',{method:'POST',signal,body:JSON.stringify({mode,request:payload,result:report,dataset_ids:datasets,engine_version:ENGINE_VERSION,strategy_version:version})})}
 catch(error){
  if(signal?.aborted||mode==='research'||!temporaryServiceFailure(error))throw error
  await assertComputeIdentity(captured)
  const id=localId.startsWith('local_')?localId:`local_${localId}`
  const finished=result as BacktestResult|PortfolioResult
  const local={...finished,run_id:id,warnings:[...finished.warnings.filter(w=>w!==LOCAL_SAVE_NOTICE),LOCAL_SAVE_NOTICE],compute:{...finished.compute!,storage_status:'local' as const}}
  const compact='bars'in local?{...local,bars:[],indicators:{}}:local
  await storage.put('runs',id,{id,mode,result:compact,dataset_ids:datasets,strategy_version:version,created_at:result.created_at,sync_request:computePayload(payload)} satisfies StoredRun)
  const summary:RunSummary={id,mode:mode as 'single'|'portfolio',strategy_id:local.strategy.id,symbol:'asset'in local?local.asset.symbol:local.assets.map(a=>a.symbol).join(','),created_at:local.created_at,total_return:local.metrics.total_return??null,max_drawdown:local.metrics.max_drawdown??null,status:'local',compute:local.compute}
  await storage.update<RunSummary[]>('runs',LOCAL_HISTORY_INDEX,rows=>[summary,...(rows??[]).filter(r=>r.id!==id)])
  if(id!==localId)await storage.delete('runs',localId)
  return local as T
 }
 await assertComputeIdentity(captured)
 const id='run_id'in saved?String(saved.run_id):String(saved.job_id)
 await storage.put('runs',id,{id,mode,result:saved,dataset_ids:datasets,strategy_version:version,created_at:saved.created_at} satisfies StoredRun)
 if(id!==localId){if(localId.startsWith('local_'))await removeLocalRun(storage,localId);else await storage.delete('runs',localId)}
 return ('bars'in result&&'bars'in saved?{...saved,bars:result.bars,indicators:result.indicators}:saved) as T
}
async function withTask<T extends StoredResult>(mode:StoredTask['mode'],payload:Record<string,unknown>,captured:ComputeIdentity,storage:ComputeStore,run:(progress:(value:number,message:string)=>void,signal:AbortSignal,recordDatasets:(ids:string[])=>void)=>Promise<T>,externalSignal?:AbortSignal):Promise<T>{
 const now=new Date().toISOString(),task:StoredTask={page_scope:tabScope(),id:crypto.randomUUID(),mode,request:computePayload(payload),dataset_ids:[],status:'running',result:null,progress:0,message:'准备计算数据',error:null,created_at:now,updated_at:now},controller=new AbortController();controllers.add(controller)
 const abort=()=>controller.abort();if(externalSignal?.aborted)abort();else externalSignal?.addEventListener('abort',abort,{once:true})
 await storage.put('tasks',task.id,task)
 let writing=Promise.resolve(),writeError:unknown=null
 const update=(value:number,message:string)=>{task.progress=value;task.message=message;task.updated_at=new Date().toISOString();const snapshot=structuredClone(task);writing=writing.then(()=>storage.put('tasks',task.id,snapshot)).catch(error=>{writeError=error;controller.abort()})}
 try{const result=await run(update,controller.signal,ids=>{task.dataset_ids=ids});await writing;if(writeError)throw writeError;if(controller.signal.aborted)throw new Error('计算已取消');await assertComputeIdentity(captured);await storage.put('tasks',task.id,{...task,status:'completed',progress:1,message:'计算完成',result:'bars'in result?{...result,bars:[],indicators:{}}:result,updated_at:new Date().toISOString()});return result}
 catch(error){await writing;await storage.put('tasks',task.id,{...task,status:controller.signal.aborted?'cancelled':'failed',message:'计算未完成',error:error instanceof Error?error.message:'浏览器计算失败',updated_at:new Date().toISOString()}).catch(()=>undefined);throw error}finally{externalSignal?.removeEventListener('abort',abort);controllers.delete(controller)}
}
export async function getMarket(symbol:string,assetClass:string,interval:Interval,source:DataSource,adjustment:Adjustment,options:{signal?:AbortSignal;refresh?:boolean;start?:string;end?:string;provider?:string}={}):Promise<MarketData>{
 support();const captured=await getComputeIdentity(),storage=await computeStore(captured)
 const manifest=await fetchManifest({symbol,asset_class:assetClass,interval,data_source:chartHistorySource(source,options.provider),adjustment},storage,options.signal)
 const market=await loadChartPage(manifest,storage,options.signal,{start:options.start?Date.parse(options.start)/1000:undefined,end:options.end?Date.parse(options.end)/1000:undefined})
 const indicators=market.bars.length?await workerCompute<MarketData['indicators']>({kind:'indicators',bars:market.bars},captured,undefined,options.signal):{}
 await assertComputeIdentity(captured)
 return {asset:market.asset,interval,adjustment:manifest.adjustment,source:market.source,source_note:manifest.source_note??null,fetched_at:manifest.fetched_at,last_bar_time:market.bars.at(-1)?.time??manifest.end,cache_hit:false,is_stale:manifest.is_stale,bars:market.bars,indicators}
}
export async function runBacktest(payload:Record<string,unknown>,externalSignal?:AbortSignal):Promise<BacktestResult>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured),cap=await capabilities(typeof payload.release_id==='string'?payload.release_id:undefined)
 return withTask('single',payload,captured,storage,async(progress,signal,recordDatasets)=>{
  const {market,manifest}=await marketFor(payload,storage,signal);recordDatasets([manifest.dataset_id])
  if(cap.execution_location==='server_private'){await assertComputeIdentity(captured);return request<BacktestResult>('/compute/private-backtests',{method:'POST',signal,body:JSON.stringify({release_id:payload.release_id,dataset_id:manifest.dataset_id,settings:computePayload(Object.fromEntries(['start','end','initial_capital','commission_rate','slippage_rate','spread_rate','max_position','max_participation_rate','stop_loss','take_profit'].filter(k=>payload[k]!==undefined).map(k=>[k,payload[k]])))})})}
  const resolved=await resolvedPayload(payload,cap)
  if(resolved.strategy_id==='python_portable'){
   const {createPortablePlan}=await import('./portablePython')
   progress(.03,'准备隔离Python运行环境与策略信号')
   resolved.portable_plan=await createPortablePlan(String(resolved.portable_python??''),market.bars,manifest.dataset_id,String(resolved.strategy_name??'Python策略'),(resolved.params??{}) as Record<string,unknown>,signal)
  }
  const result=await workerCompute<BacktestResult>({kind:'single',request:resolved,market},captured,progress,signal)
  if(!payload.start&&!payload.end)result.warnings.push('未指定历史区间，本次使用数据清单公布的覆盖范围。')
  result.compute={execution_location:'browser',proof_status:'unverified',engine_version:ENGINE_VERSION,dataset_ids:[manifest.dataset_id],strategy_version:cap.strategy_version}
  if(signal.aborted)throw new Error('计算已取消');if(payload.persist===false)return result
  return savedResult('single',resolved,result,[manifest.dataset_id],cap.strategy_version,captured,storage,signal)
 },externalSignal)
}
export async function runPortfolio(payload:Record<string,unknown>):Promise<PortfolioResult>{
 support();const captured=await getComputeIdentity(),storage=await computeStore(captured),cap=await capabilities();if(cap.execution_location!=='browser')throw new Error('组合研究仅支持浏览器策略')
 return withTask('portfolio',payload,captured,storage,async(progress,signal,recordDatasets)=>{
  if(!Array.isArray(payload.assets))throw new Error('组合缺少资产列表')
  const inputs=await Promise.all((payload.assets as Array<Record<string,unknown>>).map(asset=>marketFor({...payload,symbol:asset.symbol,asset_class:asset.asset_class??'equity'},storage,signal,true))),resolved=computePayload(payload),result=await workerCompute<PortfolioResult>({kind:'portfolio',request:resolved,markets:inputs.map(i=>i.market)},captured,progress,signal)
  recordDatasets(inputs.map(i=>i.manifest.dataset_id))
  if(!payload.start&&!payload.end)result.warnings.push('未指定历史区间，本次使用已发布数据的公共覆盖范围。')
  result.compute={execution_location:'browser',proof_status:'unverified',engine_version:ENGINE_VERSION,dataset_ids:inputs.map(i=>i.manifest.dataset_id)}
  return payload.persist===false?result:savedResult('portfolio',resolved,result,inputs.map(i=>i.manifest.dataset_id),null,captured,storage)
 })
}
export async function createResearchJob(payload:Record<string,unknown>):Promise<ResearchJob>{
 support();const captured=await getComputeIdentity(),storage=await computeStore(captured),cap=await capabilities(typeof payload.release_id==='string'?payload.release_id:undefined);if(cap.execution_location!=='browser')throw new Error('保密订阅策略不提供批量参数研究')
 const now=new Date().toISOString(),job:ResearchJob={context:{project_id:String((payload.research_context as {project_id?:string}|undefined)?.project_id??''),symbol:String(payload.symbol??''),interval:String(payload.interval??''),session_scope:captured.session_scope},id:`browser_${crypto.randomUUID()}`,status:'queued',progress:0,message:'浏览器研究排队中',result:null,error:null,created_at:now,updated_at:now},controller=new AbortController();controllers.add(controller)
 const storedTask=():StoredTask=>({...job,page_scope:tabScope(),mode:'research',request:computePayload(payload),dataset_ids:researchDatasets})
 let researchDatasets:string[]=[]
 await storage.put('jobs',job.id,{...job,page_scope:tabScope()});await storage.put('tasks',job.id,storedTask());jobControllers.set(job.id,controller);const started=generation
 void(async()=>{let writes=Promise.resolve();try{
  const {market,manifest}=await marketFor(payload,storage,controller.signal),resolved=computePayload(payload);researchDatasets=[manifest.dataset_id];job.status='running';job.message='正在浏览器研究';await storage.put('jobs',job.id,{...job,page_scope:tabScope()});await storage.put('tasks',job.id,storedTask())
  const result=await workerCompute<ResearchResult>({kind:'research',request:resolved,market,jobId:job.id},captured,(value,message)=>{job.progress=value;job.message=message;job.updated_at=new Date().toISOString();const snapshot=structuredClone(job);const taskSnapshot=storedTask();writes=writes.then(async()=>{await storage.put('jobs',job.id,{...snapshot,page_scope:tabScope()});await storage.put('tasks',job.id,taskSnapshot)}).catch(()=>controller.abort())},controller.signal,job.id)
  await writes;if(controller.signal.aborted||started!==generation)throw new Error('研究已取消或登录状态已改变')
  job.result=await savedResult('research',resolved,result,[manifest.dataset_id],cap.strategy_version,captured,storage);job.status='completed';job.progress=1;job.message='浏览器研究已完成'
 }catch(error){await writes;job.status=controller.signal.aborted?'cancelled':'failed';job.message=job.status==='cancelled'?'研究已取消':'浏览器研究失败';job.error=error instanceof Error?error.message:'浏览器研究失败'}finally{job.updated_at=new Date().toISOString();await storage.put('jobs',job.id,{...job,page_scope:tabScope()}).catch(()=>undefined);await storage.put('tasks',job.id,storedTask()).catch(()=>undefined);controllers.delete(controller);jobControllers.delete(job.id)}})()
 return structuredClone(job)
}
export async function getResearchJob(id:string,signal?:AbortSignal):Promise<ResearchJob>{if(!id.startsWith('browser_'))return request<ResearchJob>(`/research/jobs/${encodeURIComponent(id)}`,{signal});if(signal?.aborted)throw signal.reason;const captured=await getComputeIdentity(),storage=await computeStore(captured),job=await storage.get<ResearchJob&{page_scope?:string}>('jobs',id);if(!job||job.page_scope!==tabScope()||job.context?.session_scope!==captured.session_scope)throw new Error('当前用户在此浏览器没有该研究任务');return job}
export async function getLatestResearchJob(context?:{project_id:string;symbol:string;interval:string}):Promise<ResearchJob|null>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured)
 const jobs=await storage.all<ResearchJob&{page_scope?:string}>('jobs')
 return jobs.filter(job=>job.page_scope===tabScope()&&job.context?.session_scope===captured.session_scope&&(!context||(job.context.project_id===context.project_id&&job.context.symbol===context.symbol&&job.context.interval===context.interval))).sort((a,b)=>b.created_at.localeCompare(a.created_at))[0]??null
}
export async function cancelResearchJob(id:string):Promise<ResearchJob>{
 if(!id.startsWith('browser_'))return request<ResearchJob>(`/research/jobs/${encodeURIComponent(id)}`,{method:'DELETE'})
 const job=await getResearchJob(id);if(['completed','cancelled','failed'].includes(job.status))return job
 jobControllers.get(id)?.abort();const entry=active.get(id);if(entry){entry.controller.abort();entry.worker.terminate();entry.reject(new Error('研究已取消'));active.delete(id)}
 const captured=await getComputeIdentity(),storage=await computeStore(captured),next:ResearchJob={...job,status:'cancelled',message:'研究已取消',updated_at:new Date().toISOString()};await storage.put('jobs',id,{...next,page_scope:tabScope()});return next
}
export async function getRunHydrated<T extends BacktestResult|PortfolioResult>(id:string):Promise<T>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured)
 let result:T
 if(id.startsWith('local_')){
  const record=await storage.get<StoredRun>('runs',id)
  if(!record?.sync_request||record.mode==='research')throw new Error('当前用户在此浏览器没有该回测记录')
  result=record.result as T
 }else result=await request<T>(`/runs/${encodeURIComponent(id)}`)
 if('bars'in result&&result.bars.length===0&&result.compute?.dataset_ids?.length){const manifest=await fetchDatasetManifest(result.compute.dataset_ids[0],storage),from=result.equity[0]?.time??result.compute.period_start??-Infinity,to=result.equity.at(-1)?.time??result.compute.period_end??Infinity,market=await loadMarket(manifest,storage,undefined,{start:from,end:to});result.bars=market.bars.filter(b=>b.time>=from&&b.time<=to);result.indicators=await workerCompute<BacktestResult['indicators']>({kind:'indicators',bars:result.bars},captured)}
 await assertComputeIdentity(captured);return result
}

export async function listRuns():Promise<RunSummary[]>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured),local=await localHistory(storage)
 let remote:RunSummary[]
 try{remote=await request<RunSummary[]>('/runs')}
 catch(error){if(!local.length||!temporaryServiceFailure(error))throw error;remote=[]}
 await assertComputeIdentity(captured)
 return [...local,...remote].sort((a,b)=>b.created_at.localeCompare(a.created_at))
}
export async function deleteRun(id:string):Promise<void>{
 if(!id.startsWith('local_'))return request<void>(`/runs/${encodeURIComponent(id)}`,{method:'DELETE'})
 const captured=await getComputeIdentity(),storage=await computeStore(captured)
 await assertComputeIdentity(captured);await removeLocalRun(storage,id)
}
export async function syncLocalRun(id:string):Promise<BacktestResult|PortfolioResult>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured),record=await storage.get<StoredRun>('runs',id)
 if(!id.startsWith('local_')||!record?.sync_request||record.mode==='research')throw new Error('当前用户没有待同步的回测记录')
 const saved=await savedResult(record.mode,record.sync_request,record.result,record.dataset_ids,record.strategy_version,captured,storage) as BacktestResult|PortfolioResult
 if(saved.compute?.storage_status==='local')throw new Error('服务仍不可用，完整回测结果已保留在浏览器，稍后可重试同步')
 return saved
}
export async function advanceRuntimeRun(runId:string,releaseId:string,symbol:string,assetClass:string,interval:Interval,signal?:AbortSignal):Promise<StrategyRun>{
 const captured=await getComputeIdentity(),storage=await computeStore(captured),cap=await capabilities(releaseId,'runtime')
 const requireVisible=()=>{if(signal&&(signal.aborted||document.visibilityState!=='visible'||!window.location.hash.startsWith('#/trading')))throw new Error('交易页面已离开，推进已取消')}
 requireVisible()
 await request(`/compute/runtime/${encodeURIComponent(runId)}/heartbeat`,{method:'POST',signal});requireVisible()
 if(cap.execution_location==='server_private')return request<StrategyRun>(`/trading/runs/${encodeURIComponent(runId)}/tick`,{method:'POST',signal})
 const payload=await resolvedPayload({symbol,asset_class:assetClass,interval},cap),{market,manifest}=await marketFor(payload,storage,signal),target=await workerCompute<{bar_time:number;target:number;reason:string}>({kind:'runtimeSignal',request:payload,market},captured,undefined,signal)
 await assertComputeIdentity(captured)
 if(signal&&(signal.aborted||document.visibilityState!=='visible'||!window.location.hash.startsWith('#/trading')))throw new Error('交易页面已离开，推进已取消')
 return request<StrategyRun>(`/compute/runtime/${encodeURIComponent(runId)}/signal`,{method:'POST',signal,body:JSON.stringify({dataset_id:manifest.dataset_id,...target})})
}

export async function prepareExternalStrategy(payload:Record<string,unknown>,signal?:AbortSignal):Promise<Record<string,unknown>>{
 if(payload.strategy_id!=='python_portable')return payload
 const captured=await getComputeIdentity(),storage=await computeStore(captured)
 const {market,manifest}=await marketFor(payload,storage,signal)
 const {createPortablePlan}=await import('./portablePython')
 const portable_plan=await createPortablePlan(String(payload.portable_python??''),market.bars,manifest.dataset_id,String(payload.strategy_name??'Python策略'),(payload.params??{}) as Record<string,unknown>,signal)
 await assertComputeIdentity(captured)
 return {...payload,portable_plan}
}
