// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { gunzipSync } from 'node:zlib'
import { readFileSync } from 'node:fs'
import { installComputeWorker } from '../compute/worker'
import type { WorkerInput, WorkerOutput, WorkerPort } from '../compute/worker'
import { computeRuntimeSignal } from '../compute/runtime'
import type { MarketInput } from '../compute/model'
const fixture=JSON.parse(gunzipSync(readFileSync(new URL('./fixtures/single-engine-python-v1.json.gz',import.meta.url))).toString()) as {market:MarketInput}
function harness(){const messages:WorkerOutput[]=[],port:WorkerPort={onmessage:null,postMessage:m=>messages.push(m)};installComputeWorker(port);const send=(message:WorkerInput)=>port.onmessage!({data:message} as MessageEvent<WorkerInput>);return {messages,send}}
function done(messages:WorkerOutput[]):Promise<WorkerOutput>{return new Promise((resolve,reject)=>{const start=Date.now();const tick=()=>{const last=messages.find(m=>m.type==='error'||m.type==='complete');if(last)resolve(last);else if(Date.now()-start>5000)reject(new Error('worker timed out'));else setTimeout(tick,5)};tick()})}
describe('worker protocol',()=>{
 it('bounds indicator output when hydrating a full history',async()=>{
  const h=harness(),bars=Array.from({length:4001},(_,i)=>({...fixture.market.bars[0],time:1700000000+i*60}))
  h.send({type:'start',id:'long-indicators',task:{kind:'indicators',bars}})
  const output=await done(h.messages)
  expect(output.type).toBe('complete')
  if(output.type==='complete')expect((output.result as Record<string,unknown[]>).rsi14).toHaveLength(3000)
 })
 it('returns calculated indicators through the actual worker handler',async()=>{const h=harness();h.send({type:'start',id:'indicator',task:{kind:'indicators',bars:fixture.market.bars}});const result=await done(h.messages);expect(result.type).toBe('complete');if(result.type==='complete')expect(Object.keys(result.result)).toContain('rsi14')})
 it('progresses and cancels a running loop without returning partial results',async()=>{const h=harness();h.send({type:'start',id:'cancel',task:{kind:'single',request:{strategy_id:'dca'},market:fixture.market}});expect(h.messages.some(m=>m.type==='progress')).toBe(true);h.send({type:'cancel',id:'cancel'});const result=await done(h.messages);expect(result.type).toBe('error');if(result.type==='error')expect(result.message).toContain('取消')})
 it('requires successful AI rpc completion and ignores messages for another run',async()=>{const h=harness();h.send({type:'start',id:'ai',task:{kind:'single',request:{strategy_id:'dca',execution_pipeline:{max_position:.5,commission_rate:.001,slippage_rate:.0005,max_participation_rate:.01,ai_stages:[{stage:'risk',enabled:true,authority:'veto',instructions:'',timeout_ms:100,max_reduction:.25}]}},market:fixture.market}});await new Promise(resolve=>setTimeout(resolve,10));const review=h.messages.find(m=>m.type==='ai_review');expect(review).toBeTruthy();if(review?.type!=='ai_review')return;h.send({type:'ai_result',id:'wrong',rpcId:review.rpcId,result:{status:'inference_completed',scale:1}});expect(h.messages.some(m=>m.type==='complete')).toBe(false);h.send({type:'ai_result',id:'ai',rpcId:review.rpcId,error:'模型拒绝'});const result=await done(h.messages);expect(result.type).toBe('error');if(result.type==='error')expect(result.message).toBe('模型拒绝')})
 it('never uses an incomplete live candle for a runtime target',()=>{const bars=fixture.market.bars.slice(0,45),cutoff=bars.at(-1)!.time+100,result=computeRuntimeSignal({strategy_id:'dca',interval:'1d'}, {...fixture.market,bars},cutoff);expect(result.bar_time).toBe(bars.at(-2)!.time);expect(()=>computeRuntimeSignal({strategy_id:'dca'}, {...fixture.market,bars:[bars.at(-1)!]},cutoff)).toThrow('已收盘')})
})
