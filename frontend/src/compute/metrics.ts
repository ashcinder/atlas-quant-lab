import type { Interval, Trade } from '../types'
import type { MetricMap, RegimeMap } from './model'
import { finite, mean, std, rolling, pctChange } from './indicators'
export function periodsPerYear(interval:Interval,assetClass:string,exchange?:string):number {
  if(exchange && ['SSE','SZSE'].includes(exchange))return ({'1m':240,'5m':48,'15m':16,'1h':4,'4h':1,'1d':1,'1wk':52/252})[interval]*252
  const crypto=assetClass==='crypto', days=crypto?365:252
  const factors:Record<Interval,number>={'1m':days*1440,'5m':days*288,'15m':days*(crypto?96:26),'1h':days*(crypto?24:6.5),'4h':days*(crypto?6:1.625),'1d':days,'1wk':52}
  return factors[interval]
}
export function drawdownSeries(equity:number[]):number[] { let peak=-Infinity;return equity.map(x=>{peak=Math.max(peak,x);return peak?x/peak-1:NaN}) }
export function maxDrawdownDuration(values:number[]):number {let current=0,longest=0;for(const v of values){current=v<0?current+1:0;longest=Math.max(longest,current)}return longest}
export function percentile(values:number[],q:number):number {
  if(!values.length)return NaN
  const sorted=[...values].sort((a,b)=>a-b),i=(sorted.length-1)*q,lo=Math.floor(i),f=i-lo
  return sorted[lo]*(1-f)+sorted[Math.ceil(i)]*f
}
// Lanczos log-gamma and continued-fraction incomplete beta produce the same
// two-sided Student t test as scipy.stats.ttest_1samp (without a runtime dep).
function logGamma(z:number):number {
 const c=[676.5203681218851,-1259.1392167224028,771.32342877765313,-176.61502916214059,12.507343278686905,-.13857109526572012,9.9843695780195716e-6,1.5056327351493116e-7]
 if(z<.5)return Math.log(Math.PI)-Math.log(Math.sin(Math.PI*z))-logGamma(1-z)
 z--;let x=.99999999999980993;for(let i=0;i<c.length;i++)x+=c[i]/(z+i+1)
 const t=z+c.length-.5;return .5*Math.log(2*Math.PI)+(z+.5)*Math.log(t)-t+Math.log(x)
}
function betaFraction(a:number,b:number,x:number):number {
 const qab=a+b,qap=a+1,qam=a-1,tiny=1e-300;let c=1,d=1-qab*x/qap
 if(Math.abs(d)<tiny)d=tiny;d=1/d;let h=d
 for(let m=1;m<=300;m++){const m2=2*m;let aa=m*(b-m)*x/((qam+m2)*(a+m2));d=1+aa*d;if(Math.abs(d)<tiny)d=tiny;c=1+aa/c;if(Math.abs(c)<tiny)c=tiny;d=1/d;h*=d*c;aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2));d=1+aa*d;if(Math.abs(d)<tiny)d=tiny;c=1+aa/c;if(Math.abs(c)<tiny)c=tiny;d=1/d;const delta=d*c;h*=delta;if(Math.abs(delta-1)<3e-14)break}
 return h
}
function regularizedBeta(x:number,a:number,b:number):number {
 if(x<=0)return 0;if(x>=1)return 1
 const front=Math.exp(logGamma(a+b)-logGamma(a)-logGamma(b)+a*Math.log(x)+b*Math.log1p(-x))
 return x<(a+1)/(a+b+2)?front*betaFraction(a,b,x)/a:1-front*betaFraction(b,a,1-x)/b
}
export function calculateMetrics(equity:number[],benchmark:number[],trades:Trade[],exposure:number[],interval:Interval,assetClass:string,initialCapital:number,exchange?:string):{metrics:MetricMap;warnings:string[]} {
 const factor=periodsPerYear(interval,assetClass,exchange),raw=pctChange(equity),benchRaw=pctChange(benchmark),returns=raw.filter(Number.isFinite),drawdown=drawdownSeries(equity)
 const periods=Math.max(returns.length,1),total=equity.at(-1)!/initialCapital-1,years=periods/factor,cagr=equity.at(-1)!>0?(equity.at(-1)!/initialCapital)**(1/years)-1:NaN
 const volatility=returns.length>1?std(returns)*Math.sqrt(factor):0,annual=returns.length?mean(returns)*factor:0,sharpe=volatility>0?annual/volatility:NaN
 const negative=returns.filter(x=>x<0),downside=negative.length>1?std(negative)*Math.sqrt(factor):NaN,sortino=downside>0?annual/downside:NaN
 const maxDD=drawdown.reduce((minimum,value)=>Number.isFinite(value)?Math.min(minimum,value):minimum,Infinity),calmar=maxDD<0&&Number.isFinite(cagr)?cagr/Math.abs(maxDD):NaN,var95=returns.length?-percentile(returns,.05):NaN,tail=returns.filter(x=>x<=-var95)
 const paired=raw.map((v,i)=>[v,benchRaw[i]]).filter(v=>v.every(Number.isFinite));let information=NaN,beta=NaN
 if(paired.length>1){const a=paired.map(x=>x[0]-x[1]),tracking=std(a)*Math.sqrt(factor);information=tracking>0?mean(a)*factor/tracking:NaN;const bv=paired.map(x=>x[1]),bm=mean(bv),am=mean(paired.map(x=>x[0])),variance=std(bv)**2;beta=variance>0?paired.reduce((s,x)=>s+(x[0]-am)*(x[1]-bm),0)/(paired.length-1)/variance:NaN}
 const sells=trades.filter(t=>t.side==='sell'&&t.realized_pnl!==null),pnls=sells.map(t=>t.realized_pnl!),wins=pnls.filter(x=>x>0),losses=pnls.filter(x=>x<0),sum=(v:number[])=>v.reduce((a,b)=>a+b,0),fees=sum(trades.map(t=>t.fee)),notional=sum(trades.map(t=>t.notional))
 const t=returns.length>=3?mean(returns)/(std(returns)/Math.sqrt(returns.length)):NaN,p=returns.length>=3?regularizedBeta((returns.length-1)/(returns.length-1+t*t),(returns.length-1)/2,.5):NaN
 const benchmarkReturn=benchmark.at(-1)!/benchmark[0]-1
 const metrics:MetricMap={total_return:finite(total),cagr:finite(cagr),benchmark_return:finite(benchmarkReturn),excess_return:finite(total-benchmarkReturn),annual_volatility:finite(volatility),max_drawdown:finite(maxDD),max_drawdown_duration:maxDrawdownDuration(drawdown),var_95:finite(var95),cvar_95:finite(-mean(tail)),sharpe:finite(sharpe),sortino:finite(sortino),calmar:finite(calmar),information_ratio:finite(information),beta:finite(beta),trade_count:trades.length,round_trip_count:sells.length,win_rate:finite(pnls.length?wins.length/pnls.length:NaN),profit_factor:finite(losses.length?sum(wins)/Math.abs(sum(losses)):wins.length?Infinity:NaN),expectancy:finite(mean(pnls)),fees_paid:finite(fees),cost_drag:finite(fees/initialCapital),turnover:finite(notional/initialCapital),average_exposure:finite(mean(exposure)),return_t_stat:finite(t),return_p_value:finite(p)}
 const warnings:string[]=[]
 if(sells.length<30)warnings.push(`完整交易仅 ${sells.length} 笔，少于30笔，统计结论可信度有限。`)
 if(Number.isFinite(sharpe)&&Math.abs(sharpe)>3)warnings.push('Sharpe绝对值超过3，请重点检查过拟合、未来数据和样本长度。')
 if(years<3)warnings.push('回测历史不足3年，可能只覆盖单一市场阶段。')
 if(fees>Math.abs(equity.at(-1)!-initialCapital)&&fees>0)warnings.push('交易成本超过策略净盈利绝对值，策略对费用高度敏感。')
 return {metrics,warnings}
}
export function classifyRegimes(close:number[]):Array<string|null> {
 const sma50=rolling(close,50),sma200=rolling(close,200),vol=rolling(pctChange(close),20,'std'),avg=rolling(vol,120,'mean',40)
 return close.map((v,i)=>i<200?null:v>sma50[i]&&sma50[i]>sma200[i]&&vol[i]<=avg[i]?'牛市':v<sma50[i]&&sma50[i]<sma200[i]?'熊市':'震荡')
}
export function regimeMetrics(equity:number[],close:number[],interval:Interval,assetClass:string,exchange?:string):RegimeMap {
 const r=pctChange(equity),b=pctChange(close),regimes=classifyRegimes(close),factor=periodsPerYear(interval,assetClass,exchange),output:RegimeMap={}
 for(const name of ['牛市','熊市','震荡']){const values=r.filter((v,i)=>regimes[i]===name&&Number.isFinite(v)&&Number.isFinite(b[i])),bench=b.filter((v,i)=>regimes[i]===name&&Number.isFinite(v)&&Number.isFinite(r[i])),growth=(v:number[])=>v.reduce((s,x)=>s*(1+x),1),ann=(v:number[])=>v.length&&growth(v)>0?growth(v)**(factor/v.length)-1:NaN,a=ann(values),ba=ann(bench)
 output[name]={periods:values.length,total_return:finite(values.length?growth(values)-1:NaN),benchmark_total_return:finite(bench.length?growth(bench)-1:NaN),average_return:finite(mean(values)),win_period_rate:finite(values.length?values.filter(v=>v>0).length/values.length:NaN),annualized_return:finite(a),benchmark_annualized_return:finite(ba),annualized_excess_return:finite(a-ba)}}
 return output
}
