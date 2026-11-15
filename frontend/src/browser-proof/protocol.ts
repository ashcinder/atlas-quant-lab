export const PROOF_BAR_COUNTS = {
  'atlas-browser-sma-v1': 32,
  'atlas-browser-sma-64-v1': 64,
  'atlas-browser-sma-128-v1': 128,
} as const
export type ProofProfile = keyof typeof PROOF_BAR_COUNTS
export const DEFAULT_PROFILE: ProofProfile = 'atlas-browser-sma-v1'

export function isProofProfile(value: unknown): value is ProofProfile {
  return typeof value === 'string' && Object.hasOwn(PROOF_BAR_COUNTS, value)
}
export const INITIAL_EQUITY = 10_000
export const MAX_BUNDLE_BYTES = 128 * 1024
const HASH = /^[0-9a-f]{64}$/
const FIELD = /^0x[0-9a-f]{64}$/
const FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617n

export type BrowserProof = {
  profile: ProofProfile
  dataset_id: string
  window_end: number
  market_data_hash: string
  public_inputs: string[]
  proof: string
}

export type MarketInput = {
  profile: ProofProfile
  datasetId: string
  hash: string
  symbol: string
  interval: string
  source: string
  start: number
  end: number
  opens: string[]
  closes: string[]
}

export type ProofJob =
  | { mode: 'prove'; market: MarketInput; fast: number; slow: number }
  | { mode: 'verify'; market: MarketInput; bundle: BrowserProof }

// Bind the complete proof window and the immutable publication it came from.
export async function datasetHash(dataset: Record<string, unknown>) {
  const keys = ['time', 'open_micros', 'high_micros', 'low_micros', 'close_micros', 'volume_micros']
  const encoder = new TextEncoder()
  const metadata = ['dataset_id', 'source', 'symbol', 'interval', 'adjustment'].map(key => {
    const value = dataset[key]
    if (typeof value !== 'string') throw new Error('登记行情缺少元数据。')
    return encoder.encode(value)
  })
  const bars: unknown = dataset.bars
  if (!Array.isArray(bars) || bars.length > 100_000) throw new Error('登记行情根数无效。')
  const prefix = encoder.encode('TRINE-BROWSER-MARKET-V1')
  const bytes = new Uint8Array(prefix.length + metadata.reduce((size, part) => size + 4 + part.length, 0) + 4 + bars.length * keys.length * 8)
  const view = new DataView(bytes.buffer)
  bytes.set(prefix)
  let offset = prefix.length
  for (const part of metadata) {
    view.setUint32(offset, part.length); offset += 4
    bytes.set(part, offset); offset += part.length
  }
  view.setUint32(offset, bars.length); offset += 4
  for (const bar of bars) {
    if (!bar || typeof bar !== 'object') throw new Error('登记行情格式无效。')
    for (const key of keys) {
      const value = (bar as Record<string, unknown>)[key]
      if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new Error('登记行情超出浏览器支持的定点数范围。')
      view.setBigInt64(offset, BigInt(value)); offset += 8
    }
  }
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('')
}

export function marketInput(datasetId: string, hash: string, dataset: Record<string, unknown>, profile: ProofProfile): MarketInput {
  const { symbol, interval, source } = dataset
  if (!HASH.test(datasetId) || !HASH.test(hash) || typeof symbol !== 'string' || typeof interval !== 'string' || typeof source !== 'string') {
    throw new Error('市场数据格式无效。')
  }
  const barCount = PROOF_BAR_COUNTS[profile]
  if (!Array.isArray(dataset.bars) || dataset.bars.length < barCount) {
    throw new Error(`当前可用行情不足 ${barCount} 根已收盘 K 线，请选择较少的根数。`)
  }
  const bars = dataset.bars.slice(-barCount) as { time: number; open_micros: number; close_micros: number }[]
  for (const [i, bar] of bars.entries()) {
    if (!bar || ![bar.time, bar.open_micros, bar.close_micros].every(n => Number.isSafeInteger(n) && n > 0)
      || (i > 0 && bar.time <= bars[i - 1].time)) {
      throw new Error('K 线时间或定点价格超出本证明支持范围。')
    }
  }
  return {
    profile, datasetId, hash, symbol, interval, source, start: bars[0].time, end: bars[barCount - 1].time,
    opens: bars.map(bar => String(bar.open_micros)), closes: bars.map(bar => String(bar.close_micros)),
  }
}

export function marketHashFields(hash: string) {
  return [`0x${hash.slice(0, 32)}`, `0x${hash.slice(32)}`]
}

export function parseProof(value: unknown): BrowserProof {
  if (!value || typeof value !== 'object') throw new Error('证明文件格式无效。')
  const bundle = value as Partial<BrowserProof>
  if (!isProofProfile(bundle.profile) || typeof bundle.market_data_hash !== 'string' || !HASH.test(bundle.market_data_hash)
    || typeof bundle.dataset_id !== 'string' || !HASH.test(bundle.dataset_id)
    || typeof bundle.window_end !== 'number' || !Number.isSafeInteger(bundle.window_end) || bundle.window_end <= 0
    || !Array.isArray(bundle.public_inputs) || bundle.public_inputs.length !== 2 * PROOF_BAR_COUNTS[bundle.profile] + 4
    || !bundle.public_inputs.every(field => typeof field === 'string' && FIELD.test(field) && BigInt(field) < FIELD_MODULUS)
    || typeof bundle.proof !== 'string' || bundle.proof.length > MAX_BUNDLE_BYTES
    || !/^[A-Za-z0-9+/]+={0,2}$/.test(bundle.proof) || bundle.proof.length % 4 !== 0) {
    throw new Error('证明文件与本地双均线协议不兼容。')
  }
  return { profile: bundle.profile, dataset_id: bundle.dataset_id, window_end: bundle.window_end, market_data_hash: bundle.market_data_hash, public_inputs: bundle.public_inputs, proof: bundle.proof }
}

export function assertMarketBinding(bundle: BrowserProof, market: MarketInput) {
  const expected = [...marketHashFields(market.hash), ...market.opens, ...market.closes]
  if (bundle.profile !== market.profile || bundle.market_data_hash !== market.hash || bundle.dataset_id !== market.datasetId || bundle.window_end !== market.end
    || expected.length !== bundle.public_inputs.length - 2 || expected.some((value, i) => BigInt(value) !== BigInt(bundle.public_inputs[i]))) {
    throw new Error('证明公开输入与登记的市场数据不一致。')
  }
}

export function proofOutput(bundle: BrowserProof) {
  const [equity, commitment] = bundle.public_inputs.slice(-2)
  return { equity: Number(BigInt(equity)) / 1_000_000, commitment }
}
