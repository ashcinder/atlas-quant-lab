/** Small IDB test double: requests finish before transactions commit, just like IDB. */
export function idbHarness(){
 const databases=new Map<string,Map<string,Map<IDBValidKey,unknown>>>()
 let failCommit=false
 const indexedDB={open(name:string){const request:Record<string,unknown>={};queueMicrotask(()=>{
  const isNew=!databases.has(name),stores=databases.get(name)??new Map<string,Map<IDBValidKey,unknown>>();databases.set(name,stores)
  const db={objectStoreNames:{contains:(n:string)=>stores.has(n)},createObjectStore:(n:string)=>stores.set(n,new Map()),close:()=>undefined,onversionchange:null,transaction:(n:string)=>{
   const tx:Record<string,unknown>={error:null};let last:Record<string,unknown>|null=null
   tx.objectStore=()=>{const data=stores.get(n)!;const query=(act:()=>unknown)=>{const req:Record<string,unknown>={};last=req;queueMicrotask(()=>{req.result=act();(req.onsuccess as (()=>void))?.();queueMicrotask(()=>{if(req!==last)return;if(failCommit){failCommit=false;tx.error=new DOMException('quota','QuotaExceededError');(tx.onabort as (()=>void))?.()}else (tx.oncomplete as (()=>void))?.()})});return req}
    return {get:(key:IDBValidKey)=>query(()=>structuredClone(data.get(key))),getAll:()=>query(()=>[...data.values()].map(x=>structuredClone(x))),put:(value:unknown,key:IDBValidKey)=>query(()=>{data.set(key,structuredClone(value));return key}),delete:(key:IDBValidKey)=>query(()=>data.delete(key))}}
   return tx
  }}
  request.result=db;if(isNew)(request.onupgradeneeded as (()=>void))?.();(request.onsuccess as (()=>void))?.()
 });return request}}
 return {indexedDB,databases,failNextCommit:()=>{failCommit=true}}
}
