import type { Bar, Interval, PortfolioResult, Trade } from '../types'
import { checkCancelled, type ComputeContext, type MarketInput } from './model'
import { calculateMetrics, drawdownSeries } from './metrics'
import { getStrategy, validateParams } from './strategies'

type Weights = Record<string, number>
const sum = (values: number[]) => values.reduce((a, b) => a + b, 0)
const dot = (a: number[], b: number[]) => sum(a.map((v, i) => v * b[i]))
const multiply = (matrix: number[][], vector: number[]) => matrix.map(row => dot(row, vector))
const finite = (value: number) => Number.isFinite(value) ? value : null

function normalize(values: Weights): Weights {
  const total = sum(Object.values(values).map(v => Math.max(v, 0)))
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, total > 0 ? Math.max(value, 0) / total : 1 / Object.keys(values).length]))
}

export function constrainedWeights(values: Weights, cashBuffer: number, maximum: number): Weights {
  const weights = normalize(values)
  let remaining = 1 - cashBuffer
  let active = Object.keys(weights)
  const output: Weights = Object.fromEntries(active.map(symbol => [symbol, 0]))
  while (active.length) {
    const total = sum(active.map(symbol => weights[symbol]))
    const proposed = Object.fromEntries(active.map(symbol => [symbol, total > 0 ? remaining * weights[symbol] / total : remaining / active.length]))
    const capped = active.filter(symbol => proposed[symbol] > maximum)
    if (!capped.length) return { ...output, ...proposed }
    for (const symbol of capped) {
      output[symbol] = maximum
      remaining -= maximum
    }
    active = active.filter(symbol => !capped.includes(symbol))
  }
  return output
}

// pandas DatetimeIndex.round('D') uses ties-to-even, including dates before 1970.
function sessionTime(time: number, interval: Interval): number {
  if (interval !== '1d' && interval !== '1wk') return time
  const days = time / 86400
  const low = Math.floor(days)
  const fraction = days - low
  return (fraction < 0.5 ? low : fraction > 0.5 ? low + 1 : low % 2 === 0 ? low : low + 1) * 86400
}

function covariance(rows: number[][], columns: number, annualize = 252): number[][] {
  const means = Array.from({ length: columns }, (_, j) => sum(rows.map(row => row[j])) / rows.length)
  return means.map((_, j) => means.map((__, k) => sum(rows.map(row => (row[j] - means[j]) * (row[k] - means[k]))) / (rows.length - 1) * annualize))
}

function returnRows(close: number[][], start = 0, end = close.length): number[][] {
  const rows: number[][] = []
  for (let i = start + 1; i < end; i++) rows.push(close[i].map((value, j) => value / close[i - 1][j] - 1))
  return rows.filter(row => row.every(Number.isFinite))
}

function solve(matrix: number[][], vector: number[]): number[] | null {
  const augmented = matrix.map((row, i) => [...row, vector[i]])
  for (let j = 0; j < vector.length; j++) {
    let pivot = j
    for (let i = j + 1; i < vector.length; i++) if (Math.abs(augmented[i][j]) > Math.abs(augmented[pivot][j])) pivot = i
    if (Math.abs(augmented[pivot][j]) < 1e-15) return null
    ;[augmented[j], augmented[pivot]] = [augmented[pivot], augmented[j]]
    const divisor = augmented[j][j]
    for (let k = j; k <= vector.length; k++) augmented[j][k] /= divisor
    for (let i = 0; i < vector.length; i++) {
      if (i === j) continue
      const factor = augmented[i][j]
      for (let k = j; k <= vector.length; k++) augmented[i][k] -= factor * augmented[j][k]
    }
  }
  return augmented.map(row => row[vector.length])
}

