import type { QuantAgent, QuantReport, QuantVerification, StrategyRun } from '../types'

// Explicit allowlists: never serialize the entire API object or private runner configuration.
export function reportSummary(agent: QuantAgent, report: QuantReport, verification: QuantVerification | null) {
  return {
    summary_version: 'atlas_summary_v1', kind: 'strategy_report',
    strategy: { id: agent.id, name: agent.name, commitment: agent.strategy_commitment },
    report: { id: report.id, type: report.report_type, period_start: report.period_start, period_end: report.period_end,
      market_data_hash: report.market_data_hash || null, data_source: null, environment: null, fees: null, valuation_at: null, behavior_check: null,
      metrics: Object.fromEntries(['total_return', 'annualized_return', 'max_drawdown', 'sharpe', 'sortino', 'annualized_volatility', 'trade_count'].map(key => [key, Number.isFinite(report.metrics[key]) ? report.metrics[key] : null])), performance_score: report.performance_score ?? null,
      performance_score_version: report.performance_score_version ?? null },
    evidence: { level: report.evidence_level ?? null, proof_id: report.zk_proof_id ?? null,
      receipt_integrity_valid: report.receipt_integrity_valid, public_curve_integrity_valid: report.public_curve_integrity_valid,
      verified_this_session: verification?.calculation_verified ?? false,
      external_proof_verified: verification?.external_proof_verified ?? false,
      chain_status: verification?.chain.status ?? report.chain_status,
      source_authenticated: false, full_account_coverage_verified: false },
    proof_url: report.zk_proof_id ? `${window.location.origin}${window.location.pathname}#/proof/${encodeURIComponent(report.zk_proof_id)}` : null,
    limitations: ['报告类型不等于来源认证；表现分是实验性指标换算。', '新增仓位偏离规则不在现有 ZKP 范围内。', '未记录的信息为 null，不从其他报告补齐。'],
  }
}

export function runSummary(run: StrategyRun) {
  return {
    summary_version: 'atlas_summary_v1', kind: 'strategy_run',
    strategy: { name: run.strategy_name, release_id: run.release_id, version: run.strategy_version, commitment: run.strategy_hash },
    run: { id: run.id, market: run.market, symbol: run.symbol, interval: run.interval, environment: run.environment, status: run.status },
    valuation: { at: run.valuation_at ?? null, status: run.valuation_status ?? 'missing', complete: run.valuation_complete ?? null,
      currency: run.currency ?? null, equity: run.valuation_at != null ? run.equity : null,
      return_rate: run.valuation_at != null && run.valuation_complete !== false ? run.return_rate : null,
      initial_cash: run.initial_cash, position_value: run.valuation_at != null ? run.position_value ?? null : null,
      period_start: run.curve?.[0]?.bar_time ?? null, period_end: run.curve?.at(-1)?.bar_time ?? null, snapshot_count: run.curve?.length ?? 0 },
    costs: { commission_rate: run.commission_rate ?? null, slippage_rate: run.slippage_rate ?? null, valuation_complete: run.valuation_complete ?? null,
      valuation_note: run.valuation_complete === false ? '估值不完整；未折算费用或缺数以运行页面提示为准。' : null },
    behavior_check: run.behavior_check ? {
      rule_version: run.behavior_check.rule_version, status: run.behavior_check.status, reason: run.behavior_check.reason,
      limit_bps: run.behavior_check.limit_bps, period_start: run.behavior_check.period_start, period_end: run.behavior_check.period_end,
      snapshot_count: run.behavior_check.snapshot_count, latest_ratio: run.behavior_check.latest_ratio, peak_ratio: run.behavior_check.peak_ratio,
      deviation_count: run.behavior_check.deviation_count, first_deviation_at: run.behavior_check.first_deviation_at,
      points: run.behavior_check.points.map(point => ({ time: point.time, ratio: point.ratio })),
    } : null,
    evidence: { calculation: 'ordinary_rule_calculation', source_authenticated: false, zk_proven: false },
    limitations: ['仅覆盖该运行已记录的估值点，不代表完整账户或实时监控。', '仓位约束偏离不等同于基金风格漂移、违规认定或 ZKP 证明。'],
  }
}

export function summaryText(value: unknown): string {
  return value === null || value === undefined ? '未记录' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
