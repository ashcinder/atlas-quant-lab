import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { formatFundamentalMetric } from '../fundamentalsFormat'
import type { FundamentalMetric, FundamentalsResponse } from '../types'
import { FundamentalsPanel } from './FundamentalsPanel'

afterEach(cleanup)

const asset = {
  symbol: 'AAPL', name: 'Apple', asset_class: 'equity', exchange: 'NASDAQ',
  currency: 'USD', timezone: 'America/New_York', tags: ['美股'],
}

const response: FundamentalsResponse = {
  asset,
  status: 'partial',
  source: 'Test Provider',
  source_note: 'fixture',
  fetched_at: 1_788_268_800,
  as_of: 1_788_268_800,
  cache_hit: false,
  is_stale: false,
  currency: 'USD',
  financial_currency: 'USD',
  available_metric_count: 2,
  total_metric_count: 3,
  coverage: 2 / 3,
  sections: [{
    id: 'valuation',
    label: '估值',
    metrics: [
      { key: 'trailing_pe', label: '市盈率 PE (TTM)', value: 24.5, unit: 'ratio', period: 'TTM', description: 'PE', derived: false, currency: null },
      { key: 'price_to_book', label: '市净率 PB', value: 6.2, unit: 'ratio', period: 'MRQ', description: 'PB', derived: false, currency: null },
      { key: 'earnings_yield', label: '盈利收益率', value: null, unit: 'percent', period: 'TTM', description: 'yield', derived: true, currency: null },
    ],
  }],
  warnings: ['缺失字段保持为空'],
}

describe('FundamentalsPanel', () => {
  it('shows PE, PB, coverage, source and transparent missing values', () => {
    render(<FundamentalsPanel asset={asset} data={response} loading={false} error={null} onLoad={vi.fn()} />)

    expect(screen.getByText('市盈率 PE (TTM)')).toBeTruthy()
    expect(screen.getByText('24.5×')).toBeTruthy()
    expect(screen.getByText('市净率 PB')).toBeTruthy()
    expect(screen.getByText('6.2×')).toBeTruthy()
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.getByText('Test Provider')).toBeTruthy()
    expect(screen.getByLabelText('已返回 2 / 3 项指标')).toBeTruthy()
    expect(screen.getByText('覆盖率 67%')).toBeTruthy()
  })

  it('requests an explicit refresh', () => {
    const onLoad = vi.fn()
    render(<FundamentalsPanel asset={asset} data={response} loading={false} error={null} onLoad={onLoad} />)

    fireEvent.click(screen.getByTitle('刷新金融指标'))
    expect(onLoad).toHaveBeenCalledWith(true)
  })

  it('formats percent, currency and unavailable metrics consistently', () => {
    const base: FundamentalMetric = {
      key: 'metric', label: 'Metric', value: 0.125, unit: 'percent', period: 'TTM',
      description: '', derived: false, currency: null,
    }
    expect(formatFundamentalMetric(base)).toBe('12.50%')
    expect(formatFundamentalMetric({ ...base, value: 1_250_000, unit: 'currency', currency: 'USD' })).toContain('USD')
    expect(formatFundamentalMetric({ ...base, value: null })).toBe('—')
  })
})
