import bootstrap from './portable_runner.py?raw'
import type { Bar } from '../types'
import { LONG_BACKTEST_BARS, MAX_PORTABLE_BARS, packBars, packTargets } from './longBacktest'

export interface PortablePlan {dataset_id:string;source_sha256:string;name:string;start:number;end:number;targets?:number[];targets_gzip?:string}

export function packedTargetOutput(expression: string) {
 return `py.globals.set('_packed',new Uint8Array(data.packed));
 const proxy=await py.runPythonAsync(${JSON.stringify(expression)});
 const bytes=proxy.toJs();
 proxy.destroy();
 const targets=new Float64Array(bytes.buffer,bytes.byteOffset,bytes.byteLength/8);
 self.postMessage({kind:'done',targets},[targets.buffer]);`
}

export function portableMarketInput(bars: Bar[]) {
 if(!bars.length||bars.length>MAX_PORTABLE_BARS)throw new Error(`Python 回测支持 1 至 ${MAX_PORTABLE_BARS.toLocaleString('zh-CN')} 根 K 线，本次选择 ${bars.length.toLocaleString('zh-CN')} 根。`)
 return bars.length > LONG_BACKTEST_BARS ? { packed: packBars(bars) } : { bars }
}

export function readPortableTargets(result: Record<string, unknown>, count: number): number[] {
 const targets = result.targets
 if ((!Array.isArray(targets) && !(targets instanceof Float64Array)) || targets.length!==count
    || targets.some((v:unknown)=>typeof v!=='number'||!Number.isFinite(v)||v<0||v>1))throw new Error('Python返回的仓位计划无效')
 return Array.isArray(targets) ? targets : Array.from(targets)
}

export async function encodePortableTargets(targets: number[]) {
 return targets.length > LONG_BACKTEST_BARS ? { targets_gzip: await packTargets(targets) } : { targets }
}

// The Python source is a message, never part of executable HTML/JavaScript.
// The opaque-origin iframe owns a dedicated Worker, no host credentials or DOM.
export function portableFrameDocument(runtimeBase:string, projectRunner?: string):string {
 const base=new URL(runtimeBase)
 if(!['http:','https:'].includes(base.protocol)||base.username||base.password||!base.pathname.endsWith('/api/v1/python-runtime/'))throw new Error('Python运行库地址无效')
 const worker=`self.onmessage=async({data})=>{try{
  importScripts(${JSON.stringify(base.href)}+'pyodide.js');
  const py=await loadPyodide({indexURL:${JSON.stringify(base.href)},jsglobals:Object.create(null)});
  ${projectRunner ?? `await py.loadPackagesFromImports(data.source);
  py.globals.set('_source',data.source);py.globals.set('_parameters',JSON.stringify(data.params||{}));
  await py.runPythonAsync(${JSON.stringify(bootstrap)});
  if(data.packed){
   ${packedTargetOutput('run_packed_strategy(_source, _packed, _parameters)')}
  }else{
   py.globals.set('_bars',JSON.stringify(data.bars));
   const targets=JSON.parse(await py.runPythonAsync('run_strategy(_source, _bars, _parameters)'));
   self.postMessage({kind:'done',targets});
  }`}
 }catch(error){self.postMessage({kind:'error',message:String(error).slice(0,5000)})}};`
 const csp=`default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: ${base.href}; connect-src ${base.href}; worker-src blob:;`
 const controller=`let worker;window.addEventListener('message',event=>{if(event.source!==parent)return;const data=event.data;if(data.kind==='cancel'){worker?.terminate();return}if(data.kind!=='run'||worker)return;worker=new Worker(URL.createObjectURL(new Blob([${JSON.stringify(worker)}],{type:'text/javascript'})));worker.onmessage=({data:result})=>parent.postMessage({...result,id:data.id},'*',result.targets instanceof Float64Array?[result.targets.buffer]:[]);worker.onerror=()=>parent.postMessage({kind:'error',id:data.id,message:'Python运行环境加载失败'},'*');worker.postMessage(data,[data.archive,data.packed].filter(value=>value instanceof ArrayBuffer))});window.addEventListener('pagehide',()=>worker?.terminate());parent.postMessage({kind:'ready'},'*');`
 return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${csp}"><script>${controller.replace(/<\/script/gi,'<\\/script')}</script>`
}

export async function runPortablePython(source:string,bars:Bar[],params:Record<string,unknown>={},signal?:AbortSignal):Promise<number[]>{
 if(!source.trim()||source.length>60000)throw new Error('Python代码须为1至60000字符')
 if(signal?.aborted)throw new DOMException('已取消','AbortError')
 return runIsolatedPython({source,...portableMarketInput(bars),params},result=>readPortableTargets(result,bars.length),signal)
}

export async function runIsolatedPython<T>(
 payload: Record<string, unknown>,
 readResult: (result: Record<string, unknown>) => T,
 signal?: AbortSignal,
 projectRunner?: string,
): Promise<T> {
 if(signal?.aborted)throw new DOMException('已取消','AbortError')
 const id=crypto.randomUUID(),frame=document.createElement('iframe')
 frame.hidden=true;frame.setAttribute('sandbox','allow-scripts');frame.setAttribute('aria-hidden','true')
 const apiRoot=(import.meta.env.VITE_API_ROOT??'/api/v1').replace(/\/$/,'')
 frame.srcdoc=portableFrameDocument(new URL(apiRoot+'/python-runtime/',location.origin).href,projectRunner)
 return new Promise((resolve,reject)=>{
  let started=false
  const lifecycleEvents=['trine-session-lock','atlas-session-expired','pagehide']
  const cleanup=()=>{clearTimeout(timer);window.removeEventListener('message',receive);signal?.removeEventListener('abort',abort);for(const event of lifecycleEvents)window.removeEventListener(event,abort);frame.contentWindow?.postMessage({kind:'cancel'},'*');setTimeout(()=>frame.remove(),200)}
  const abort=()=>{cleanup();reject(new DOMException('Python执行已取消','AbortError'))}
  const receive=(event:MessageEvent)=>{
   if(event.source!==frame.contentWindow)return
   const result=event.data
   if(result?.kind==='ready'&&!started){
    started=true
    const transfer=[payload.archive,payload.packed].filter(value=>value instanceof ArrayBuffer)
    frame.contentWindow!.postMessage({kind:'run',id,...payload},'*',transfer)
    return
   }
   if(result?.id!==id)return
   if(result.kind==='error'){cleanup();reject(new Error(result.message));return}
   if(result.kind==='done'){
    cleanup()
    try{resolve(readResult(result))}catch(error){reject(error)}
   }
  }
  const timer=setTimeout(()=>{cleanup();reject(new Error('Python策略超过10分钟，已停止执行'))},600000)
  window.addEventListener('message',receive);signal?.addEventListener('abort',abort,{once:true});for(const event of lifecycleEvents)window.addEventListener(event,abort,{once:true});document.body.append(frame)
 })
}

export async function createPortablePlan(source:string,bars:Bar[],datasetId:string,name='Python策略',params:Record<string,unknown>={},signal?:AbortSignal):Promise<PortablePlan>{
 const targets=await runPortablePython(source,bars,params,signal)
 const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(source))
 const encoded = await encodePortableTargets(targets)
 return {dataset_id:datasetId,source_sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''),name:name.slice(0,80),start:bars[0].time,end:bars.at(-1)!.time,...encoded}
}
