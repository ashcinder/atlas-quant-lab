import type { Adjustment, BacktestResult, CustomStrategySpec, Interval, Strategy, Trade } from '../types'
import type { AIStage, ComputeContext, MarketInput } from './model'
import { checkCancelled } from './model'
import { calculateIndicators } from './indicators'
import { calculateMetrics, drawdownSeries, regimeMetrics } from './metrics'
import { buildEvaluation } from './evaluation'
import { contributionSchedule, generateCustomTarget, generateTargetExposure, getStrategy, validateParams } from './strategies'
import { generatePythonTargets } from './pythonProgram'
import type { PythonInstruction } from './pythonProgram'
interface Pipeline {max_position:number;commission_rate:number;slippage_rate:number;max_participation_rate:number;ai_stages?:AIStage[]}
const closeEnough=(a:number,b:number,atol:number)=>Math.abs(a-b)<=atol+1e-5*Math.abs(b)
function requestNumber(request:Record<string,unknown>,key:string,fallback:number,min:number,max=Infinity,inclusiveMin=true,inclusiveMax=true):number{
 const raw=request[key]??fallback
 if(typeof raw==='boolean'||(typeof raw!=='number'&&typeof raw!=='string'))throw new Error(`${key} 必须为数字`)
 const n=Number(raw);if(!Number.isFinite(n)||(inclusiveMin?n<min:n<=min)||(inclusiveMax?n>max:n>=max))throw new Error(`${key} 超出有效范围`);return n
}
export async function runBacktest(request:Record<string,unknown>,market:MarketInput,context?:ComputeContext):Promise<BacktestResult>{
 checkCancelled(context)
 const bars=market.bars;if(bars.length<40)throw new Error('至少需要40根K线才能回测')
 for(let i=0;i<bars.length;i++){const b=bars[i];if(![b.time,b.open,b.high,b.low,b.close,b.volume].every(Number.isFinite)||b.open<=0||b.close<=0||b.high<=0||b.low<=0||b.volume<0||b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close)||(i>0&&b.time<=bars[i-1].time))throw new Error('行情存在缺失、非有限值、无效价格或重复/乱序时间，不能回测')}
 const interval=String(request.interval??market.interval??'1d') as Interval
 if(!['15m','1h','4h','1d','1wk'].includes(interval))throw new Error('不支持的K线周期')
 const adjustment=String(request.adjustment??market.adjustment??'auto') as Adjustment
 if(!['auto','raw','forward','backward'].includes(adjustment))throw new Error('不支持的复权方式')
 const initial=requestNumber(request,'initial_capital',100000,0,Infinity,false),spread=requestNumber(request,'spread_rate',.0005,0,.1)
 let maxPosition=requestNumber(request,'max_position',.95,0,1,false),commission=requestNumber(request,'commission_rate',.001,0,.1),slippage=requestNumber(request,'slippage_rate',.0005,0,.1),participation=requestNumber(request,'max_participation_rate',.01,0,1,false)
 const stop=request.stop_loss==null?null:requestNumber(request,'stop_loss',0,0,1,false,false),take=request.take_profit==null?null:requestNumber(request,'take_profit',0,0,Infinity,false)
 const pipeline=request.execution_pipeline as Pipeline|null|undefined
 let stages:AIStage[]=[]
 if(pipeline){maxPosition=Math.min(maxPosition,requestNumber(pipeline as unknown as Record<string,unknown>,'max_position',.5,0,1,false));commission=requestNumber(pipeline as unknown as Record<string,unknown>,'commission_rate',.001,0,.1);slippage=requestNumber(pipeline as unknown as Record<string,unknown>,'slippage_rate',.0005,0,.1);participation=requestNumber(pipeline as unknown as Record<string,unknown>,'max_participation_rate',.01,0,1,false);stages=(pipeline.ai_stages??[]).filter(s=>s.enabled);if(new Set(stages.map(s=>s.stage)).size!==stages.length)throw new Error('AI 阶段不能重复');if(stages.length&&!context?.aiReview)throw new Error('浏览器历史 AI 回测需要配置审核回调；本次计算未启动')}
 const strategyId=String(request.strategy_id??'sma_cross'),custom=request.custom_strategy as CustomStrategySpec|null|undefined,program=request.python_program as PythonInstruction[]|undefined,python=request.python_source!=null||program!=null
 if(request.python_source!=null&&!program)throw new Error('受限 Python 源码需先编译为已验证整数指令')
 if(python&&(custom||Object.keys((request.params??{}) as object).length||strategyId!=='python_bounded'))throw new Error('受限Python回测不接受其他策略或参数')
 let strategy:Strategy
 if(python)strategy={id:'python_bounded',name:'受限Python策略',category:'代码',description:'整数Python子集；本次回测不生成ZKP',suitable_for:'收盘价格与均线条件',risk_level:'高',mode:'single',parameters:[]}
 else if(custom)strategy={id:custom.id,name:custom.name,category:'自定义',description:custom.description,suitable_for:'由用户定义的条件组合',risk_level:'高',mode:'single',parameters:[]}
 else strategy=getStrategy(strategyId)
 if(strategy.mode!=='single')throw new Error('组合策略请使用组合回测接口')
 const scheduled=strategyId==='scheduled_dca'&&!custom,scheduleParams=scheduled?validateParams(strategyId,(request.params??{}) as Record<string,unknown>):{},due=scheduled?contributionSchedule(bars.map(b=>b.time),Number(scheduleParams.every),String(scheduleParams.unit),Number(scheduleParams.start_delay)):[]
 const {target,reasons}=python?generatePythonTargets(bars,program!,maxPosition):scheduled?{target:bars.map(()=>0),reasons:bars.map(()=>'固定金额定投')}:custom?generateCustomTarget(bars,custom,maxPosition):generateTargetExposure(bars,strategyId,(request.params??{}) as Record<string,unknown>,maxPosition)
 context?.progress?.(.05,'策略信号已计算')
 let cash=initial,quantity=0,averageCost=0,pendingTarget=0,pendingReason='初始状态',lastSignalTarget=0,activeTarget=0,rebalancing=false,aiReviews=0
 const trades:Trade[]=[],equityValues:number[]=[],exposures:number[]=[],aiStarted=performance.now(),benchmarkUnits=initial/bars[0].close
 for(let i=0;i<bars.length;i++){
  checkCancelled(context)
  const b=bars[i],open=b.open,preEquity=cash+quantity*open
  if(i>0){
   if(!closeEnough(pendingTarget,lastSignalTarget,1e-9)){lastSignalTarget=pendingTarget;activeTarget=pendingTarget;rebalancing=true}
   const currentFraction=preEquity>0?quantity*open/preEquity:0;let desiredQuantity=open>0?activeTarget*preEquity/open:quantity
   if(scheduled){rebalancing=due[i-1];const impact=1+slippage+spread/2,budget=Math.min(Number(scheduleParams.amount),Math.max(0,cash)),allowed=Math.max(0,maxPosition*preEquity-quantity*open),addition=rebalancing?Math.min(budget/(open*impact*(1+commission)),allowed/(open*impact)):0;desiredQuantity=quantity+addition;activeTarget=preEquity>0?desiredQuantity*open/preEquity:0;pendingReason='固定金额定投（下一根开盘）'}
   if(quantity>0&&averageCost>0){const previousClose=bars[i-1].close;if(stop&&previousClose<=averageCost*(1-stop)){activeTarget=0;rebalancing=true;desiredQuantity=0;pendingReason='收盘确认止损'}else if(take&&previousClose>=averageCost*(1+take)){activeTarget=0;rebalancing=true;desiredQuantity=0;pendingReason='收盘确认止盈'}}
   let delta=desiredQuantity-quantity
   const minChange=scheduled?.01:Math.max(preEquity*.001,1)
   if(context?.aiReview&&rebalancing&&Math.abs(delta*open)>=minChange){const forced=pendingReason==='收盘确认止损'||pendingReason==='收盘确认止盈'||(delta<0&&currentFraction>maxPosition);let scale=1
    for(const stage of stages){if(forced||(['entry','buy_size'].includes(stage.stage)&&delta<=0)||(stage.stage==='sell_size'&&delta>=0))continue;aiReviews++;if(performance.now()-aiStarted>75000)throw new Error('AI 审核超过本次回测时间预算；请缩短回测范围或减少启用阶段');if(aiReviews>200)throw new Error('本次 AI 回测超过 200 次审核；请缩短时间范围或减少 AI 阶段')
     const review=await context.aiReview({stage:stage.stage,side:delta>0?'buy':'sell',closed_bars:bars.slice(Math.max(0,i-20),i),signal:pendingReason,scale,authority:stage.authority,instructions:stage.instructions,timeout_ms:stage.timeout_ms});checkCancelled(context);if(review.status!=='inference_completed'||!Number.isFinite(review.scale))throw new Error(`AI 阶段 ${stage.stage} 调用失败，本次回测中止，请检查模型配置与连接`);let reviewed=review.scale;if(stage.authority==='reduce_only')reviewed=Math.max(reviewed,scale*(1-stage.max_reduction));scale=Math.min(scale,Math.max(0,reviewed))
    }delta*=scale
   }
   if(rebalancing&&Math.abs(delta*open)>=minChange&&(scheduled||Math.abs(currentFraction-activeTarget)>=.001)){
    const side=delta>0?'buy':'sell',impact=slippage+spread/2,executionPrice=open*(side==='buy'?1+impact:1-impact),maxNotional=b.volume>0?b.volume*open*participation:Infinity
    let tradeQuantity=Math.min(Math.abs(delta),maxNotional/executionPrice)
    if(side==='buy')tradeQuantity=Math.min(tradeQuantity,cash/(executionPrice*(1+commission)))
    let notional=tradeQuantity*executionPrice,fee=notional*commission;const slippageCost=tradeQuantity*Math.abs(executionPrice-open);let realizedPnl:number|null=null
    if(tradeQuantity>0){if(side==='buy'){const oldCost=averageCost*quantity;cash-=notional+fee;quantity+=tradeQuantity;averageCost=quantity>0?(oldCost+notional+fee)/quantity:0}else{tradeQuantity=Math.min(tradeQuantity,quantity);notional=tradeQuantity*executionPrice;fee=notional*commission;cash+=notional-fee;realizedPnl=(executionPrice-averageCost)*tradeQuantity-fee;quantity-=tradeQuantity;if(quantity<=1e-12){quantity=0;averageCost=0}}
     trades.push({id:trades.length+1,time:b.time,side,reason:pendingReason,price:executionPrice,quantity:tradeQuantity,notional,fee,slippage_cost:slippageCost,position_after:quantity,cash_after:cash,realized_pnl:realizedPnl})}
   }
   const post=cash+quantity*open,fraction=post>0?quantity*open/post:0,remaining=Math.abs(activeTarget*post-quantity*open)
   if(Math.abs(fraction-activeTarget)<.002||remaining<Math.max(post*.001,1))rebalancing=false
  }
  const equity=cash+quantity*b.close;equityValues.push(equity);exposures.push(equity>0?quantity*b.close/equity:0);pendingTarget=target[i];pendingReason=reasons[i]
  if(i%128===0){context?.progress?.(.05+.8*i/bars.length,'逐根执行与资金核算');await new Promise<void>(resolve=>setTimeout(resolve,0))}
 }
 const benchmark=bars.map(b=>b.close*benchmarkUnits),drawdown=drawdownSeries(equityValues),{metrics,warnings}=calculateMetrics(equityValues,benchmark,trades,exposures,interval,market.asset.asset_class,initial),regimes=regimeMetrics(equityValues,bars.map(b=>b.close),interval,market.asset.asset_class),evaluation=buildEvaluation(metrics,{start:bars[0].time,end:bars.at(-1)!.time,observation_count:bars.length-1},regimes)
 warnings.unshift('所有策略信号均在当前K线收盘后生成，并在下一根K线开盘执行。')
 if(scheduled)warnings.push('固定金额定投使用初始可用资金，金额包含手续费；资金不足、仓位上限或流动性限制可能导致部分成交或跳过。日历时间按数据 UTC 时间计算，非交易时段顺延；K线粒度过粗时合并错过的计划，不补做多笔成交。不模拟外部自动入金。')
 if(['dca','dip_dca'].includes(strategyId)&&!custom)warnings.push('此定投模型分期提高目标仓位，只使用初始资金，不模拟外部持续入金。达到仓位上限或投入次数限制后将停止增加目标仓位；没有新买点不代表策略停止运行。')
 if(pipeline)warnings.push(`已应用策略流程：仓位上限 ${(pipeline.max_position*100).toFixed(0)}%、手续费、滑点及成交参与率；AI 审核 ${aiReviews} 次。`)
 if(aiReviews)warnings.push('AI 为当前配置模型对历史数据的审核，不是历史时点模型重放；本报告不包含 AI 的 ZKP 或 TEE 证明。')
 if(['arithmetic_grid','geometric_grid'].includes(strategyId))warnings.push('网格使用收盘确认和保守成交顺序；单根K线内的真实价格路径无法由OHLC确定。')
 if(market.source==='demo')warnings.unshift('当前使用明确标记的演示数据，结果不能用于真实投资判断。')
 checkCancelled(context);context?.progress?.(1,'回测完成')
 const details=context?.includeDetails!==false
 return {run_id:crypto.randomUUID(),created_at:new Date().toISOString(),asset:market.asset,interval,adjustment,strategy,data_source:market.source,valuation_currency:market.asset.currency,source_note:market.source_note??null,bars:details?bars:[],indicators:details?calculateIndicators(bars):{},trades,equity:details?bars.map((b,i)=>({time:b.time,equity:equityValues[i],benchmark:benchmark[i],drawdown:Number.isFinite(drawdown[i])?drawdown[i]:0,exposure:exposures[i]})):[],metrics,regime_metrics:regimes,evaluation,warnings}
}
