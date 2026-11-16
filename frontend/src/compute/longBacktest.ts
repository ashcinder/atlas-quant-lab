import type { Bar } from '../types'

export const LONG_BACKTEST_BARS = 100_000
export const MAX_PORTABLE_BARS = 5_000_000
export const REPORT_POINTS = 6_000
export const REPORT_TRADES = 12_000

export function packBars(bars: Bar[]): ArrayBuffer {
  const packed = new Float64Array(bars.length * 6)
  let index = 0
  for (const { time, open, high, low, close, volume } of bars) {
    packed[index++] = time
    packed[index++] = open
    packed[index++] = high
    packed[index++] = low
    packed[index++] = close
    packed[index++] = volume
  }
  return packed.buffer as ArrayBuffer
}

export async function packTargets(targets: number[]): Promise<string> {
  const bytes = new Float64Array(targets).buffer
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('gzip'))
  const compressed = new Uint8Array(await new Response(stream).arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < compressed.length; offset += 16384) {
    binary += String.fromCharCode(...compressed.subarray(offset, offset + 16384))
  }
  return btoa(binary)
}

export async function unpackTargets(packed: string, count: number): Promise<Float64Array> {
  const stream = new Blob([Uint8Array.from(atob(packed), char => char.charCodeAt(0))]).stream()
    .pipeThrough(new DecompressionStream('gzip'))
  const reader = stream.getReader()
  const bytes = new Uint8Array(count * 8)
  let offset = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (offset + value.length > bytes.length) throw new Error('仓位计划长度与行情不一致')
      bytes.set(value, offset)
      offset += value.length
    }
  } finally {
    await reader.cancel()
  }
  if (offset !== bytes.length) throw new Error('仓位计划长度与行情不一致')
  return new Float64Array(bytes.buffer)
}
