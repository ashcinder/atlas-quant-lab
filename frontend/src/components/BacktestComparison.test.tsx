import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ComparisonRow } from '../compute/compareBacktests'
import type { BacktestResult } from '../types'
import { BacktestComparison } from './BacktestComparison'

vi.mock('./ResultsPanel', () => ({
  ResultsPanel: ({ result }: { result: BacktestResult }) => <p>{result.run_id}</p>,
}))
afterEach(cleanup)

function completed(engine: ComparisonRow['engine']): ComparisonRow {
  return { engine, status: 'completed', result: {
    run_id: 'report-' + engine, engine_version: 'test', trades: [], metrics: { total_return: 0.05, max_drawdown: -0.01 },
  } as unknown as BacktestResult }
}

it('opens the first completed report and switches among all three without rerunning', () => {
  const running: ComparisonRow = { engine: 'rqalpha', status: 'running' }
  const rows = [completed('atlas'), completed('vnpy'), running]
  const { rerender } = render(<BacktestComparison rows={rows} />)
  const region = screen.getByRole('region', { name: '三框架回测结果' })
  const tabList = within(region).getByRole('tablist', { name: '回测引擎' })
  const report = () => within(region).getByRole('tabpanel')
  expect(report()).toHaveTextContent('report-atlas')
  fireEvent.click(within(tabList).getByRole('tab', { name: 'vn.py' }))
  expect(report()).toHaveTextContent('report-vnpy')
  fireEvent.keyDown(within(tabList).getByRole('tab', { name: 'vn.py' }), { key: 'ArrowRight' })
  expect(report()).toHaveTextContent('RQAlpha · 回测中')
  rerender(<BacktestComparison rows={[...rows.slice(0, 2), completed('rqalpha')]} />)
  expect(report()).toHaveTextContent('report-rqalpha')
  expect(within(tabList).getByRole('tab', { name: 'RQAlpha' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(within(tabList).getByRole('tab', { name: 'Trine' }))
  expect(report()).toHaveTextContent('report-atlas')
})
