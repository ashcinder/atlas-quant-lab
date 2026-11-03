export type SweepField = { key: string; label: string; value: number; min?: number; max?: number; integer?: boolean; scale?: number; unit?: string }
export type SweepRange = { enabled: boolean; from: string; to: string; step: string }
export function formatSweepValue(field: SweepField | undefined, value: number): string {
  return `${Number((value * (field?.scale ?? 1)).toPrecision(12))}${field?.unit ?? ''}`
}
export function sweepGrid(fields: SweepField[], ranges: Record<string, SweepRange>, limit = 100): Record<string, number>[] {
  let rows: Record<string, number>[] = [{}]
  let selected = 0
  for (const field of fields) {
    const range = ranges[field.key]
    if (!range?.enabled) continue
    selected++
    const values = [range.from, range.to, range.step]
    if (values.some(x => !x.trim())) throw new Error(`${field.label}：请填写最小值、最大值和每次增加量`)
    const [from, to, step] = values.map(Number)
    const scale = field.scale ?? 1
    if (![from, to, step].every(Number.isFinite) || step <= 0 || to < from) throw new Error(`${field.label}：最大值不能小于最小值，每次增加量须大于0`)
    if ((field.min != null && from / scale < field.min) || (field.max != null && to / scale > field.max) || (field.integer && ![from, to, step].every(Number.isInteger))) throw new Error(`${field.label}：超出允许范围或不是整数`)
    const count = Math.floor((to - from) / step + 1e-9) + 1
    if (rows.length * count > limit) throw new Error(`超过 ${limit} 组，请缩小范围或增大每次增加量`)
    rows = rows.flatMap(row => Array.from({ length: count }, (_, i) => ({ ...row, [field.key]: Number(((from + i * step) / scale).toPrecision(12)) })))
  }
  if (!selected) throw new Error('先勾选要比较的参数')
  return rows
}
export function numericFields(value: unknown, prefix = ''): SweepField[] {
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof item === 'number' && Number.isFinite(item)) {
      const side = path.split('.').includes('entry') ? '买入' : path.split('.').includes('exit') ? '卖出' : ''
      const conditions = [...path.matchAll(/children\.(\d+)/g)].map(match => Number(match[1]) + 1)
      const context = side ? `${side}条件${conditions.length ? conditions.join('-') : '1'} · ` : ''
      const indicator = (value as { field?: string }).field
      const names: Record<string, string> = { sma: '均线', ema: '指数均线', rsi: '强弱指标', roc: '动量指标', boll_upper: '布林上轨', boll_lower: '布林下轨' }
      const label = key === 'target_position' ? '持仓比例' : key === 'period' ? `${context}${path.split('.').includes('right_indicator') ? '参考' : ''}${names[indicator ?? ''] ?? '指标'}长度` : `${context}比较值`
      return [{ key: path, label, value: item, ...(key === 'period' ? { integer: true, min: 2, max: 500, unit: '根K线' } : key === 'target_position' ? { min: 0, max: 1, scale: 100, unit: '%' } : {}) }]
    }
    return numericFields(item, path)
  })
}
export function applySweep<T>(source: T, values: Record<string, number>): T {
  const result = structuredClone(source)
  for (const [path, value] of Object.entries(values)) {
    const parts = path.split('.')
    let cursor = result as Record<string, unknown>
    for (const key of parts.slice(0, -1)) cursor = cursor[key] as Record<string, unknown>
    cursor[parts.at(-1)!] = value
  }
  return result
}
