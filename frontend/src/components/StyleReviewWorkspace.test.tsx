import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StyleReviewWorkspace from './StyleReviewWorkspace'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('style review workspace', () => {
  it('starts empty and loads an explicitly marked demo without saving it', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetcher)
    render(<StyleReviewWorkspace />)
    expect(screen.getByText('从一份可复核的报告开始')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '载入75% → 85%示例' }))
    expect((screen.getByLabelText('基金代码 / 内部唯一编号') as HTMLInputElement).value).toBe('DEMO-CONSUMER')
    expect((screen.getByLabelText('这是一份演示或合成数据') as HTMLInputElement).checked).toBe(true)
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  })

  it('shows validation failures without claiming a saved report', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: '版本已存在，请创建新版本' }) }))
    render(<StyleReviewWorkspace />)
    fireEvent.click(screen.getByRole('button', { name: '载入75% → 85%示例' }))
    fireEvent.submit(screen.getByRole('button', { name: '核验并保存快照' }).closest('form')!)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('版本已存在'))
    expect(screen.getByLabelText('基金名称')).toBeTruthy()
  })

  it('exports only on demand and explains verification limitations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
    render(<StyleReviewWorkspace />)
    fireEvent.click(screen.getByRole('button', { name: '复核包验证' }))
    expect(screen.getByText(/同时篡改输入、结果和摘要可能通过/)).toBeTruthy()
    expect(screen.getByLabelText('选择JSON复核包')).toBeTruthy()
  })
})
