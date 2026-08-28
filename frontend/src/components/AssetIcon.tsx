import { memo } from 'react'
import { Apple, BatteryCharging, Droplets, Landmark, TrendingUp } from 'lucide-react'
import type { Asset } from '../types'

interface Props {
  asset: Asset
}

const toneBySymbol: Record<string, string> = {
  'BTC-USD': 'bitcoin',
  'ETH-USD': 'ethereum',
  'SOL-USD': 'solana',
  AAPL: 'apple',
  MSFT: 'microsoft',
  NVDA: 'nvidia',
  SPY: 'spy',
  QQQ: 'qqq',
  TLT: 'bond',
  IEF: 'bond',
  GLD: 'gold',
  'GC=F': 'gold',
  'SI=F': 'silver',
  'CL=F': 'oil',
  'EURUSD=X': 'forex',
  'USDJPY=X': 'forex',
  '000001.SS': 'china-index',
  '510300.SS': 'china-etf',
  '600519.SS': 'moutai',
  '300750.SZ': 'catl',
  '0700.HK': 'tencent',
  '^HSI': 'hang-seng',
}

function BrandGlyph({ symbol }: { symbol: string }) {
  switch (symbol) {
    case 'BTC-USD':
      return <b className="asset-glyph asset-glyph-large">₿</b>
    case 'ETH-USD':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" opacity=".82" d="M12 2 6.7 12 12 9.1 17.3 12 12 2Z" /><path fill="currentColor" d="m6.7 13 5.3 8.9V10.1L6.7 13Zm5.3 8.9 5.3-8.9-5.3-2.9v11.8Z" /></svg>
    case 'SOL-USD':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m5.2 5.2 2-2h11.6l-2 2H5.2Zm0 6.1h11.6l2 2H7.2l-2-2Zm0 7.5 2 2h11.6l-2-2H5.2Z" /></svg>
    case 'AAPL':
      return <Apple aria-hidden="true" />
    case 'MSFT':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#f25022" d="M3 3h8v8H3z" /><path fill="#7fba00" d="M13 3h8v8h-8z" /><path fill="#00a4ef" d="M3 13h8v8H3z" /><path fill="#ffb900" d="M13 13h8v8h-8z" /></svg>
    case 'NVDA':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" strokeWidth="2" d="M3.5 12c3-4.2 8.1-6 13-3.9 1.7.7 3 1.9 4 3.3-2.7 3.5-7.4 5.2-11.6 3.3-1.3-.6-2.3-1.6-2.9-2.7 2.1-2.3 5.8-3.1 8.4-1.2 1.2.9 1.4 2.6.4 3.7" /><circle cx="12" cy="12.2" r="1.8" fill="currentColor" /></svg>
    case 'SPY':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" strokeWidth="2" d="M4 18 9 13l3 2 7-8" /><path fill="currentColor" d="m15 7 4-1v4l-4-3Z" /></svg>
    case 'QQQ':
      return <b className="asset-glyph">Q³</b>
    case 'TLT':
      return <b className="asset-glyph asset-glyph-small">20+</b>
    case 'IEF':
      return <b className="asset-glyph asset-glyph-small">7–10</b>
    case 'GLD':
    case 'GC=F':
      return <b className="asset-glyph">Au</b>
    case 'SI=F':
      return <b className="asset-glyph">Ag</b>
    case 'CL=F':
      return <Droplets aria-hidden="true" />
    case 'EURUSD=X':
      return <b className="asset-glyph asset-glyph-small">€/$</b>
    case 'USDJPY=X':
      return <b className="asset-glyph asset-glyph-small">$/¥</b>
    case '000001.SS':
      return <TrendingUp aria-hidden="true" />
    case '510300.SS':
      return <b className="asset-glyph asset-glyph-small">300</b>
    case '600519.SS':
      return <b className="asset-glyph">茅</b>
    case '300750.SZ':
      return <BatteryCharging aria-hidden="true" />
    case '0700.HK':
      return <b className="asset-glyph asset-glyph-large">T</b>
    case '^HSI':
      return <b className="asset-glyph">恒</b>
    default:
      return null
  }
}

function fallbackTone(assetClass: string) {
  if (assetClass === 'crypto') return 'crypto'
  if (assetClass === 'commodity') return 'commodity'
  if (assetClass === 'forex') return 'forex'
  if (assetClass === 'etf' || assetClass === 'index') return 'fund'
  return 'equity'
}

function fallbackText(symbol: string) {
  return symbol.replace(/[^A-Z0-9]/gi, '').slice(0, 2).toUpperCase() || '·'
}

export const AssetIcon = memo(function AssetIcon({ asset }: Props) {
  const tone = toneBySymbol[asset.symbol] ?? fallbackTone(asset.asset_class)
  const brand = <BrandGlyph symbol={asset.symbol} />
  return (
    <span className={`asset-icon asset-icon--${tone}`} title={`${asset.name} · ${asset.symbol}`} aria-hidden="true">
      {brand ?? (asset.asset_class === 'etf' || asset.asset_class === 'index'
        ? <Landmark aria-hidden="true" />
        : <b className="asset-glyph asset-glyph-small">{fallbackText(asset.symbol)}</b>)}
    </span>
  )
})
