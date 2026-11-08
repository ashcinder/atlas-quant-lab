import type { Bar, Strategy, CustomStrategySpec, IndicatorSpec, RuleNode } from '../types'
import { STRATEGIES } from './catalog'
import { ema, rsi, rolling, pctChange } from './indicators'
export type Params=Record<string,number|string|boolean>
export function getStrategy(id:string):Strategy {const strategy=STRATEGIES.find(s=>s.id===id);if(!strategy)throw new Error(`未知策略: ${id}`);return structuredClone(strategy)}
export function defaultParams(id:string):Params {return Object.fromEntries(getStrategy(id).parameters.map(p=>[p.key,p.default]))}
export function validateParams(id:string,supplied:Record<string,unknown>):Params {
 const strategy=getStrategy(id),definitions=Object.fromEntries(strategy.parameters.map(p=>[p.key,p])),unknown=Object.keys(supplied).filter(k=>!definitions[k]).sort()
 if(unknown.length)throw new Error(`策略包含未知参数: ${unknown.join(', ')}`)
 const result=defaultParams(id)
 for(const [key,raw] of Object.entries(supplied)){const p=definitions[key];if(p.kind==='boolean'){if(typeof raw!=='boolean')throw new Error(`${p.label} 必须为布尔值`);result[key]=raw}
 else if(p.kind==='select'){if(typeof raw!=='string'||!p.options?.some(o=>o.value===raw))throw new Error(`${p.label} 不是有效选项`);result[key]=raw}
 else {if(typeof raw==='boolean'||raw===null||(typeof raw!=='string'&&typeof raw!=='number')||(typeof raw==='string'&&!raw.trim()))throw new Error(`${p.label} 必须为数字`);const n=Number(raw);if(!Number.isFinite(n))throw new Error(`${p.label} 必须为有限数字`);if(p.minimum!==null&&n<p.minimum)throw new Error(`${p.label} 不能小于 ${p.minimum}`);if(p.maximum!==null&&n>p.maximum)throw new Error(`${p.label} 不能大于 ${p.maximum}`);if(p.kind==='integer'&&!Number.isInteger(n))throw new Error(`${p.label} 必须为整数`);result[key]=n}}
 return result
}
export function holdState(entries:boolean[],exits:boolean[],amount=1):number[]{let state=0;return entries.map((e,i)=>{if(e)state=amount;if(exits[i])state=0;return state})}
export function confirmed(mask:boolean[],bars:number):boolean[]{const n=Math.max(1,Math.trunc(bars));let count=0;return mask.map(v=>{count=v?count+1:0;return count>=n})}
export function generateTargetExposure(bars:Bar[],id:string,params:Record<string,unknown>,maxPosition:number):{target:number[];reasons:string[]} {
 const p=validateParams(id,params),n=(key:string)=>Number(p[key]),close=bars.map(b=>b.close),reasons=bars.map(()=>'等待信号');let target=bars.map(()=>0)
 if(id==='sma_cross'||id==='ema_cross'){
  const fast=n('fast'),slow=n('slow');if(fast>=slow)throw new Error('快速周期必须小于慢速周期')
  const f=id==='sma_cross'?rolling(close,fast):ema(close,fast),s=id==='sma_cross'?rolling(close,slow):ema(close,slow),filter=n('trend_filter'),trend=filter>0?rolling(close,filter):close
  target=confirmed(close.map((v,i)=>f[i]>s[i]*(1+n('min_gap'))&&(filter<=0||v>trend[i])),n('confirm_bars')).map(v=>v?maxPosition:0)
  target.forEach((v,i)=>reasons[i]=v>0?'快速均线位于慢速均线上方':'均线差距、确认期或趋势过滤未满足')
 }else if(id==='macd'){
  if(n('fast')>=n('slow'))throw new Error('快速周期必须小于慢速周期')
  const f=ema(close,n('fast')),s=ema(close,n('slow')),m=f.map((v,i)=>v-s[i]),sig=ema(m,n('signal'))
  target=confirmed(m.map((v,i)=>v>sig[i]&&(!p.zero_line_filter||v>0)),n('confirm_bars')).map(v=>v?maxPosition:0)
  target.forEach((v,i)=>reasons[i]=v>0?'MACD上穿并保持在信号线上方':'MACD未确认多头')
 }else if(id==='rsi_reversal'){
  const o=rsi(close,n('period'));target=holdState(confirmed(o.map(v=>v<n('entry')),n('entry_confirm')),confirmed(o.map(v=>v>n('exit')),n('exit_confirm')),maxPosition)
  o.forEach((v,i)=>{if(v<n('entry'))reasons[i]='RSI进入超卖区';if(v>n('exit'))reasons[i]='RSI恢复至退出阈值'})
 }else if(id==='bollinger'){
  const m=rolling(close,n('period')),s=rolling(close,n('period'),'std'),lo=m.map((v,i)=>v-n('std_dev')*s[i]),hi=m.map((v,i)=>v+n('std_dev')*s[i]),entry=close.map((v,i)=>v<lo[i]&&(hi[i]-lo[i])/(m[i]||NaN)>=n('min_bandwidth')),exit=close.map((v,i)=>v>=lo[i]+(m[i]-lo[i])*n('exit_ratio'))
  target=holdState(entry,exit,maxPosition);entry.forEach((v,i)=>{if(v)reasons[i]='价格跌破下轨且带宽满足过滤';if(exit[i])reasons[i]='价格恢复至设定退出位置'})
 }else if(id==='breakout'){
  const hi=rolling(bars.map(b=>b.high),n('entry_lookback'),'max'),lo=rolling(bars.map(b=>b.low),n('exit_lookback'),'min'),entry=confirmed(close.map((v,i)=>i>0&&v>hi[i-1]*(1+n('breakout_buffer'))),n('confirm_bars')),exit=close.map((v,i)=>i>0&&v<lo[i-1])
  target=holdState(entry,exit,maxPosition);entry.forEach((v,i)=>{if(v)reasons[i]='收盘确认突破缓冲后的通道高点';if(exit[i])reasons[i]='收盘跌破退出通道'})
 }else if(id==='momentum'){
  const m=rolling(pctChange(close,n('lookback')),n('smoothing'));target=holdState(m.map(v=>v>n('threshold')),m.map(v=>v<n('exit_threshold')),maxPosition);target.forEach((v,i)=>reasons[i]=v>0?'阶段动量超过阈值':'阶段动量不足')
 }else if(id==='dca'||id==='dip_dca'){
  const every=n('every_bars'),increment=n('amount_pct'),delay=Number(p.start_delay??0),limit=Number(p.max_contributions??0),peak=rolling(close,Number(p.drawdown_lookback??Math.max(20,every)),'max',1);let count=0,running=0
  target=close.map((v,i)=>{if(i>=delay&&(i-delay)%every===0&&(!limit||count<limit)){let add=increment;if(id==='dip_dca'&&v/peak[i]-1<=-n('dip_threshold')){add*=n('dip_multiplier');reasons[i]='阶段回撤触发加倍定投'}else reasons[i]='定期投入';running=Math.min(maxPosition,running+add);count++}return running})
 }else if(id==='arithmetic_grid'||id==='geometric_grid'){
  const lower=n('lower'),upper=n('upper'),levels=n('levels'),base=n('base_position');if(lower<=0||upper<=lower)throw new Error('网格上限必须大于下限，且下限必须为正')
  target=close.map(v=>{const clamped=Math.max(lower,Math.min(upper,v)),raw=id==='geometric_grid'?(Math.log(upper)-Math.log(clamped))/(Math.log(upper)-Math.log(lower)):(upper-clamped)/(upper-lower),stepped=Math.ceil(raw*levels)/levels;return (base+(1-base)*Math.max(0,Math.min(1,stepped)))*maxPosition});target.forEach((v,i)=>{if(i&&v>target[i-1])reasons[i]='价格下穿网格，增加仓位';if(i&&v<target[i-1])reasons[i]='价格上穿网格，减少仓位'})
 }else if(id==='martingale'){
  const o=rsi(close,n('rsi_period')),holding=holdState(o.map(v=>v<n('entry_rsi')),o.map(v=>v>=55)),peak=rolling(close,20,'max',1)
  target=close.map((v,i)=>holding[i]>0?n('base_position')*n('multiplier')**Math.trunc(Math.max(0,Math.min(4,-(v/peak[i]-1)/n('drawdown_step')))):0);target.forEach((v,i)=>reasons[i]=v>0?'回撤层级提高马丁目标仓位':'RSI退出马丁持仓')
 }else if(id==='anti_martingale'){
  const m=pctChange(close,n('lookback'));target=m.map(v=>v>0?n('base_position')*n('multiplier')**Math.trunc(Math.max(0,Math.min(n('max_levels'),Math.max(0,v)/n('level_step')))):0);target.forEach((v,i)=>reasons[i]=v>0?'盈利趋势提高反马丁目标仓位':'动量转弱，降低仓位')
 }else throw new Error(`策略 ${id} 不支持单标的回测`)
 return {target:target.map(v=>Number.isFinite(v)?Math.max(0,Math.min(maxPosition,v)):0),reasons}
}
export function contributionSchedule(times:number[],every:number,unit:string,delay=0):boolean[] {
 if(!Number.isInteger(every)||every<1||!Number.isInteger(delay)||delay<0||!['hours','days','weeks','months'].includes(unit))throw new Error('定投间隔必须为正数，延迟不能为负，单位必须有效')
 const result=times.map(()=>false);if(delay>=times.length)return result;const anchor=new Date(times[delay]*1000)
 const due=(count:number):number=>{if(unit!=='months')return times[delay]+count*every*({hours:3600,days:86400,weeks:604800}[unit]!)
 const date=new Date(anchor),month=anchor.getUTCMonth()+count*every;date.setUTCDate(1);date.setUTCMonth(month);const last=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth()+1,0)).getUTCDate();date.setUTCDate(Math.min(anchor.getUTCDate(),last));return date.getTime()/1000}
 let count=0,next=due(0);for(let i=delay;i<times.length;i++){if(times[i]>=next){result[i]=true;while(next<=times[i])next=due(++count)}}return result
}
function indicatorSeries(bars:Bar[],spec:IndicatorSpec):number[]{const close=bars.map(b=>b.close),period=spec.period||14
 if(['open','high','low','close','volume'].includes(spec.field))return bars.map(b=>b[spec.field as keyof Omit<Bar,'time'>])
 if(spec.field==='sma')return rolling(close,period);if(spec.field==='ema')return ema(close,period);if(spec.field==='rsi')return rsi(close,period)
 if(spec.field==='macd'||spec.field==='macd_signal'){const f=ema(close,12),s=ema(close,26),m=f.map((v,i)=>v-s[i]);return spec.field==='macd'?m:ema(m,9)}
 if(spec.field==='boll_upper'||spec.field==='boll_lower'){const m=rolling(close,period),width=rolling(close,period,'std');return m.map((v,i)=>v+(spec.field==='boll_upper'?2:-2)*width[i])}
 if(spec.field==='roc')return pctChange(close,period);throw new Error(`不支持的指标: ${spec.field}`)
}
export function validateRuleComplexity(node:RuleNode,depth=1):number{
 if(depth>5)throw new Error('自定义策略条件最多嵌套5层')
 if(!node||!['condition','group'].includes(node.kind)||!Array.isArray(node.children??[])||(node.children??[]).length>20)throw new Error('自定义策略条件结构无效')
 if(node.kind==='condition'){
  if(!node.left||!node.operator||!['gt','gte','lt','lte','crosses_above','crosses_below'].includes(node.operator)||(node.children??[]).length||(node.right_indicator==null)===(node.right_value==null))throw new Error('比较条件必须包含左值和操作符，且只能设置一种右值')
  if(node.right_value!=null&&(typeof node.right_value!=='number'||!Number.isFinite(node.right_value)))throw new Error('比较条件右值必须为有限数字')
  for(const indicator of [node.left,node.right_indicator])if(indicator){if(!['open','high','low','close','volume','sma','ema','rsi','macd','macd_signal','boll_upper','boll_lower','roc'].includes(indicator.field)||(indicator.period!=null&&(!Number.isInteger(indicator.period)||indicator.period<2||indicator.period>500)))throw new Error('指标或指标周期无效')}
  return 1
 }
 if(!['all','any'].includes(node.combinator??'')||!node.children?.length||node.left||node.operator||node.right_indicator||node.right_value!=null)throw new Error('条件组必须包含逻辑关系和子条件，不能包含比较表达式')
 const count=1+node.children.reduce((s,c)=>s+validateRuleComplexity(c,depth+1),0);if(count>50)throw new Error('自定义策略最多包含50个条件节点');return count
}
export function evaluateRule(bars:Bar[],node:RuleNode):boolean[]{
 if(node.kind==='group'){const children=(node.children??[]).map(c=>evaluateRule(bars,c));return bars.map((_,i)=>children.length>0&&(node.combinator==='all'?children.every(v=>v[i]):children.some(v=>v[i])))}
 if(!node.left||!node.operator)throw new Error('自定义比较条件不完整');const left=indicatorSeries(bars,node.left),right=node.right_indicator?indicatorSeries(bars,node.right_indicator):bars.map(()=>Number(node.right_value))
 return left.map((v,i)=>{const r=right[i];switch(node.operator){case'gt':return v>r;case'gte':return v>=r;case'lt':return v<r;case'lte':return v<=r;case'crosses_above':return i>0&&v>r&&left[i-1]<=right[i-1];case'crosses_below':return i>0&&v<r&&left[i-1]>=right[i-1];default:return false}})
}
export function generateCustomTarget(bars:Bar[],spec:CustomStrategySpec,maxPosition:number):{target:number[];reasons:string[]}{if(!Number.isFinite(spec.target_position)||spec.target_position<=0||spec.target_position>1)throw new Error('自定义策略目标仓位必须大于0且不超过1');validateRuleComplexity(spec.entry);validateRuleComplexity(spec.exit);const entry=evaluateRule(bars,spec.entry),exit=evaluateRule(bars,spec.exit),target=holdState(entry,exit,Math.min(spec.target_position,maxPosition));return {target:target.map(v=>Math.max(0,Math.min(v,maxPosition))),reasons:bars.map((_,i)=>exit[i]?`${spec.name}：退出条件成立`:entry[i]?`${spec.name}：入场条件成立`:'等待自定义信号')}}
