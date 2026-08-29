export function normalizeWeightValues(weights: number[]): number[] {
  if (weights.length === 0) return []
  const clean = weights.map((weight) => Math.max(0, Number.isFinite(weight) ? weight : 0))
  const total = clean.reduce((sum, weight) => sum + weight, 0)
  const rawUnits = clean.map((weight) => total > 0 ? weight / total * 1_000 : 1_000 / weights.length)
  const units = rawUnits.map(Math.floor)
  const remainder = 1_000 - units.reduce((sum, value) => sum + value, 0)
  const priority = rawUnits
    .map((value, index) => ({ index, fraction: value - units[index] }))
    .sort((left, right) => right.fraction - left.fraction || left.index - right.index)
  for (let index = 0; index < remainder; index += 1) units[priority[index % priority.length].index] += 1
  return units.map((value) => value / 1_000)
}
