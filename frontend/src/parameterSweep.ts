export type SweepField = { key: string; label: string; value: number; min?: number; max?: number; integer?: boolean }
export type SweepRange = { enabled: boolean; from: string; to: string; step: string }
export function sweepGrid(fields: SweepField[], ranges: Record<string, SweepRange>, limit = 100): Record<string, number>[] {
  let rows: Record<string, number>[] = [{}]
  let selected = 0
  for (const field of fields) {
    const range = ranges[field.key]
    if (!range?.enabled) continue
    selected++
    const values = [range.from, range.to, range.step]
    if (values.some(x => !x.trim())) throw new Error(`${field.label}：请填写起点、终点与步长`)
    const [from, to, step] = values.map(Number)
    if (![from, to, step].every(Number.isFinite) || step <= 0 || to < from) throw new Error(`${field.label}：范围或步长无效`)
    if ((field.min != null && from < field.min) || (field.max != null && to > field.max) || (field.integer && ![from, to, step].every(Number.isInteger))) throw new Error(`${field.label}：超出允许范围或不是整数`)
    const count = Math.floor((to - from) / step + 1e-9) + 1
    if (rows.length * count > limit) throw new Error(`组合数超过 ${limit}，请缩小范围或增大步长`)
    rows = rows.flatMap(row => Array.from({ length: count }, (_, i) => ({ ...row, [field.key]: Number((from + i * step).toPrecision(12)) })))
  }
  if (!selected) throw new Error('至少勾选一个搜索参数')
  return rows
}
export function numericFields(value: unknown, prefix = ''): SweepField[] {
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof item === 'number' && Number.isFinite(item)) return [{ key: path, label: path.replace(/entry/g, '入场').replace(/exit/g, '离场').replace(/children/g, '条件').replace(/period/g, '周期').replace(/target_position/g, '目标仓位'), value: item, ...(key === 'period' ? { integer: true, min: 2, max: 500 } : key === 'target_position' ? { min: 0, max: 1 } : {}) }]
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
