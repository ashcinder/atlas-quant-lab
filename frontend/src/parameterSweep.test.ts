import { expect, it } from 'vitest'
import { applySweep, numericFields, sweepGrid } from './parameterSweep'
it('enumerates inclusive decimal ranges and rejects invalid or oversized grids', () => {
  const fields = [{ key: 'x', label: 'x', value: .1 }]
  expect(sweepGrid(fields, { x: { enabled: true, from: '.1', to: '.3', step: '.1' } })).toEqual([{ x: .1 }, { x: .2 }, { x: .3 }])
  for (const step of ['0', '-1', '.0001']) expect(() => sweepGrid(fields, { x: { enabled: true, from: '.1', to: '.3', step } })).toThrow()
  expect(() => sweepGrid([{ ...fields[0], integer: true }], { x: { enabled: true, from: '2.5', to: '3', step: '1' } })).toThrow()
})
it('applies nested visual conditions without mutating the draft', () => {
  const source = { entry: { children: [{ left: { period: 20 }, right: 3 }] } }
  expect(numericFields(source).map(x => x.key)).toEqual(['entry.children.0.left.period', 'entry.children.0.right'])
  const next = applySweep(source, { 'entry.children.0.left.period': 30 })
  expect(next.entry.children[0].left.period).toBe(30); expect(source.entry.children[0].left.period).toBe(20)
})
