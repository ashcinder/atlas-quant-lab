import type { Bar, MarketData } from './types'
export function retainChartHistory(current: MarketData | null, backtest: MarketData): MarketData {
  if (!current || current.asset.symbol !== backtest.asset.symbol || current.interval !== backtest.interval || current.source.split(':')[0] !== backtest.source.split(':')[0]) return backtest
  const merged = new Map<number, Bar>(current.bars.map(bar => [bar.time, bar]))
  backtest.bars.forEach(bar => merged.set(bar.time, bar))
  return { ...current, bars: [...merged.values()].sort((a,b)=>a.time-b.time) }
}
export function outsideBacktest(time: number, start?: number, end?: number) {
  return (start != null && time < start) || (end != null && time > end)
}
