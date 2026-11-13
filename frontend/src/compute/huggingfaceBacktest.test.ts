import { expect, it } from 'vitest'
import { runBacktest } from './backtest'
import type { MarketInput } from './model'

function market(): MarketInput {
 return {asset:{symbol:'300750.SZ',name:'宁德时代',asset_class:'equity',exchange:'SZSE',currency:'CNY',timezone:'Asia/Shanghai',tags:[]},
  source:'hf-ohlcv',interval:'1m',adjustment:'raw',
  bars:Array.from({length:100},(_,i)=>{const close=i<50?100+i:200-i;return {time:1735781400+i*60,open:close,high:close+1,low:close-1,close,volume:100000}})}
}
it('keeps zero-volume HF bars in the tape but never fills on them', async () => {
 const tape=market();tape.bars=tape.bars.map(b=>({...b,volume:0}))
 const result=await runBacktest({strategy_id:'sma_cross',params:{fast:5,slow:20},initial_capital:100000},tape)
 expect(result.bars).toEqual(tape.bars)
 expect(result.trades).toEqual([])
 expect(result.equity.every(point=>point.equity===100000)).toBe(true)
})
it('does not change past fills or equity when later HF prices change', async () => {
 const tape=market(),changed=structuredClone(tape)
 changed.bars=changed.bars.map((b,i)=>i>=60?{...b,open:b.open*2,high:b.high*2,low:b.low*2,close:b.close*2}:b)
 const request={strategy_id:'sma_cross',params:{fast:5,slow:20},initial_capital:100000}
 const first=await runBacktest(request,tape),second=await runBacktest(request,changed)
 expect(first.trades.length).toBeGreaterThan(0)
 expect(first.equity.slice(0,60)).toEqual(second.equity.slice(0,60))
 const cutoff=tape.bars[60].time
 expect(first.trades.filter(t=>t.time<cutoff)).toEqual(second.trades.filter(t=>t.time<cutoff))
})
