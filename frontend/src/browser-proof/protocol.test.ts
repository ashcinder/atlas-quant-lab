// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { assertMarketBinding, datasetHash, marketHashFields, marketInput, parseProof, PROOF_BAR_COUNTS } from './protocol'
import type { ProofProfile } from './protocol'

const hash = 'a'.repeat(64)
const id = 'b'.repeat(64)
const dataset = {
  symbol: 'BTC-USD',
  interval: '1d',
  source: 'test',
  bars: Array.from({ length: 130 }, (_, i) => ({ time: i + 1, open_micros: 100 + i, close_micros: 101 + i })),
}

describe('browser proof bar profiles', () => {
  const profiles = Object.entries(PROOF_BAR_COUNTS) as [ProofProfile, number][]

  it.each(profiles)('binds %s to its exact window of %i closed bars', (profile, count) => {
    const market = marketInput(id, hash, dataset, profile)
    expect(market).toMatchObject({ profile, start: 131 - count, end: 130 })
    expect(market.opens).toHaveLength(count)
    expect(market.opens[0]).toBe(String(230 - count))

    const bundle = parseProof({
      profile, dataset_id: id, window_end: market.end, market_data_hash: hash, proof: 'AQ==',
      public_inputs: [...marketHashFields(hash), ...market.opens, ...market.closes, '10000000000', '1']
        .map(value => `0x${BigInt(value).toString(16).padStart(64, '0')}`),
    })
    expect(() => assertMarketBinding(bundle, market)).not.toThrow()
    const other = profiles.find(([id]) => id !== profile)![0]
    expect(() => parseProof({ ...bundle, profile: other })).toThrow('证明文件与本地双均线协议不兼容')
    expect(() => assertMarketBinding(bundle, marketInput(id, hash, dataset, other))).toThrow('证明公开输入与登记的市场数据不一致')
    expect(() => assertMarketBinding({ ...bundle, window_end: market.end - 1 }, market)).toThrow('证明公开输入与登记的市场数据不一致')
  })

  it('rejects a short dataset without padding or silently reducing the proof window', () => {
    const short = { ...dataset, bars: dataset.bars.slice(0, 127) }
    expect(() => marketInput(id, hash, short, 'atlas-browser-sma-128-v1')).toThrow('不足 128 根')
  })

  it('commits to the market window prices and immutable dataset version', async () => {
    const fixture = {
      dataset_id: id, source: '测试', symbol: 'BTC-USD', interval: '1d', adjustment: 'raw',
      bars: [{ time: 1_700_000_000, open_micros: 1_000_000, high_micros: 2_000_000, low_micros: 750_000, close_micros: 1_500_000, volume_micros: 999 }],
    }
    const commitment = await datasetHash(fixture)
    expect(await datasetHash({ ...fixture, dataset_id: hash })).not.toBe(commitment)
    fixture.bars[0].close_micros += 1
    expect(await datasetHash(fixture)).not.toBe(commitment)
  })
})
