import { expect, it } from 'vitest'
import { assetGroupLabel, groupAssets } from './assetGroups'
import type { Asset } from './types'
const stock = (symbol: string, exchange = 'SSE', tags: string[] = []): Asset => ({symbol, name: symbol, asset_class:'equity', exchange, currency:'CNY', timezone:'Asia/Shanghai', tags})
it('separates technology themes, US equities, finance and existing consumer stocks', () => {
  const assets = [stock('600036.SS'), stock('AAPL','NASDAQ'), stock('688981.SS','SSE',['半导体']), stock('688017.SS','SSE',['机器人']), stock('600118.SS','SSE',['航天']), stock('000333.SZ','SZSE')]
  const groups=groupAssets(assets)
  expect(groups.map(group=>group.label)).toEqual(['A股 · 半导体','A股 · 机器人','A股 · 航天','美股 · 科技','A股 · 银行金融','A股 · 消费家电'])
  expect(groups.flatMap(group=>group.assets)).toHaveLength(assets.length)
  expect(new Set(groups.flatMap(group=>group.assets.map(asset=>asset.symbol))).size).toBe(assets.length)
})
it('does not assign an invented sector to unknown equities', () => {
  expect(assetGroupLabel(stock('UNKNOWN','NASDAQ'))).toBe('美股 · 其他')
  expect(assetGroupLabel(stock('UNKNOWN'))).toBe('A股 · 其他')
})
