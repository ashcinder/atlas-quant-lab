import type { Asset, DataSource } from './types'
export function chartHistorySource(source: DataSource, provider?: string): DataSource {
  if ((provider === 'hf-unverified' || provider === 'hf-ohlcv')) return 'huggingface'
  if (provider === 'baostock-disputed') return 'baostock'
  if (provider === 'binance') return 'binance'
  return source
}
export function supportsMinuteBars(asset: Pick<Asset, 'asset_class' | 'exchange'> | null | undefined): boolean {
  return asset?.asset_class === 'crypto' || (asset?.asset_class === 'equity' && ['SSE', 'SZSE'].includes(asset.exchange))
}

export function supportsHuggingFaceHistory(
  asset: Pick<Asset, 'asset_class' | 'exchange' | 'symbol'> | null | undefined,
  interval?: string,
): boolean {
  return asset?.asset_class === 'equity'
    && ['SSE', 'SZSE'].includes(asset.exchange)
    && /^\d{6}\.(SS|SZ)$/.test(asset.symbol)
    && (interval === undefined || ['1m', '5m', '15m', '1h', '4h', '1d', '1wk'].includes(interval))
}
