import { memo, useState } from 'react'
import { Droplets, Landmark } from 'lucide-react'
import type { Asset } from '../types'
import { ASSET_BRANDS } from '../assetBrands'

const labels: Record<string, string> = {
  'GC=F': 'Au', 'SI=F': 'Ag', 'EURUSD=X': '€/$', 'USDJPY=X': '$/¥',
  '000001.SS': '上证',
}

export const AssetIcon = memo(function AssetIcon({ asset }: { asset: Asset }) {
  const [failedSource, setFailedSource] = useState<string | null>(null)
  const brand = ASSET_BRANDS[asset.symbol]
  const source = brand ? `/asset-icons/${brand}.svg` : null
  const showImage = source !== null && source !== failedSource
  const label = labels[asset.symbol] ?? (/\p{Script=Han}/u.test(asset.name) ? asset.name.slice(0, 2) : asset.symbol.replace(/[^A-Z0-9]/gi, '').slice(0, 2).toUpperCase())
  return (
    <span className={`asset-icon${showImage ? ' asset-icon--brand' : ''}`} title={`${asset.name} · ${asset.symbol}`} aria-hidden="true">
      {showImage ? <img src={source} alt="" width={28} height={28} decoding="async" onError={() => setFailedSource(source)} />
        : asset.symbol === 'CL=F' ? <Droplets />
          : label ? <b className="asset-glyph">{label}</b> : <Landmark />}
    </span>
  )
})
