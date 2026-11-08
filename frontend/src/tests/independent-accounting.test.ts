import {it,expect} from 'vitest'
import {runBacktest} from '../compute/backtest'
import type {MarketInput} from '../compute/model'
const market:MarketInput={asset:{symbol:'TEST',name:'Synthetic cash oracle',asset_class:'crypto',currency:'USD',exchange:'fixture',timezone:'UTC',tags:[]},source:'independent-fixed',bars:Array.from({length:60},(_,i)=>({time:1704067200+i*86400,open:100,close:100,high:101,low:99,volume:100000}))}
it('independently derives next-open execution quantity fees and flat-market net return',async()=>{
 const r=await runBacktest({strategy_id:'custom',custom_strategy:{id:'oracle',name:'Oracle',description:'Algebraic fixture',entry:{kind:'condition',left:{field:'close'},operator:'gt',right_value:0},exit:{kind:'condition',left:{field:'close'},operator:'lt',right_value:0},target_position:1},initial_capital:1000,max_position:1,commission_rate:.01,slippage_rate:0,spread_rate:0,max_participation_rate:1},market)
 // $1000 = q * $100 + 1% commission, independent algebraic cash oracle.
 const quantity=1000/(100*1.01),fee=quantity*100*.01
 expect(r.trades).toHaveLength(1);const t=r.trades[0];expect(t.time).toBe(market.bars[1].time);expect(t.side).toBe('buy');expect(t.quantity).toBeCloseTo(quantity,10);expect(t.fee).toBeCloseTo(fee,10);expect(t.cash_after).toBeCloseTo(0,10);expect(r.equity[0].equity).toBe(1000);expect(r.equity.at(-1)!.equity).toBeCloseTo(quantity*100,10);expect(r.metrics.total_return).toBeCloseTo((quantity*100-1000)/1000,10)
})
it('independently derives spread and slippage cost without creating capital',async()=>{
 const r=await runBacktest({strategy_id:'custom',custom_strategy:{id:'oracle',name:'Oracle',description:'Algebraic fixture',entry:{kind:'condition',left:{field:'close'},operator:'gt',right_value:0},exit:{kind:'condition',left:{field:'close'},operator:'lt',right_value:0},target_position:1},initial_capital:1000,max_position:1,commission_rate:.01,slippage_rate:.01,spread_rate:.02,max_participation_rate:1},market)
 const price=100*(1+.01+.02/2),quantity=1000/(price*1.01),trade=r.trades[0]
 expect(trade.price).toBe(price);expect(trade.quantity).toBeCloseTo(quantity,10);expect(trade.slippage_cost).toBeCloseTo(quantity*(price-100),10);expect(r.equity.at(-1)!.equity).toBeCloseTo(quantity*100,10)
 let cash=1000,held=0
 for(const t of r.trades){cash+=(t.side==='buy'?-t.notional:t.notional)-t.fee;held+=(t.side==='buy'?1:-1)*t.quantity;expect(t.cash_after).toBeCloseTo(cash,10);expect(t.position_after).toBeCloseTo(held,10)}
 expect(r.equity.at(-1)!.equity).toBeCloseTo(cash+held*100,10)
})
