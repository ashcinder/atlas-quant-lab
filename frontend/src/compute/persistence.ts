import type { BacktestResult, PortfolioResult, ResearchJob, ResearchResult } from '../types'
export const LOCAL_SAVE_NOTICE='回测已完成并保存在当前浏览器；本地服务暂时不可用，报告尚未同步。可从回测历史打开或重试同步，无需重新回测。'
export interface ComputeIdentity { owner_id:string; session_scope:string }
export type StoredResult=BacktestResult|PortfolioResult|ResearchResult
export interface StoredRun {id:string; mode:'single'|'portfolio'|'research'; result:StoredResult; dataset_ids:string[]; strategy_version:string|null; created_at:string; sync_request?:Record<string,unknown>}
export interface StoredTask {page_scope?:string; id:string; status:'queued'|'running'|'completed'|'failed'|'cancelled'; mode:'single'|'portfolio'|'research'; request:Record<string,unknown>; dataset_ids:string[]; result:StoredResult|null; progress:number;message:string;error:string|null;created_at:string;updated_at:string}
const STORE_NAMES=['chunks','manifests','runs','tasks','jobs'] as const
export type ComputeStoreName=typeof STORE_NAMES[number]
export class ComputeStore {
 private database:Promise<IDBDatabase>
 constructor(readonly identity:ComputeIdentity){
  if(typeof indexedDB==='undefined')throw new Error('当前浏览器不支持 IndexedDB，无法保存本地计算任务')
  if(!identity.owner_id||!identity.session_scope)throw new Error('计算需要已登录的用户身份')
  this.database=new Promise((resolve,reject)=>{
   const open=indexedDB.open(`atlas.compute.v1:${encodeURIComponent(identity.owner_id)}`,1)
   open.onupgradeneeded=()=>{for(const name of STORE_NAMES)if(!open.result.objectStoreNames.contains(name))open.result.createObjectStore(name)}
   open.onerror=()=>reject(new Error(`无法打开浏览器计算存储：${open.error?.message??'访问被阻止'}`))
   open.onblocked=()=>reject(new Error('浏览器计算存储被其他页面阻塞，请关闭旧页面后重试'))
   open.onsuccess=()=>{const db=open.result;db.onversionchange=()=>db.close();resolve(db)}
  })
 }
 private async transaction<T>(name:ComputeStoreName,mode:IDBTransactionMode,action:(store:IDBObjectStore)=>IDBRequest<T>):Promise<T>{
  const db=await this.database
  return new Promise((resolve,reject)=>{
   let result:T,tx:IDBTransaction
   try{tx=db.transaction(name,mode);const req=action(tx.objectStore(name));req.onsuccess=()=>{result=req.result};req.onerror=()=>{ /* transaction owns error handling */ };tx.oncomplete=()=>resolve(result);tx.onabort=tx.onerror=()=>reject(new Error(`浏览器计算存储失败：${tx.error?.message??'存储不可用或空间不足'}`))}catch(error){reject(error)}
  })
 }
 get<T>(name:ComputeStoreName,key:string):Promise<T|undefined>{return this.transaction(name,'readonly',store=>store.get(key))}
 async put<T>(name:ComputeStoreName,key:string,value:T):Promise<void>{await this.transaction(name,'readwrite',store=>store.put(value,key))}
 async delete(name:ComputeStoreName,key:string):Promise<void>{await this.transaction(name,'readwrite',store=>store.delete(key))}
 async update<T>(name:ComputeStoreName,key:string,change:(value:T|undefined)=>T):Promise<void>{
  const db=await this.database
  await new Promise<void>((resolve,reject)=>{
   const tx=db.transaction(name,'readwrite'),store=tx.objectStore(name),get=store.get(key)
   tx.oncomplete=()=>resolve();tx.onabort=tx.onerror=()=>reject(new Error('浏览器计算索引更新失败'))
   get.onsuccess=()=>{try{store.put(change(get.result),key)}catch(error){tx.abort();reject(error)}}
  })
 }
 all<T>(name:ComputeStoreName):Promise<T[]>{return this.transaction(name,'readonly',store=>store.getAll())}
 async close():Promise<void>{(await this.database).close()}
 /** Recover previous-page tasks only once per store instance before scheduling new work. */
 async recoverInterrupted(pageScope?:string):Promise<void>{
  const now=new Date().toISOString()
  const tasks=await this.all<StoredTask>('tasks')
  for(const task of tasks)if((!pageScope||task.page_scope===pageScope)&&(task.status==='running'||task.status==='queued'))await this.put('tasks',task.id,{...task,status:'failed',message:'页面已关闭，计算已中断；请重新运行',error:'interrupted',updated_at:now})
  const jobs=await this.all<ResearchJob&{page_scope?:string}>('jobs')
  for(const job of jobs)if((!pageScope||job.page_scope===pageScope)&&(job.status==='running'||job.status==='queued'))await this.put('jobs',job.id,{...job,status:'failed',message:'页面已关闭，研究已中断；请重新运行',error:'interrupted',updated_at:now})
 }
}
