import { expect, it } from 'vitest'
import { applySweep, formatSweepValue, numericFields, sweepGrid } from './parameterSweep'
it('enumerates inclusive decimal ranges and rejects invalid or oversized grids', () => {
  const fields = [{ key: 'x', label: 'x', value: .1 }]
  expect(sweepGrid(fields, { x: { enabled: true, from: '.1', to: '.3', step: '.1' } })).toEqual([{ x: .1 }, { x: .2 }, { x: .3 }])
  for (const step of ['0', '-1', '.0001']) expect(() => sweepGrid(fields, { x: { enabled: true, from: '.1', to: '.3', step } })).toThrow()
  expect(() => sweepGrid([{ ...fields[0], integer: true }], { x: { enabled: true, from: '2.5', to: '3', step: '1' } })).toThrow()
})
it('labels buy and sell conditions and converts percentage ranges without changing stored values', () => {
  const fields = numericFields({ custom_strategy: {
    entry: { children: [{ left: { field: 'close' }, right_indicator: { field: 'sma', period: 20 } }] },
    exit: { children: [{ left: { field: 'rsi', period: 14 }, right_value: 70 }] },
    target_position: .5,
  } })
  expect(fields.map(field => field.label)).toEqual(['买入条件1 · 参考均线长度', '卖出条件1 · 强弱指标长度', '卖出条件1 · 比较值', '持仓比例'])
  const position = fields.find(field => field.label === '持仓比例')!
  expect(formatSweepValue(position, .5)).toBe('50%')
  expect(sweepGrid([position], { [position.key]: { enabled: true, from: '50', to: '100', step: '25' } })).toEqual([
    { [position.key]: .5 }, { [position.key]: .75 }, { [position.key]: 1 },
  ])
  expect(() => sweepGrid([position], { [position.key]: { enabled: true, from: '50', to: '101', step: '25' } })).toThrow()
  expect(() => sweepGrid([position], { [position.key]: { enabled: true, from: '-1', to: '50', step: '25' } })).toThrow()
  expect(fields.every(field => !field.label.includes('custom_strategy'))).toBe(true)
})
it('applies nested visual conditions without mutating the draft', () => {
  const source = { entry: { children: [{ left: { period: 20 }, right: 3 }] } }
  expect(numericFields(source).map(x => x.key)).toEqual(['entry.children.0.left.period', 'entry.children.0.right'])
  const next = applySweep(source, { 'entry.children.0.left.period': 30 })
  expect(next.entry.children[0].left.period).toBe(30); expect(source.entry.children[0].left.period).toBe(20)
})
