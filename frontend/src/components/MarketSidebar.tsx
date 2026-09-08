import { memo, useDeferredValue, useEffect, useState } from 'react'
import { Search, Star } from 'lucide-react'
import { api } from '../api'
import type { Asset } from '../types'
import { AssetIcon } from './AssetIcon'

interface Props {
  assets: Asset[]
  selectedSymbol: string
  onSelect: (asset: Asset) => void
}

export const MarketSidebar = memo(function MarketSidebar({ assets, selectedSymbol, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Asset[]>(assets)
  const deferredQuery = useDeferredValue(query)

  useEffect(() => {
    let active = true
    api.searchAssets(deferredQuery).then((items) => {
      if (active) setResults(items)
    }).catch(() => {
      if (active) setResults(assets)
    })
    return () => { active = false }
  }, [assets, deferredQuery])

  return (
    <aside className="market-sidebar" aria-label="标的列表">
      <div className="sidebar-heading">
        <span>市场</span>
        <button className="icon-button" aria-label="收藏标的"><Star size={15} /></button>
      </div>
      <label className="search-field" aria-label="搜索市场标的">
        <Search size={14} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="代码、名称或类别" />
      </label>
      <div className="asset-list">
        {results.map((asset) => {
          const active = asset.symbol === selectedSymbol
          return (
            <button
              className={`asset-row ${active ? 'is-active' : ''}`}
              key={asset.symbol}
              onClick={() => onSelect(asset)}
            >
              <AssetIcon asset={asset} />
              <span className="asset-copy">
                <strong>{asset.symbol}</strong>
                <small>{asset.name}</small>
              </span>
              <span className="asset-exchange">{asset.exchange}</span>
            </button>
          )
        })}
        {results.length === 0 ? <div className="empty-inline">没有匹配标的</div> : null}
      </div>
    </aside>
  )
})
