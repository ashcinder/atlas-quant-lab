import { expect, it } from 'vitest'
import { calculateMetrics } from './metrics'

it('calculates drawdown across a full CATL-sized minute history without argument-stack overflow', () => {
 const count=475251
 const equity=Array.from({length:count},(_,i)=>i<count/2?100000:50000)
 const benchmark=Array<number>(count).fill(100000)
 const exposure=Array<number>(count).fill(1)
 const {metrics}=calculateMetrics(equity,benchmark,[],exposure,'1m','equity',100000,'SZSE')
 expect(metrics.max_drawdown).toBe(-.5)
 expect(metrics.total_return).toBe(-.5)
 expect(metrics.trade_count).toBe(0)
})
