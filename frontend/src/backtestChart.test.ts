import { expect, it } from 'vitest'
import { retainChartHistory, outsideBacktest } from './backtestChart'
import type { MarketData, Bar } from './types'
it('keeps bars before and after a backtest while adding missing historical bars',()=>{
 const bar=(time:number)=>({time,open:10,high:11,low:9,close:10,volume:1} as Bar)
 const current={asset:{symbol:'BTC-USD'},interval:'1d',source:'binance',bars:[bar(2),bar(3),bar(4)]} as MarketData
 const result={...current,bars:[bar(1),{...bar(2),close:10.5}]}
 const next=retainChartHistory(current,result)
 expect(next.bars.map(b=>b.time)).toEqual([1,2,3,4]);expect(next.bars[1].close).toBe(10.5)
 expect(outsideBacktest(1,2,3)).toBe(true);expect(outsideBacktest(4,2,3)).toBe(true);expect(outsideBacktest(2,2,3)).toBe(false)
 expect(retainChartHistory(current,{...result,source:'demo'}).bars).toEqual(result.bars)
})