// Solve the linear equality and box constrained SQP subproblem. The dimension
// is at most twelve; an active set avoids a heavyweight numerical dependency.
function quadraticStep(hessian: number[][], gradient: number[], current: number[]): number[] | null {
  const count = current.length
  const active = new Set<number>()
  const step = current.map(() => 0)
  for (let iteration = 0; iteration < 20 * count + 20; iteration++) {
    const free = current.map((_, i) => i).filter(i => !active.has(i))
    if (!free.length) return null
    const system = free.map(i => [...free.map(j => hessian[i][j]), 1])
    system.push([...free.map(() => 1), 0])
    const atStep = multiply(hessian, step).map((value, i) => value + gradient[i])
    const solution = solve(system, [...free.map(i => -atStep[i]), 0])
    if (!solution) return null
    const direction = current.map((_, i) => active.has(i) ? 0 : solution[free.indexOf(i)])
    if (Math.sqrt(dot(direction, direction)) < 1e-12) {
      const stationarity = atStep.map(value => value + solution[free.length])
      let release: number | undefined, mostViolation = 1e-10
      for (const i of active) {
        const violation = current[i] + step[i] <= 0.01 + 1e-10 ? -stationarity[i] : stationarity[i]
        if (violation > mostViolation) { release = i; mostViolation = violation }
      }
      if (release === undefined) return step
      active.delete(release)
      continue
    }
    let alpha = 1, blocking: number | undefined
    for (const i of free) {
      const candidate = direction[i] < 0 ? (0.01 - current[i] - step[i]) / direction[i] : direction[i] > 0 ? (1 - current[i] - step[i]) / direction[i] : Infinity
      if (candidate < alpha) { alpha = Math.max(0, candidate); blocking = i }
    }
    for (let i = 0; i < count; i++) step[i] += alpha * direction[i]
    if (blocking !== undefined) active.add(blocking)
  }
  return null
}

/** Same long-only risk-contribution objective, bounds and default ftol as SciPy SLSQP. */
export function riskParityWeights(rows: number[][], symbols: string[], shrinkage = 0.1): Weights {
  const n = symbols.length
  const equal = Array.from({ length: n }, () => 1 / n)
  if (rows.length < 30) return Object.fromEntries(symbols.map((symbol, i) => [symbol, equal[i]]))
  const sample = covariance(rows, n)
  const cov = sample.map((row, i) => row.map((value, j) => i === j ? value : value * (1 - shrinkage)))
  const objective = (weights: number[]) => {
    const marginal = multiply(cov, weights)
    const volatility = Math.sqrt(Math.max(dot(weights, marginal), 1e-16))
    return sum(weights.map((weight, i) => (weight * marginal[i] / volatility - volatility / n) ** 2))
  }
  const gradient = (weights: number[], value: number) => weights.map((_, i) => {
    const delta = weights[i] + 1.4901161193847656e-8 <= 1 ? 1.4901161193847656e-8 : -1.4901161193847656e-8
    const shifted = [...weights]; shifted[i] += delta
    return (objective(shifted) - value) / delta
  })
  let weights = [...equal]
  let value = objective(weights)
  let grad = gradient(weights, value)
  let hessian: number[][] = equal.map((_, i) => equal.map((__, j) => i === j ? 1 : 0))
  let success = false
  for (let iteration = 0; iteration < 100; iteration++) {
    const direction = quadraticStep(hessian, grad, weights)
    if (!direction) break
    const derivative = dot(grad, direction)
    if (Math.abs(derivative) < 1e-6) { success = true; break }
    let alpha = 1
    let next = weights.map((weight, i) => Math.min(1, Math.max(0.01, weight + direction[i])))
    let nextValue = objective(next)
    // SLSQP's inexact Armijo line search, including its quadratic interpolation.
    for (let line = 0; nextValue - value > 0.1 * alpha * derivative && line < 10; line++) {
      const slope = alpha * derivative
      const nextAlpha = Math.max(slope / (2 * (slope - (nextValue - value))), 0.1)
      alpha *= nextAlpha
      next = weights.map((weight, i) => Math.min(1, Math.max(0.01, weight + alpha * direction[i])))
      nextValue = objective(next)
    }
    const step = next.map((weight, i) => weight - weights[i])
    if (Math.abs(nextValue - value) < 1e-6 || Math.sqrt(dot(step, step)) < 1e-6) { weights = next; success = true; break }
    const nextGradient = gradient(next, nextValue)
    let change = nextGradient.map((component, i) => component - grad[i])
    const hessianStep = multiply(hessian, step)
    const curvature = dot(step, hessianStep)
    let stepChange = dot(step, change)
    if (stepChange < 0.2 * curvature) {
      const theta = 0.8 * curvature / (curvature - stepChange)
      change = change.map((component, i) => theta * component + (1 - theta) * hessianStep[i])
      stepChange = dot(step, change)
    }
    if (!(curvature > 0) || !(stepChange > 0)) hessian = equal.map((_, i) => equal.map((__, j) => i === j ? 1 : 0))
    else hessian = hessian.map((row, i) => row.map((element, j) => element + change[i] * change[j] / stepChange - hessianStep[i] * hessianStep[j] / curvature))
    weights = next; value = nextValue; grad = nextGradient
  }
  if (!success) weights = equal
  return Object.fromEntries(symbols.map((symbol, i) => [symbol, weights[i]]))
}

