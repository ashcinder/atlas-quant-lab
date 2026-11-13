import { expect, it } from 'vitest'
import { runBacktest } from './backtest'
import type { MarketInput } from './model'

it('rejects the disputed historical source before running a backtest', async () => {
  const market = { source: 'baostock-disputed', bars: [] } as unknown as MarketInput
  await expect(runBacktest({}, market)).rejects.toThrow('仅供查看')
})
