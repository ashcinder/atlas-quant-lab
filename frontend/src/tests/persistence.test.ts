import { afterEach, describe, expect, it, vi } from 'vitest'
import { ComputeStore } from '../compute/persistence'
import { idbHarness } from './idb-harness'
const identity={owner_id:'owner_a',session_scope:'session_a'}
afterEach(()=>vi.unstubAllGlobals())
describe('owner isolated durable IndexedDB tasks',()=>{
 it('refuses unsupported persistence instead of an in-memory fallback',()=>{vi.stubGlobal('indexedDB',undefined);expect(()=>new ComputeStore(identity)).toThrow('IndexedDB')})
 it('never reads another user cache/results even for identical keys',async()=>{const h=idbHarness();vi.stubGlobal('indexedDB',h.indexedDB);const a=new ComputeStore(identity),b=new ComputeStore({owner_id:'owner_b',session_scope:'session_b'});await a.put('runs','same',{secret:'owner A'});expect(await b.get('runs','same')).toBeUndefined();expect(await a.get('runs','same')).toEqual({secret:'owner A'});expect(h.databases.size).toBe(2)})
 it('reports a failed transaction commit even after its request succeeded',async()=>{const h=idbHarness();vi.stubGlobal('indexedDB',h.indexedDB);const a=new ComputeStore(identity);await a.get('runs','nothing');h.failNextCommit();await expect(a.put('runs','same',{value:1})).rejects.toThrow('quota')})
 it('marks previous-page running work interrupted and retains completed or other-tab work',async()=>{const h=idbHarness();vi.stubGlobal('indexedDB',h.indexedDB);const a=new ComputeStore(identity);await a.put('tasks','old',{id:'old',page_scope:'tab-a',status:'running'});await a.put('tasks','done',{id:'done',page_scope:'tab-a',status:'completed',result:{value:2}});await a.put('tasks','other',{id:'other',page_scope:'tab-b',status:'running'});await a.put('jobs','job',{id:'job',page_scope:'tab-a',status:'queued'});await a.recoverInterrupted('tab-a');expect(await a.get('tasks','old')).toMatchObject({status:'failed',error:'interrupted'});expect(await a.get('jobs','job')).toMatchObject({status:'failed',error:'interrupted'});expect(await a.get('tasks','done')).toMatchObject({status:'completed',result:{value:2}});expect(await a.get('tasks','other')).toMatchObject({status:'running'})})
})