function number(request: Record<string, unknown>, key: string, fallback: number, minimum: number, maximum = Infinity, inclusive = true): number {
  const value = request[key] === undefined ? fallback : request[key]
  if (typeof value !== 'number' || !Number.isFinite(value) || (inclusive ? value < minimum : value <= minimum) || value > maximum) throw new Error(`${key} 超出有效范围`)
  return value
}

export function runPortfolio(request: Record<string, unknown>, markets: MarketInput[], context?: ComputeContext): PortfolioResult {
  const interval = (request.interval ?? '1d') as Interval
  if (!['1m', '5m', '15m', '1h', '4h', '1d', '1wk'].includes(interval)) throw new Error('无效K线周期')
  const strategy = getStrategy(String(request.strategy_id ?? 'all_weather'))
  if (strategy.mode !== 'portfolio') throw new Error('该策略不支持多资产组合')
  const params = validateParams(strategy.id, (request.params ?? {}) as Record<string, unknown>)
  const assets = request.assets as Array<{symbol: string; weight?: number | null}>
  if (!Array.isArray(assets) || assets.length < 2 || assets.length > 12) throw new Error('组合需要2–12个标的')
  const symbols = assets.map(asset => String(asset.symbol).trim().toUpperCase())
  if (symbols.some(symbol => !symbol) || new Set(symbols).size !== symbols.length) throw new Error('组合不能包含重复或空标的')
  const selected = symbols.map(symbol => {
    const market = markets.find(item => item.asset.symbol === symbol)
    if (!market) throw new Error(`缺少行情 ${symbol}`)
    return market
  })
  const cashBuffer = number(request, 'cash_buffer', 0, 0, 0.5)
  if (cashBuffer >= 0.5) throw new Error('现金缓冲必须小于50%')
  const maxWeight = number(request, 'max_asset_weight', 1, 0, 1, false)
  if (maxWeight * symbols.length + 1e-12 < 1 - cashBuffer) throw new Error('max_asset_weight is too low for the selected asset count')
  const capital = number(request, 'initial_capital', 100000, 0, Infinity, false)
  const commission = number(request, 'commission_rate', 0.001, 0, 0.1)
  const slippage = number(request, 'slippage_rate', 0.0005, 0, 0.1)
  const spread = number(request, 'spread_rate', 0.0005, 0, 0.1)
  const volatilityTarget = request.volatility_target == null ? null : number(request, 'volatility_target', 0, 0, 1, false)
  const rebalance = String(request.rebalance ?? 'quarterly')
  if (!['monthly', 'quarterly', 'yearly'].includes(rebalance)) throw new Error('无效再平衡周期')
  const currency = String(request.base_currency ?? 'CNY')
  if (!['CNY', 'USD', 'USDT'].includes(currency)) throw new Error('无效计价币种')
  // FX is performed when producing the dataset. Never silently mix currencies.
  if (selected.some(market => market.asset.currency !== currency && !(market.source_note ?? '').includes('历史汇率换算'))) throw new Error(`组合行情必须先按历史汇率统一换算为 ${currency}`)
  const start = request.start == null ? -Infinity : Date.parse(String(request.start)) / 1000
  const end = request.end == null ? Infinity : Date.parse(String(request.end)) / 1000
  if (Number.isNaN(start) || Number.isNaN(end) || start >= end) throw new Error('start must be earlier than end')
  const frames = selected.map(market => {
    const frame = new Map<number, Bar>()
    for (const bar of market.bars) {
      if (bar.time < start || bar.time > end) continue
      const timestamp = sessionTime(bar.time, interval)
      if (![bar.time, bar.open, bar.close].every(Number.isFinite) || bar.open <= 0 || bar.close <= 0) throw new Error('行情包含无效价格或时间')
      frame.set(timestamp, bar)
    }
    return frame
  })
  const times = [...frames[0].keys()].filter(time => frames.every(frame => frame.has(time))).sort((a, b) => a - b)
  if (times.length < 60) throw new Error(`多资产组合对齐后仅有${times.length}个共同K线周期，至少需要60个；请改用日线/周线、减少跨市场标的，或选择历史更长的数据源`)
  const close = times.map(time => frames.map(frame => frame.get(time)!.close))
  const opens = times.map(time => frames.map(frame => frame.get(time)!.open))
  const supplied = Object.fromEntries(assets.filter(asset => asset.weight != null).map(asset => {
    if (typeof asset.weight !== 'number' || !Number.isFinite(asset.weight) || asset.weight < 0 || asset.weight > 1) throw new Error('标的权重超出有效范围')
    return [asset.symbol.trim().toUpperCase(), asset.weight]
  }))
  let fixed: Weights
  if (strategy.id === 'sixty_forty') {
    const target = Number(params.equity_target)
    fixed = Object.fromEntries(symbols.map((symbol, i) => [symbol, i === 0 ? target : (1 - target) / Math.max(symbols.length - 1, 1)]))
  } else if (Object.keys(supplied).length === assets.length) fixed = supplied
  else if (strategy.id === 'all_weather' && symbols.length === 5) fixed = Object.fromEntries(symbols.map((symbol, i) => [symbol, [0.30, 0.40, 0.15, 0.075, 0.075][i]]))
  else fixed = Object.fromEntries(symbols.map(symbol => [symbol, 1 / symbols.length]))
  const target = constrainedWeights(fixed, cashBuffer, maxWeight)
  const units = symbols.map(() => 0)
  let cash = capital
  const trades: Trade[] = []
  const equity: number[] = [], exposures: number[] = []
  const weightHistory: PortfolioResult['weight_history'] = []
  let previousPeriod = ''
  for (let i = 0; i < times.length; i++) {
    checkCancelled(context)
    if (i % 100 === 0) context?.progress?.(i / times.length, '组合再平衡与净值计算')
    const timestamp = times[i]
    const date = new Date(timestamp * 1000)
    const month = date.getUTCMonth()
    const period = `${date.getUTCFullYear()}-${rebalance === 'yearly' ? 0 : rebalance === 'quarterly' ? Math.floor(month / 3) : month}`
    const atOpen = cash + dot(units, opens[i])
    if (i === 0 || period !== previousPeriod) {
      let history: number[][] = []
      let execution = { ...target }
      if (strategy.id === 'risk_parity' && i > 0) {
        history = returnRows(close, Math.max(0, i - Number(params.lookback)), i)
        if (history.length >= 30) execution = constrainedWeights(riskParityWeights(history, symbols, Number(params.covariance_shrinkage)), cashBuffer, maxWeight)
      }
      if (volatilityTarget != null && i > 0) {
        if (!history.length) history = returnRows(close, Math.max(0, i - 252), i)
        if (history.length >= 30) {
          const vector = symbols.map(symbol => execution[symbol] ?? 0)
          const volatility = Math.sqrt(Math.max(dot(vector, multiply(covariance(history, symbols.length), vector)), 1e-16))
          const scale = Math.min(1, volatilityTarget / volatility)
          execution = Object.fromEntries(symbols.map(symbol => [symbol, execution[symbol] * scale]))
        }
      }
      const current = Object.fromEntries(symbols.map((symbol, j) => [symbol, atOpen > 0 ? units[j] * opens[i][j] / atOpen : 0]))
      if (i > 0 && Math.max(...symbols.map(symbol => Math.abs(current[symbol] - execution[symbol]))) < Number(params.rebalance_band)) execution = current
      const deltas = new Map<number, number>()
      for (let j = 0; j < symbols.length; j++) {
        const delta = atOpen * (execution[symbols[j]] ?? 0) / opens[i][j] - units[j]
        if (Math.abs(delta * opens[i][j]) >= Math.max(atOpen * Number(params.min_trade_rate), 1)) deltas.set(j, delta)
      }
      const cost = slippage + spread / 2
      const buyCost = sum([...deltas].filter(([, delta]) => delta > 0).map(([j, delta]) => delta * opens[i][j] * (1 + cost) * (1 + commission)))
      const sellProceeds = sum([...deltas].filter(([, delta]) => delta < 0).map(([j, delta]) => Math.min(-delta, units[j]) * opens[i][j] * (1 - cost) * (1 - commission)))
      const buyScale = buyCost ? Math.min(1, Math.max(0, cash + sellProceeds) / buyCost) : 1
      const ordered = [...deltas].sort(([a, da], [b, db]) => Number(da > 0) - Number(db > 0) || (symbols[a] < symbols[b] ? -1 : symbols[a] > symbols[b] ? 1 : 0))
      for (const [j, delta] of ordered) {
        const side = delta > 0 ? 'buy' : 'sell'
        const price = opens[i][j] * (side === 'buy' ? 1 + cost : 1 - cost)
        const quantity = side === 'buy' ? Math.min(Math.abs(delta) * buyScale, Math.max(0, cash) / (price * (1 + commission))) : Math.min(Math.abs(delta), units[j])
        if (quantity <= 0) continue
        const notional = quantity * price, fee = notional * commission
        if (side === 'buy') { cash -= notional + fee; units[j] += quantity }
        else { cash += notional - fee; units[j] -= quantity }
        trades.push({ id: trades.length + 1, time: timestamp, side, reason: `${symbols[j]} 组合再平衡`, price, quantity, notional, fee, slippage_cost: quantity * Math.abs(price - opens[i][j]), position_after: units[j], cash_after: cash, realized_pnl: null })
      }
      const after = cash + dot(units, opens[i])
      weightHistory.push({ time: timestamp, weights: Object.fromEntries(symbols.map((symbol, j) => [symbol, after > 0 ? units[j] * opens[i][j] / after : 0])) })
    }
    previousPeriod = period
    const value = cash + dot(units, close[i])
    equity.push(value)
    exposures.push(value > 0 ? (value - cash) / value : 0)
  }
  let benchmarkValue = capital
  const benchmark = close.map((row, i) => {
    if (i) benchmarkValue *= 1 + sum(row.map((value, j) => value / close[i - 1][j] - 1)) / symbols.length
    return benchmarkValue
  })
  const { metrics, warnings } = calculateMetrics(equity, benchmark, trades, exposures, interval, 'equity', capital)
  const allReturns = returnRows(close)
  const cov = covariance(allReturns, symbols.length)
  const latest = weightHistory.at(-1)?.weights ?? target
  const vector = symbols.map(symbol => latest[symbol] ?? 0)
  const volatility = Math.sqrt(Math.max(dot(vector, multiply(cov, vector)), 1e-16))
  const component = multiply(cov, vector).map((value, i) => vector[i] * value / volatility)
  const componentTotal = sum(component)
  const risk = Object.fromEntries(symbols.map((symbol, i) => [symbol, componentTotal > 0 ? finite(component[i] / componentTotal) ?? 0 : 0]))
  const correlation = Object.fromEntries(symbols.map((symbol, i) => [symbol, Object.fromEntries(symbols.map((other, j) => [other, finite(cov[i][j] / Math.sqrt(cov[i][i] * cov[j][j]))]))]))
  if (selected.some(market => (market.source_note ?? '').includes('历史汇率换算'))) warnings.unshift(`不同币种行情已按历史汇率统一换算为 ${currency}。`)
  if (selected.some(market => market.source === 'demo')) warnings.unshift('组合中包含演示行情，结果只用于验证产品流程。')
  if (interval === '1d' || interval === '1wk') warnings.unshift('跨市场日线/周线已按交易日期规范化，并仅保留共同交易日。')
  warnings.unshift('组合权重仅在再平衡日生成，并在对应开盘价计入滑点和手续费后成交。')
  if (cashBuffer > 0) warnings.unshift(`组合保留 ${(cashBuffer * 100).toFixed(1)}% 现金缓冲。`)
  if (volatilityTarget != null) warnings.unshift(`目标年化波动率为 ${(volatilityTarget * 100).toFixed(1)}%，只会降低暴露，不使用杠杆。`)
  const drawdown = drawdownSeries(equity)
  checkCancelled(context)
  context?.progress?.(1, '组合回测完成')
  return { run_id: crypto.randomUUID(), created_at: new Date().toISOString(), strategy, assets: selected.map(market => market.asset), data_source: [...new Set(selected.map(market => market.source))].sort().join(', '), valuation_currency: currency, weights: latest, weight_history: weightHistory, equity: times.map((time, i) => ({ time, equity: equity[i], benchmark: benchmark[i], drawdown: drawdown[i], exposure: exposures[i] })), trades, metrics, risk_contribution: risk, correlation, warnings }
}
