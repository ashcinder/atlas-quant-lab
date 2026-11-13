import type { Asset } from './types'

const stockSectors: Record<string, string> = {
  '000001.SZ': '银行金融', '600036.SS': '银行金融', '600030.SS': '银行金融',
  '601318.SS': '银行金融', '601398.SS': '银行金融', '601939.SS': '银行金融',
  '601288.SS': '银行金融', '601988.SS': '银行金融',
  '600519.SS': '白酒食品', '000858.SZ': '白酒食品',
  '000333.SZ': '消费家电', '000651.SZ': '消费家电',
  '300750.SZ': '新能源', '002594.SZ': '新能源',
  '600941.SS': '通信', '600028.SS': '能源电力', '601857.SS': '能源电力', '600900.SS': '能源电力',
  '002415.SZ': '电子安防', '000725.SZ': '电子安防',
}
const order = ['加密货币', 'A股 · 半导体', 'A股 · 机器人', 'A股 · 航天', '美股 · 科技', '美股 · 其他',
  'A股 · 银行金融', 'A股 · 消费家电', 'A股 · 白酒食品', 'A股 · 新能源', 'A股 · 电子安防',
  'A股 · 通信', 'A股 · 能源电力', 'A股 · 其他', '港股', '其他股票', 'ETF / 基金', '大宗商品', '外汇', '指数']

export function assetGroupLabel(asset: Asset): string {
  if (asset.asset_class === 'equity' || asset.asset_class === 'stock') {
    if (['SSE', 'SZSE'].includes(asset.exchange)) {
      const topic = ['半导体', '机器人', '航天'].find(tag => asset.tags.includes(tag))
      return `A股 · ${topic ?? stockSectors[asset.symbol] ?? '其他'}`
    }
    if (asset.exchange === 'HKEX') return '港股'
    if (['NASDAQ', 'NYSE', 'NYSE Arca'].includes(asset.exchange)) return ['AAPL', 'MSFT', 'NVDA'].includes(asset.symbol) ? '美股 · 科技' : '美股 · 其他'
    return '其他股票'
  }
  return ({crypto: '加密货币', etf: 'ETF / 基金', commodity: '大宗商品', forex: '外汇', index: '指数'} as Record<string, string>)[asset.asset_class] ?? asset.asset_class
}

export function groupAssets(assets: Asset[]): Array<{label: string; assets: Asset[]}> {
  const groups = new Map<string, Asset[]>()
  for (const asset of assets) {
    const label = assetGroupLabel(asset)
    const rows = groups.get(label) ?? []
    rows.push(asset)
    groups.set(label, rows)
  }
  return [...groups].map(([label, rows]) => ({label, assets: rows})).sort((a, b) => {
    const rank = (label: string) => { const index = order.indexOf(label); return index < 0 ? order.length : index }
    return rank(a.label) - rank(b.label)
  })
}
