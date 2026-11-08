// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { runBacktest } from '../compute/backtest'
import { calculateIndicators } from '../compute/indicators'
import { evaluateProgram, generatePythonTargets, priceMicros } from '../compute/pythonProgram'
import { contributionSchedule, validateParams } from '../compute/strategies'
import type { BacktestResult, Bar } from '../types'
import type { MarketInput } from '../compute/model'
const fixtures=JSON.parse(gunzipSync(readFileSync(new URL('./fixtures/single-engine-python-v1.json.gz',import.meta.url))).toString('utf8')) as {market:MarketInput;indicators:BacktestResult['indicators'];cases:Array<{name:string;request:Record<string,unknown>;result:BacktestResult}>}
function compare(actual:unknown,expected:unknown,path='result'):void {
 if(expected===null){expect(actual,path).toBeNull();return}
 if(typeof expected==='number') {expect(typeof actual,path).toBe('number');const delta=Math.abs((actual as number)-expected);expect(delta,path+` actual=${actual} expected=${expected}`).toBeLessThanOrEqual(1e-10+Math.abs(expected)*1e-11);return}
 if(Array.isArray(expected)){expect(Array.isArray(actual),path).toBe(true);expect((actual as unknown[]).length,path+'.length').toBe(expected.length);expected.forEach((v,i)=>compare((actual as unknown[])[i],v,`${path}[${i}]`));return}
 if(typeof expected==='object'){for(const [key,value] of Object.entries(expected)){if(['run_id','created_at','provider_symbol'].includes(key))continue;compare((actual as Record<string,unknown>)[key],value,`${path}.${key}`)}return}
 expect(actual,path).toBe(expected)
}
describe('Python single-engine oracle parity',()=>{
 for(const fixture of fixtures.cases)it(fixture.name,async()=>{const actual=await runBacktest(fixture.request,fixtures.market);compare(actual,{...fixture.result,bars:fixtures.market.bars,indicators:fixtures.indicators})})
})
describe('browser execution boundaries',()=>{
 it('cancels instead of returning partial results',async()=>{await expect(runBacktest(fixtures.cases[0].request,fixtures.market,{cancelled:()=>true})).rejects.toThrow('取消')})
 it('rejects AI stages when callback missing',async()=>{await expect(runBacktest({...fixtures.cases[0].request,execution_pipeline:{max_position:.5,commission_rate:.001,slippage_rate:.0005,max_participation_rate:.01,ai_stages:[{enabled:true,stage:'risk',authority:'veto'}]}},fixtures.market)).rejects.toThrow('审核回调')})
 it('never silently repairs missing/duplicate market bars',async()=>{const bars=structuredClone(fixtures.market.bars);bars[2].close=NaN;await expect(runBacktest(fixtures.cases[0].request,{...fixtures.market,bars})).rejects.toThrow('行情存在');bars[2]=bars[1];await expect(runBacktest(fixtures.cases[0].request,{...fixtures.market,bars})).rejects.toThrow('行情存在')})
 it('uses UTC month end anchoring, coalescing coarse dates',()=>{const ts=['2024-01-31','2024-02-28','2024-02-29','2024-03-31','2024-05-31'].map(s=>Date.parse(s)/1000);expect(contributionSchedule(ts,1,'months')).toEqual([true,false,true,true,true])})
 it('retains indicator warmups',()=>{const output=calculateIndicators(fixtures.market.bars);expect(output.sma20.slice(0,19).every(p=>p.value===null)).toBe(true);expect(output.ema26[24].value).toBeNull();expect(output.macd_signal[32].value).toBeNull();expect(output.macd_signal[33].value).not.toBeNull()})
 it('rejects unknown/invalid catalog params',()=>{expect(()=>validateParams('sma_cross',{fast:true})).toThrow();expect(()=>validateParams('sma_cross',{typo:1})).toThrow();expect(()=>validateParams('sma_cross',{fast:2.5})).toThrow()})
 it('interprets large integer arithmetic exactly',()=>{expect(evaluateProgram([{const:'999999999999999999'},{const:'999999999999999998'},'sub'],[],[0n],1)).toBe(1n);expect(()=>evaluateProgram([{const:1e18}],[],[0n],1)).toThrow('精确');expect(()=>evaluateProgram([{const:1000000000},{const:1000000000},'mul',{const:2},'mul'],[],[0n],1)).toThrow('限制')})
 it('uses Decimal-style price truncation and exact prefix SMA',()=>{expect(priceMicros(1.000001)).toBe(1000001n);expect(priceMicros(.0000001)).toBe(0n);const bars=fixtures.market.bars.slice(0,3).map((b,i)=>({...b,close:[1.000001,1.000002,1.000003][i]})) as Bar[];expect(generatePythonTargets(bars,[{sma:2},{close:0},'lt',{const:9000},{const:0},'select']).target).toEqual([.9,.9,.9])})
})
