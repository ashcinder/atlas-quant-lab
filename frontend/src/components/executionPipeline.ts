export interface ExecutionPipeline {
  max_position: number
  commission_rate: number
  slippage_rate: number
  max_participation_rate: number
  ai_stages: Array<{ stage: string; enabled: boolean; authority: 'advisory' | 'veto' | 'reduce_only'; instructions: string; timeout_ms: number; max_reduction: number }>
}

export const executionStages = [
  ['market', '市场判断', '审查市场状态与异常波动'],
  ['entry', '开仓审核', '买入前检查信号与风险'],
  ['buy_size', '买入数量', '在限制范围内减少本次买入量'],
  ['sell_size', '卖出数量', '审核本次卖出量；强制风控退出不受阻拦'],
  ['risk', '风险复核', '对拟提交订单进行风险复核'],
  ['execution', '提交前审核', '模拟成交前的最后一次订单检查'],
] as const

export const defaultPipeline = (): ExecutionPipeline => ({ max_position: .5, commission_rate: .001, slippage_rate: .0005, max_participation_rate: .01,
  ai_stages: executionStages.map(([stage]) => ({ stage, enabled: false, authority: 'advisory', instructions: '', timeout_ms: 2500, max_reduction: .25 })) })
