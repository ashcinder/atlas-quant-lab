import type { CustomStrategySpec, Interval } from '../types'
import type { MarketInput } from './model'
import { generateTargetExposure, generateCustomTarget, validateParams } from './strategies'
import { generatePythonTargets } from './pythonProgram'
import type { PythonInstruction } from './pythonProgram'
export interface RuntimeSignal {bar_time:number;target:number;reason:string}
export function computeRuntimeSignal(request:Record<string,unknown>,market:MarketInput,nowSeconds=Date.now()/1000):RuntimeSignal{
 const interval=(request.interval??market.interval??'1d') as Interval,duration=({'15m':900,'1h':3600,'4h':14400,'1d':86400,'1wk':604800})[interval]
 if(!duration)throw new Error('不支持的K线周期')
 const bars=market.bars.filter(b=>b.time<=nowSeconds-duration)
 if(!bars.length)throw new Error('没有已收盘K线，无法生成信号')
 const id=String(request.strategy_id??'sma_cross'),maximum=Number(request.max_position??1)
 if(!Number.isFinite(maximum)||maximum<=0||maximum>1)throw new Error('目标仓位上限无效')
 let target:number[],reasons:string[]
 if(request.python_program){({target,reasons}=generatePythonTargets(bars,request.python_program as PythonInstruction[],maximum))}
 else if(request.python_source)throw new Error('受限Python源码需先编译为整数指令')
 else if(request.custom_strategy){const custom=request.custom_strategy as CustomStrategySpec;({target,reasons}=generateCustomTarget(bars,custom,Math.min(maximum,custom.target_position)))}
 else if(id==='scheduled_dca'){validateParams(id,(request.params??{}) as Record<string,unknown>);target=bars.map(()=>maximum);reasons=bars.map(()=>'固定金额定投')}
 else ({target,reasons}=generateTargetExposure(bars,id,(request.params??{}) as Record<string,unknown>,maximum))
 return {bar_time:bars.at(-1)!.time,target:target.at(-1)!,reason:reasons.at(-1)!}
}
