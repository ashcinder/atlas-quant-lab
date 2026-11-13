import type { Bar, IndicatorPoint } from '../types'
export const finite = (v: number): number | null => Number.isFinite(v) ? v : null
export const mean = (values: number[]): number => values.length ? values.reduce((a,b)=>a+b,0)/values.length : NaN
export function std(values: number[], ddof = 1): number {
  if (values.length <= ddof) return NaN
  const m = mean(values)
  return Math.sqrt(values.reduce((s,x)=>s+(x-m)**2,0)/(values.length-ddof))
}
export function rolling(values: number[], period: number, operation: 'mean'|'std'|'min'|'max'='mean', minPeriods = period): number[] {
  return values.map((_,i)=> {
    const slice = values.slice(Math.max(0,i-period+1),i+1).filter(Number.isFinite)
    if (slice.length < minPeriods) return NaN
    return operation==='mean' ? mean(slice) : operation==='std' ? std(slice) : operation==='min' ? Math.min(...slice) : Math.max(...slice)
  })
}
/** pandas ewm(adjust=False, ignore_na=False), including missing observations. */
export function ewm(values: number[], alpha: number, minPeriods = 0): number[] {
  let state = NaN, oldWeight = 1, count = 0
  return values.map(value => {
    if (Number.isFinite(value)) count++
    if (Number.isFinite(state)) {
      oldWeight *= 1-alpha
      if (Number.isFinite(value)) {
        if (state !== value) state = (oldWeight*state+alpha*value)/(oldWeight+alpha)
        oldWeight = 1
      }
    } else if (Number.isFinite(value)) state=value
    return count>=Math.max(minPeriods,1) ? state : NaN
  })
}
export const ema = (values:number[],span:number):number[] => ewm(values,2/(span+1),span)
export function rsi(close:number[],period=14):number[] {
  const delta=close.map((v,i)=>i?v-close[i-1]:NaN)
  const gain=ewm(delta.map(v=>Math.max(v,0)),1/period)
  const loss=ewm(delta.map(v=>-Math.min(v,0)),1/period)
  return close.map((_,i)=>loss[i]===0||!Number.isFinite(loss[i])||!Number.isFinite(gain[i])?50:100-100/(1+gain[i]/loss[i]))
}
export function atr(bars:Bar[],period=14):number[] {
  return ewm(bars.map((b,i)=>Math.max(b.high-b.low,i?Math.abs(b.high-bars[i-1].close):0,i?Math.abs(b.low-bars[i-1].close):0)),1/period,period)
}
export function pctChange(values:number[],period=1):number[] { return values.map((v,i)=>i>=period?v/values[i-period]-1:NaN) }
export function indicatorValues(bars:Bar[]):Record<string,number[]> {
  const close=bars.map(b=>b.close), middle=rolling(close,20), deviation=rolling(close,20,'std')
  const e12=ema(close,12),e26=ema(close,26),macd=e12.map((v,i)=>v-e26[i]),signal=ema(macd,9)
  const lows=rolling(bars.map(b=>b.low),9,'min'), highs=rolling(bars.map(b=>b.high),9,'max')
  const rsv=close.map((v,i)=>highs[i]===lows[i]?NaN:(v-lows[i])/(highs[i]-lows[i])*100)
  const k=ewm(rsv,1/3),d=ewm(k,1/3)
  return {sma20:middle,sma50:rolling(close,50),ema12:e12,ema26:e26,macd,macd_signal:signal,macd_hist:macd.map((v,i)=>v-signal[i]),rsi14:rsi(close),boll_mid:middle,boll_upper:middle.map((v,i)=>v+2*deviation[i]),boll_lower:middle.map((v,i)=>v-2*deviation[i]),atr14:atr(bars),kdj_k:k,kdj_d:d,kdj_j:k.map((v,i)=>3*v-2*d[i])}
}
export function calculateIndicators(bars:Bar[],maximumPoints=Infinity):Record<string,IndicatorPoint[]> {
  return Object.fromEntries(Object.entries(indicatorValues(bars)).map(([key,values])=>[key,values.slice(Math.max(0,bars.length-maximumPoints)).map((value,i)=>({time:bars[Math.max(0,bars.length-maximumPoints)+i].time,value:finite(value)}))]))
}
