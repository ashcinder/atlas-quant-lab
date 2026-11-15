import type { Bar, MarketData } from './types'
export function retainChartHistory(current: MarketData | null, backtest: MarketData, preserveRecent = false): MarketData {
  if (!current || current.asset.symbol !== backtest.asset.symbol || current.asset.asset_class !== backtest.asset.asset_class || current.interval !== backtest.interval || current.adjustment !== backtest.adjustment || current.source.split(':')[0] !== backtest.source.split(':')[0]) return backtest
  const currentFeed = current.chart_feed
  const keepRecent = preserveRecent && currentFeed && !currentFeed.used_as_fallback
    && !backtest.chart_feed && (current.bars.at(-1)?.time ?? 0) > (backtest.bars.at(-1)?.time ?? 0)
  const previous = currentFeed && !currentFeed.used_as_fallback && !keepRecent
    && currentFeed.source.split(':')[0] !== backtest.chart_feed?.source.split(':')[0]
    ? current.bars.filter(bar => bar.time < currentFeed.start)
    : current.bars
  const merged = new Map<number, Bar>(previous.map(bar => [bar.time, bar]))
  backtest.bars.forEach(bar => merged.set(bar.time, bar))
  const bars = [...merged.values()].sort((a, b) => a.time - b.time)
  if (keepRecent) {
    return { ...backtest, bars, chart_feed: currentFeed, fetched_at: current.fetched_at,
      last_bar_time: bars.at(-1)!.time, is_stale: true, cache_hit: true }
  }
  return { ...backtest, bars }
}
export function outsideBacktest(time: number, start?: number, end?: number) {
  return (start != null && time < start) || (end != null && time > end)
}

const minuteLengths: Partial<Record<MarketData['interval'], number>> = {
  '1m': 60, '5m': 300, '15m': 900, '1h': 3600,
}

export function canExtendPublishedChart(interval: MarketData['interval']): boolean {
  return minuteLengths[interval] !== undefined
}

export function extendPublishedChart(history: MarketData, recent: MarketData): MarketData {
  const step = minuteLengths[history.interval]
  const latest = history.bars.at(-1)
  if (!step || !latest || history.source !== 'hf-ohlcv' || history.adjustment !== 'raw'
    || recent.adjustment !== 'raw' || history.interval !== recent.interval
    || history.asset.symbol !== recent.asset.symbol || history.asset.exchange !== recent.asset.exchange
    || !['sina', 'eastmoney'].includes(recent.source.split(':')[0])) return history

  const tail = recent.bars.filter(bar => bar.time > latest.time)
  if (!tail.length) return history
  const lastLocal = (latest.time + 8 * 3600) % 86400
  const nextLocal = (tail[0].time + 8 * 3600) % 86400
  const dayGap = Math.floor((tail[0].time + 8 * 3600) / 86400) - Math.floor((latest.time + 8 * 3600) / 86400)
  const lunchBreak = lastLocal + step === 11.5 * 3600 && nextLocal === 13 * 3600
  const hasGap = dayGap > 3 || (dayGap === 0 && !lunchBreak && tail[0].time - latest.time > step)
  return {
    ...history, bars: [...history.bars, ...tail], last_bar_time: tail.at(-1)!.time,
    fetched_at: recent.fetched_at, is_stale: recent.is_stale, cache_hit: recent.cache_hit,
    // Chart pagination and backtests still resolve the original published source.
    chart_feed: { source: recent.source, start: tail[0].time,
      has_gap: hasGap, used_as_fallback: false },
  }
}
