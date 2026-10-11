import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import RegulatoryWorkspace from './RegulatoryWorkspace'
import DisclosureReviewWorkspace from './DisclosureReviewWorkspace'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('groups both functions and preserves the disclosure draft when switching', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
  render(<RegulatoryWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: '信息披露一致性核验', exact: true }))
  fireEvent.click(screen.getByRole('button', { name: '载入披露差异示例' }))
  fireEvent.click(screen.getByRole('button', { name: '风格监管', exact: true }))
  fireEvent.click(screen.getByRole('button', { name: '信息披露一致性核验', exact: true }))
  expect((screen.getByLabelText('披露来源与页码 / 表名') as HTMLInputElement).value).toContain('合成季度报告')
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
})

it('reports invalid input without displaying a successful snapshot', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: '证券代码重复' }) }))
  render(<DisclosureReviewWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: '载入披露差异示例' }))
  fireEvent.submit(screen.getByRole('button', { name: '对比并保存核验快照' }).closest('form')!)
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('证券代码重复'))
  expect(screen.queryByLabelText('披露核验结果')).toBeNull()
})
