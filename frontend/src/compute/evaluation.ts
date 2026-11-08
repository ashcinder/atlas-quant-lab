import type { EvaluationDimension, StrategyEvaluation } from '../types'
import type { MetricMap, RegimeMap } from './model'
export const EVALUATION_VERSION='evaluation_v1' as const
const number=(value:unknown):number|null=>typeof value==='boolean'||value==null||!Number.isFinite(Number(value))?null:Number(value)
/** Python's round uses ties to even. */
export function roundEven(value:number,digits=0):number { const f=10**digits,x=value*f,lo=Math.floor(x),fraction=x-lo;return (Math.abs(fraction-.5)<Number.EPSILON*Math.abs(x)*2?(lo%2===0?lo:lo+1):Math.round(x))/f }
const scale=(value:number|null,low:number,high:number):number|null=>value===null?null:roundEven(Math.max(0,Math.min(100,(value-low)/(high-low)*100)),1)
export function buildEvaluation(metrics:MetricMap,period:EvaluationDimension['period'],regimeMetrics?:RegimeMap|null):StrategyEvaluation {
 const dimension=(id:EvaluationDimension['id'],score:number|null,raw:Record<string,unknown>,reason:string|null=null):EvaluationDimension=>({id,status:score===null?'not_evaluable':'evaluated',score,raw,reason,period,rule_version:EVALUATION_VERSION})
 const annual=number(metrics.annualized_return)??number(metrics.cagr),sharpe=number(metrics.sharpe),dd=number(metrics.max_drawdown)
 const dimensions:EvaluationDimension[]=[dimension('return_capacity',scale(annual,-.2,.4),{annualized_return:annual},annual===null?'缺少可核对的年化收益。':null),dimension('risk_adjusted_efficiency',scale(sharpe,-1,3),{sharpe},sharpe===null?'缺少可核对的 Sharpe。':null),dimension('risk_control_stability',scale(dd===null?null:Math.abs(dd),.5,0),{max_drawdown:dd},dd===null?'缺少可核对的最大回撤。':null)]
 const raw:Record<string,unknown>={},excess:number[]=[];let reason:string|null=null
 if(!regimeMetrics)reason='报告未关联可核对的原始市场阶段数据，不能推算市场适应性。'
 else {for(const name of ['牛市','熊市','震荡']){const source=regimeMetrics[name]??{},periods=Number(source.periods||0),v=number(source.annualized_excess_return);raw[name]={periods,strategy_annualized_return:number(source.annualized_return),benchmark_annualized_return:number(source.benchmark_annualized_return),annualized_excess_return:v};if(periods<30)reason=`${name}只有 ${periods} 个有效收益观测，少于 30 个。`;else if(v===null)reason=`${name}缺少可复算的年化超额收益。`;else excess.push(v)}if(reason===null&&excess.length!==3)reason='牛市、熊市、震荡三个阶段的数据不完整。'}
 const avg=excess.length===3?excess.reduce((s,x)=>s+x,0)/3:null;if(avg!==null)raw.equal_weight_mean_excess_return=avg
 dimensions.push(dimension('market_adaptability',scale(avg,-.2,.2),raw,reason),dimension('backtest_live_consistency',null,{},'缺少同一策略、同一口径和重叠区间的回测与实盘配对数据。'),dimension('strategy_purity',null,{},'缺少策略风格声明、基线和可核对的持仓观测数据。'))
 const complete=dimensions.every(d=>d.status==='evaluated')
 return {version:EVALUATION_VERSION,dimensions,complete,total_score:complete?roundEven(dimensions.reduce((s,d)=>s+d.score!,0)/dimensions.length,1):null}
}
