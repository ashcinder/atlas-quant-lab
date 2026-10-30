import type { EvaluationDimension, EvaluationDimensionId, QuantReport } from '../types'

export const evaluationOrder: EvaluationDimensionId[] = [
  'return_capacity',
  'risk_adjusted_efficiency',
  'risk_control_stability',
  'market_adaptability',
  'backtest_live_consistency',
  'strategy_purity',
]

export function strategyDimensions(report: QuantReport | null): Array<EvaluationDimension | null> {
  const byId = new Map(report?.evaluation?.dimensions.map((item) => [item.id, item]) ?? [])
  return evaluationOrder.map((id) => byId.get(id) ?? null)
}

export function strategyScores(report: QuantReport | null): Array<number | null> {
  return strategyDimensions(report).map((item) => item?.status === 'evaluated' && Number.isFinite(item.score) ? item.score : null)
}
