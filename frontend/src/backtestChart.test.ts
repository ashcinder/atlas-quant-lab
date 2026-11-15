import { expect, it } from 'vitest'
import { retainChartHistory, outsideBacktest, extendPublishedChart } from './backtestChart'
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
it('keeps previous bars while taking freshness and source metadata from each new response', () => {
 const bar=(time:number)=>({time,open:10,high:11,low:9,close:10,volume:1} as Bar)
 const current={asset:{symbol:'BTC-USD',asset_class:'crypto'},interval:'15m',adjustment:'raw',source:'binance:stale-cache',is_stale:true,last_bar_time:2,fetched_at:2,cache_hit:true,bars:[bar(1),bar(2)]} as MarketData
 const fresh={...current,source:'binance',is_stale:false,last_bar_time:3,fetched_at:3,cache_hit:false,bars:[bar(2),bar(3)]}
 const updated=retainChartHistory(current,fresh)
 expect(updated.bars.map(b=>b.time)).toEqual([1,2,3])
 expect(updated).toMatchObject({source:'binance',is_stale:false,last_bar_time:3,fetched_at:3,cache_hit:false})
 expect(retainChartHistory(updated,{...fresh,source:'binance:stale-cache',is_stale:true})).toMatchObject({source:'binance:stale-cache',is_stale:true})
 expect(retainChartHistory(updated,{...fresh,adjustment:'forward'}).bars.map(b=>b.time)).toEqual([2,3])
})

it('keeps the fixed snapshot, appends only newer raw bars, and identifies the source and gap', () => {
  const bar = (time: number) => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 20 })
  const history = {
    asset: { symbol: '002371.SZ', exchange: 'SZSE' }, interval: '5m', adjustment: 'raw',
    source: 'hf-ohlcv', bars: [bar(300), bar(600)],
  } as MarketData
  const recent = {
    ...history, source: 'sina', bars: [{ ...bar(600), close: 12 }, bar(345_600)],
    fetched_at: 345_920, is_stale: false, cache_hit: false,
  }
  const chart = extendPublishedChart(history, recent)
  expect(chart.bars).toEqual([bar(300), bar(600), bar(345_600)])
  expect(chart.chart_feed).toEqual({ source: 'sina', start: 345_600, has_gap: true, used_as_fallback: false })
  expect(chart.source).toBe('hf-ohlcv')
  expect(extendPublishedChart(history, { ...recent, adjustment: 'forward' })).toBe(history)
  const revised = extendPublishedChart(history, { ...recent, source: 'eastmoney', bars: [bar(346_200)] })
  expect(retainChartHistory(chart, revised).bars).toEqual([bar(300), bar(600), bar(346_200)])
})
