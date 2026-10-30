import { describe, expect, it } from 'vitest'
import type { EvaluationDimension, EvaluationDimensionId, QuantReport } from '../types'
import { strategyScores } from './strategy-scores'

const ids: EvaluationDimensionId[] = ['return_capacity', 'risk_adjusted_efficiency', 'risk_control_stability', 'market_adaptability', 'backtest_live_consistency', 'strategy_purity']
const report = (scores: Array<number | null>) => ({ metrics: {}, period_start: '2025-01-01', period_end: '2026-01-01', evaluation: {
  version: 'evaluation_v1', complete: scores.every((score) => score != null), total_score: null,
  dimensions: ids.map((id, index) => ({ id, status: scores[index] == null ? 'not_evaluable' : 'evaluated', score: scores[index], raw: {}, reason: scores[index] == null ? '缺少可核对数据' : null, period: { start: '2025-01-01', end: '2026-01-01', observation_count: 365 }, rule_version: 'evaluation_v1' })) as EvaluationDimension[],
} }) as QuantReport

describe('six dimensional score calibration', () => {
  it('does not fabricate scores for missing reports or metrics', () => {
    expect(strategyScores(null)).toEqual([null, null, null, null, null, null])
    expect(strategyScores(report([null, null, null, null, null, null]))).toEqual([null, null, null, null, null, null])
  })
  it('uses the backend evaluation rather than recalculating report metrics', () => {
    const value = report([50, 50, 80, null, null, null])
    value.metrics = { annualized_return: 99, sharpe: 99, max_drawdown: 0 }
    expect(strategyScores(value)).toEqual([50, 50, 80, null, null, null])
  })
  it('does not infer evaluation for a legacy report without evaluation_v1', () => {
    const value = { metrics: { annualized_return: 1 }, period_start: '2025-01-01', period_end: '2026-01-01' } as unknown as QuantReport
    expect(strategyScores(value)).toEqual([null, null, null, null, null, null])
  })
})

import {render,cleanup} from '@testing-library/react'
import {afterEach} from 'vitest'
import StrategyRadar from './StrategyRadar'
import type {QuantAgent} from '../types'
afterEach(cleanup)
it('draws only evaluated dimensions and explains missing dimensions',()=>{
 const agent={id:'a',name:'均线',latest_report:report([33,50,100,null,null,null])} as QuantAgent
 const {container}=render(<StrategyRadar agent={agent} peers={[]}/>);
 expect(container.querySelectorAll('[data-radar-segment]').length).toBe(2)
 expect(container.textContent).toContain('不可评估')
 expect(container.textContent).toContain('缺少可核对数据')
})
