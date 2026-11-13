import { expect, it } from 'vitest'
import { calculateIndicators } from './indicators'
import { runBacktest } from './backtest'
import type { MarketInput } from './model'

const asset={symbol:'300750.SZ',name:'宁德时代',asset_class:'equity',exchange:'SZSE',currency:'CNY',timezone:'Asia/Shanghai',tags:[]}
const bars=Array.from({length:4001},(_,i)=>({time:1735781400+i*60,open:100+i*.01,high:102+i*.01,low:99+i*.01,close:101+i*.01,volume:100000}))

it('retains full-history indicator values while bounding returned point objects',()=>{
 const full=calculateIndicators(bars),bounded=calculateIndicators(bars,3000)
 for(const key of Object.keys(full))expect(bounded[key]).toEqual(full[key].slice(-3000))
})
it('labels the shared model and keeps every account observation',async()=>{
 const result=await runBacktest({execution_model:'unified',strategy_id:'sma_cross',params:{fast:5,slow:20}},
  {asset,bars,source:'hf-ohlcv',interval:'1m',adjustment:'raw'} as MarketInput)
 expect(result.execution_contract).toBe('research-next-open/v1')
 expect(result.execution_model).toBe('unified')
 expect(result.equity).toHaveLength(bars.length)
 expect(result.bars).toHaveLength(bars.length)
 expect(result.indicators.sma20).toHaveLength(3000)
 expect(result.warnings.join(' ')).toContain('非原生股票账户')
})
it('rejects unresolved releases instead of silently falling back',async()=>{
 await expect(runBacktest({execution_model:'unified',strategy_id:'rsi_reversal',release_id:'unresolved'},
  {asset,bars,source:'hf-ohlcv'} as MarketInput)).rejects.toThrow('已解析')
})
