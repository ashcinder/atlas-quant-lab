import type { BacktestResult, Bar, IndicatorPoint, PortfolioResult, ResearchResult } from '../types'
import type { AIReviewInput, ComputeContext, MarketInput } from './model'
import { runBacktest } from './backtest'
import { runPortfolio } from './portfolio'
import { runResearch } from './research'
import { calculateIndicators } from './indicators'
import { computeRuntimeSignal } from './runtime'
import type { RuntimeSignal } from './runtime'
export type WorkerTask = {kind:'runtimeSignal';request:Record<string,unknown>;market:MarketInput}|{kind:'single';request:Record<string,unknown>;market:MarketInput}|{kind:'portfolio';request:Record<string,unknown>;markets:MarketInput[]}|{kind:'research';request:Record<string,unknown>;market:MarketInput;jobId:string}|{kind:'indicators';bars:Bar[]}
export type WorkerResult=RuntimeSignal|BacktestResult|PortfolioResult|ResearchResult|Record<string,IndicatorPoint[]>
export type WorkerInput={type:'start';id:string;task:WorkerTask}|{type:'cancel';id:string}|{type:'ai_result';id:string;rpcId:string;result?:{scale:number;status:string};error?:string}
export type WorkerOutput={type:'progress';id:string;progress:number;message:string}|{type:'complete';id:string;result:WorkerResult}|{type:'error';id:string;message:string}|{type:'ai_review';id:string;rpcId:string;input:AIReviewInput}
export interface WorkerPort {postMessage:(message:WorkerOutput)=>void;onmessage:((event:MessageEvent<WorkerInput>)=>void)|null}
/** Exported installer makes the worker protocol testable without a real browser. */
export function installComputeWorker(port:WorkerPort):void{
 let active:string|null=null,cancelled=false
 const reviews=new Map<string,{resolve:(result:{scale:number;status:string})=>void;reject:(error:Error)=>void}>()
 port.onmessage=event=>{const message=event.data
  if(message.type==='cancel'){if(message.id===active){cancelled=true;for(const pending of reviews.values())pending.reject(new Error('计算已取消'));reviews.clear()}return}
  if(message.type==='ai_result'){if(message.id!==active)return;const pending=reviews.get(message.rpcId);if(!pending)return;reviews.delete(message.rpcId);if(message.error||!message.result)pending.reject(new Error(message.error??'AI 审核返回无效'));else pending.resolve(message.result);return}
  if(active){port.postMessage({type:'error',id:message.id,message:'计算 Worker 正忙'});return}
  active=message.id;cancelled=false
  const id=message.id,task=message.task,context:ComputeContext={cancelled:()=>cancelled,progress:(progress,text)=>port.postMessage({type:'progress',id,progress,message:text}),aiReview:input=>new Promise((resolve,reject)=>{const rpcId=crypto.randomUUID();reviews.set(rpcId,{resolve,reject});port.postMessage({type:'ai_review',id,rpcId,input})})}
  void (async()=>{try{let result:WorkerResult
   if(task.kind==='single')result=await runBacktest(task.request,task.market,context)
   else if(task.kind==='portfolio')result=runPortfolio(task.request,task.markets,context)
   else if(task.kind==='research')result=await runResearch(task.request,task.market,{...context,jobId:task.jobId})
   else if(task.kind==='runtimeSignal')result=computeRuntimeSignal(task.request,task.market)
   else result=calculateIndicators(task.bars)
   if(cancelled)throw new Error('计算已取消');port.postMessage({type:'complete',id,result})
  }catch(error){port.postMessage({type:'error',id,message:error instanceof Error?error.message:'浏览器计算失败'})}finally{active=null;for(const pending of reviews.values())pending.reject(new Error('计算已结束'));reviews.clear()}})()
 }
}
if(typeof self!=='undefined'&&typeof document==='undefined')installComputeWorker(self as unknown as WorkerPort)
