import type { Interval, ResearchCandidate, ResearchExperiment, ResearchResult, WalkForwardWindow } from '../types'
import { runBacktest } from './backtest'
import { checkCancelled, type ComputeContext, type MarketInput } from './model'
import { defaultParams, getStrategy } from './strategies'

type Params = ResearchExperiment['base_params']
type Metrics = Record<string, number | null>
export interface ResearchContext extends ComputeContext { jobId?: string }

function finite(value: unknown): number | null {
  if (value == null || typeof value === 'boolean') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length

function integer(value: unknown, fallback: number, minimum: number, maximum: number): number {
  const result = value === undefined ? fallback : value
  if (typeof result !== 'number' || !Number.isInteger(result) || result < minimum || result > maximum) throw new Error('Walk-forward窗口参数超出有效范围')
  return result
}

function expand(experiment: ResearchExperiment): Params[] {
  if (experiment.custom_strategy != null) {
    if (experiment.custom_strategy.id !== experiment.strategy_id) throw new Error('自定义策略 ID 与研究实验 strategy_id 不一致')
    if (Object.keys(experiment.base_params).length || Object.keys(experiment.parameter_grid).length) throw new Error('视觉规则策略暂不接受参数网格；请复制策略版本后比较')
    return [{}]
  }
  const strategy = getStrategy(experiment.strategy_id)
  const definitions = Object.fromEntries(strategy.parameters.map(parameter => [parameter.key, parameter]))
  const base = { ...defaultParams(strategy.id), ...experiment.base_params }
  const keys = Object.keys(experiment.parameter_grid)
  for (const key of [...Object.keys(experiment.base_params), ...keys]) if (!definitions[key]) throw new Error(`策略 ${experiment.strategy_id} 不包含参数 ${key}`)
  let combinations = 1
  for (const key of keys) {
    const values = experiment.parameter_grid[key]
    if (!key || !Array.isArray(values) || !values.length || values.length > 20) throw new Error('每个参数网格必须包含1–20个值')
    combinations *= values.length
    if (combinations > 200) throw new Error('单个策略的参数组合不能超过200组')
    const definition = definitions[key]
    for (const value of values) {
      if (definition.kind === 'boolean' && typeof value !== 'boolean') throw new Error(`参数 ${key} 必须是布尔值`)
      if (definition.kind === 'number' || definition.kind === 'integer') {
        const number = Number(value)
        if (!Number.isFinite(number)) throw new Error(`参数 ${key} 必须为有限数字`)
        if (definition.minimum != null && number < definition.minimum) throw new Error(`参数 ${key} 低于最小值`)
        if (definition.maximum != null && number > definition.maximum) throw new Error(`参数 ${key} 高于最大值`)
      }
    }
  }
  let candidates: Params[] = [base]
  for (const key of keys) candidates = candidates.flatMap(params => experiment.parameter_grid[key].map(value => ({ ...params, [key]: value })))
  return candidates
}

export function candidateWarnings(train: Metrics, test: Metrics, combinations: number, paramCount: number): { warnings: string[]; degradation: number | null; adjustedP: number | null; score: number } {
  const warnings: string[] = []
  const trainSharpe = finite(train.sharpe), testSharpe = finite(test.sharpe)
  let degradation: number | null = null
  if (trainSharpe != null && trainSharpe > 0 && testSharpe != null) {
    degradation = 1 - testSharpe / trainSharpe
    if (degradation > 0.5) warnings.push('样本外Sharpe相对样本内下降超过50%')
  }
  if (trainSharpe != null && Math.abs(trainSharpe) > 3) warnings.push('样本内Sharpe绝对值超过3，存在明显过拟合风险')
  const trades = Math.trunc(test.round_trip_count || 0)
  if (trades < 30) warnings.push(`样本外完整交易仅${trades}笔，统计功效不足`)
  const observations = Math.max(Math.trunc(test.trade_count || 0), 1)
  if (observations / Math.max(paramCount, 1) < 20) warnings.push('每个参数对应的样本不足20个')
  const rawP = finite(test.return_p_value)
  const adjustedP = rawP == null ? null : Math.min(1, rawP * combinations)
  if (adjustedP != null && adjustedP > 0.05) warnings.push('经Bonferroni多重测试修正后收益不显著')
  const retention = trainSharpe != null && trainSharpe > 0 && testSharpe != null ? Math.min(1, Math.max(0, testSharpe / trainSharpe)) : 0
  const oosQuality = Math.min(1, Math.max(0, ((testSharpe || 0) + 0.5) / 2))
  const tradeQuality = Math.min(1, trades / 30)
  const significance = adjustedP == null ? 0 : 1 - adjustedP
  const score = Math.round(10000 * (0.4 * oosQuality + 0.25 * retention + 0.2 * tradeQuality + 0.15 * significance)) / 100
  return { warnings, degradation, adjustedP, score }
}

/** Parameter selection sees training bars only; holdout and WF tests are never reused to choose parameters. */
export async function runResearch(request: Record<string, unknown>, market: MarketInput, context?: ResearchContext): Promise<ResearchResult> {
  const bars = market.bars
  if (bars.length < 160) throw new Error('策略研究至少需要160根K线')
  const interval = (request.interval ?? '1d') as Interval
  const objective = String(request.objective ?? 'sharpe')
  if (!['sharpe', 'calmar', 'cagr', 'total_return'].includes(objective)) throw new Error('无效研究目标')
  const holdout = request.holdout_ratio === undefined ? 0.2 : request.holdout_ratio
  if (typeof holdout !== 'number' || !Number.isFinite(holdout) || holdout < 0.1 || holdout > 0.4) throw new Error('样本外比例必须为10%–40%')
  const pipeline = request.execution_pipeline as {ai_stages?: Array<{enabled?: boolean}>} | undefined
  if (pipeline?.ai_stages?.some(stage => stage.enabled)) throw new Error('AI 审核目前用于单次回测；批量研究请关闭 AI，避免重复模型调用与不可复现的选参')
  const rawExperiments = request.experiments as ResearchExperiment[]
  if (!Array.isArray(rawExperiments) || !rawExperiments.length || rawExperiments.length > 8) throw new Error('研究需要1–8个策略实验')
  const experiments = rawExperiments.map(experiment => ({ ...experiment, base_params: experiment.base_params ?? {}, parameter_grid: experiment.parameter_grid ?? {} }))
  const expanded = experiments.map(experiment => ({ experiment, combinations: expand(experiment) }))
  const combinationsCount = expanded.reduce((total, item) => total + item.combinations.length, 0)
  if (combinationsCount > 500) throw new Error('单次研究任务最多评估500组参数')
  const wfInput = (request.walk_forward ?? {}) as Record<string, unknown>
  if (wfInput.enabled !== undefined && typeof wfInput.enabled !== 'boolean') throw new Error('Walk-forward enabled必须为布尔值')
  const wf = { enabled: wfInput.enabled !== false, train: integer(wfInput.train_bars, 500, 80, 10000), test: integer(wfInput.test_bars, 120, 40, 2000), step: integer(wfInput.step_bars, 120, 20, 2000), windows: integer(wfInput.max_windows, 8, 1, 20) }
  const totalWork = combinationsCount * (1 + (wf.enabled ? wf.windows : 0))
  if (totalWork > 2500) throw new Error('网格与Walk-forward窗口的总评估量不能超过2500次')
  const split = Math.min(Math.max(Math.trunc(bars.length * (1 - holdout)), 80), bars.length - 40)
  const subset = (start: number, end: number): MarketInput => ({ ...market, bars: bars.slice(start, end) })
  const trainMarket = subset(0, split), testMarket = subset(split, bars.length)
  let completed = 0
  const candidates: ResearchCandidate[] = []
  const metrics = async (input: MarketInput, experiment: ResearchExperiment, params: Params) => {
    checkCancelled(context)
    const result = await runBacktest({ ...request, strategy_id: experiment.strategy_id, custom_strategy: experiment.custom_strategy, params, persist: false }, input, { ...context, progress: undefined, includeDetails: false })
    checkCancelled(context)
    return result.metrics
  }
  type Scored = { value: number; params: Params; metrics: Metrics }
  const score = async (input: MarketInput, experiment: ResearchExperiment, params: Params): Promise<Scored | null> => {
    try {
      const result = await metrics(input, experiment, params)
      return { value: finite(result[objective]) ?? -1e100, params, metrics: result }
    } catch (error) {
      checkCancelled(context)
      // Python ignores ValueError for individual invalid parameter combinations.
      // Unexpected runtime failures and cancellation must still reach the task UI.
      if (error instanceof Error && error.name === 'AbortError') throw error
      if (!(error instanceof Error)) throw error
      return null
    }
  }
  for (const { experiment, combinations } of expanded) {
    const scored: Scored[] = []
    for (const params of combinations) {
      checkCancelled(context)
      const candidate = await score(trainMarket, experiment, params)
      if (candidate) scored.push(candidate)
      completed++
      context?.progress?.(Math.min(0.9, completed / Math.max(totalWork, 1)), `正在评估 ${experiment.strategy_id}`)
    }
    if (!scored.length) throw new Error(`策略 ${experiment.strategy_id} 没有可用的参数组合`)
    scored.sort((a, b) => b.value - a.value)
    const best = scored[0]
    const bestTest = await metrics(testMarket, experiment, best.params)
    for (const entry of scored) {
      const isBest = Object.keys(entry.params).length === Object.keys(best.params).length && Object.entries(entry.params).every(([key, value]) => value === best.params[key])
      const details = isBest ? candidateWarnings(entry.metrics, bestTest, combinations.length, Object.keys(experiment.parameter_grid).length || Object.keys(experiment.base_params).length || 1) : { warnings: [], degradation: null, adjustedP: null, score: 0 }
      candidates.push({ strategy_id: experiment.strategy_id, params: entry.params, train_metrics: entry.metrics, test_metrics: isBest ? bestTest : {}, objective_train: finite(entry.metrics[objective]), objective_test: isBest ? finite(bestTest[objective]) : null, sharpe_degradation: details.degradation, adjusted_p_value: details.adjustedP, robustness_score: details.score, rank: 0, warnings: details.warnings })
    }
  }
  const windows: WalkForwardWindow[] = []
  const warnings = ['参数只在训练窗口中选择，测试窗口仅用于样本外评估。', '所有信号仍在K线收盘后生成，并在下一根K线开盘成交。']
  if (wf.enabled) {
    for (const { experiment, combinations } of expanded) {
      let start = 0, windowCount = 0
      while (start + wf.train + wf.test <= bars.length && windowCount < wf.windows) {
        checkCancelled(context)
        const train = subset(start, start + wf.train)
        const test = subset(start + wf.train, start + wf.train + wf.test)
        const scored: Scored[] = []
        for (const params of combinations) {
          checkCancelled(context)
          const candidate = await score(train, experiment, params)
          if (candidate) scored.push(candidate)
          completed++
          context?.progress?.(Math.min(0.96, completed / Math.max(totalWork, 1)), 'Walk-forward滚动验证')
        }
        if (scored.length) {
          scored.sort((a, b) => b.value - a.value)
          const best = scored[0], testMetrics = await metrics(test, experiment, best.params)
          windows.push({ strategy_id: experiment.strategy_id, train_start: train.bars[0].time, train_end: train.bars.at(-1)!.time, test_start: test.bars[0].time, test_end: test.bars.at(-1)!.time, params: best.params, train_sharpe: finite(best.metrics.sharpe), test_sharpe: finite(testMetrics.sharpe), test_return: finite(testMetrics.total_return), trades: Math.trunc(testMetrics.round_trip_count || 0) })
        }
        start += wf.step
        windowCount++
      }
    }
    if (!windows.length) warnings.push('K线数量不足以生成Walk-forward窗口，请缩短训练或测试长度。')
  }
  const bestCandidates = candidates.filter(candidate => Object.keys(candidate.test_metrics).length).sort((a, b) => b.robustness_score - a.robustness_score)
  bestCandidates.forEach((candidate, i) => { candidate.rank = i + 1 })
  const remaining = candidates.filter(candidate => !Object.keys(candidate.test_metrics).length)
  const sharpes = windows.map(window => window.test_sharpe).filter((value): value is number => value != null)
  const returns = windows.map(window => window.test_return).filter((value): value is number => value != null)
  const summary: ResearchResult['summary'] = { holdout_bars: testMarket.bars.length, walk_forward_windows: windows.length, average_oos_sharpe: sharpes.length ? finite(mean(sharpes)) : null, worst_oos_sharpe: sharpes.length ? finite(Math.min(...sharpes)) : null, profitable_window_ratio: returns.length ? mean(returns.map(value => Number(value > 0))) : null, is_robust: Boolean(sharpes.length && mean(sharpes) > 0.5 && returns.length && mean(returns.map(value => Number(value > 0))) >= 0.6) }
  checkCancelled(context)
  context?.progress?.(1, '研究完成')
  return { job_id: context?.jobId ?? crypto.randomUUID(), symbol: String(request.symbol ?? market.asset.symbol), interval, objective, data_source: market.source, tested_combinations: combinationsCount, candidates: [...bestCandidates, ...remaining], walk_forward: windows, summary, warnings, created_at: new Date().toISOString() }
}
