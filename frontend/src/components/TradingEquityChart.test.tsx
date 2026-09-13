import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import TradingEquityChart from './TradingEquityChart'
import type { StrategyRun } from '../types'
afterEach(cleanup)
const run = { strategy_name: '持续测试', currency: 'USDT', curve: [
  { bar_time: 1800000000, equity: '200', return_rate: '0' },
  { bar_time: 1800000012, equity: '199.8', return_rate: '-0.001' },
] } as StrategyRun
it('browses real snapshots with the keyboard and restores latest on blur', () => {
  render(<TradingEquityChart run={run} />)
  const chart = screen.getByRole('img', { name: '持续测试 净值曲线，共 2 个快照' })
  expect(screen.getByText('-0.10%')).toBeTruthy()
  fireEvent.keyDown(chart, { key: 'ArrowLeft' })
  expect(screen.getByText('历史策略净值')).toBeTruthy()
  expect(screen.getByText('+0.00%')).toBeTruthy()
  fireEvent.blur(chart)
  expect(screen.getByText('最新策略净值')).toBeTruthy()
  expect(screen.getByText('-0.10%')).toBeTruthy()
})
it('shows a finite visible point for one unchanged snapshot', () => {
  const { container } = render(<TradingEquityChart run={{ ...run, curve: run.curve!.slice(0, 1) }} />)
  const marker = container.querySelector('circle')!
  expect(Number.isFinite(Number(marker.getAttribute('cy')))).toBe(true)
  expect(container.querySelector('path')?.getAttribute('d')).not.toMatch(/NaN|Infinity/)
})
