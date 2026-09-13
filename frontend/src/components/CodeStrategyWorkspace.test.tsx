import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../request'
import { STRATEGY_LANGUAGES, languageForFile } from './strategy-languages'
import { CodeStrategyWorkspace } from './CodeStrategyWorkspace'

vi.mock('../request', () => ({ request: vi.fn() }))
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(request).mockImplementation(async (path) => path.endsWith('/capabilities') ? { configured: true, model: 'local-test' } : { valid: true, error: null }) })
afterEach(cleanup)
async function open() { const result = render(<CodeStrategyWorkspace />); await screen.findByText('local-test 已配置'); return result }

describe('code strategy editor', () => {
  it('shows an honest disconnected state and disables generation', async () => {
    vi.mocked(request).mockResolvedValue({ configured: false })
    render(<CodeStrategyWorkspace />)
    await screen.findByText('尚未配置模型')
    fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '写策略' } })
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.keyDown(screen.getByLabelText('告诉 AI 你想实现什么'), { key: 'Enter' })
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('previews generated code without changing editor and guards newer edits', async () => {
    const response = deferred<{ explanation: string; code: string }>()
    vi.mocked(request).mockImplementation(async (path) => path.endsWith('/capabilities') ? { configured: true, model: 'local-test' } : response.promise)
    await open()
    const editor = screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement
    fireEvent.change(editor, { target: { value: '# submitted code' } })
    fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '增加止损' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    expect(request).toHaveBeenLastCalledWith('/strategy-code/assist', expect.objectContaining({ body: JSON.stringify({ prompt: '增加止损', code: '# submitted code', language: 'python' }) }), 90000)
    fireEvent.change(editor, { target: { value: '# my newer edits' } })
    await act(async () => response.resolve({ explanation: '加入了限额', code: '# generated' }))
    expect(editor.value).toBe('# my newer edits')
    fireEvent.click(screen.getByRole('button', { name: '应用到编辑器' }))
    expect(screen.getByRole('alertdialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '取消，保留当前内容' }))
    expect(editor.value).toBe('# my newer edits')
    fireEvent.click(screen.getByRole('button', { name: '应用到编辑器' }))
    fireEvent.click(screen.getByRole('button', { name: '替换代码' }))
    expect(editor.value).toBe('# generated')
    fireEvent.click(screen.getByRole('button', { name: '撤销替换' }))
    expect(editor.value).toBe('# my newer edits')
  })
  it('ignores late generation after cancellation', async () => {
    const response = deferred<{ explanation: string; code: string }>()
    vi.mocked(request).mockImplementation(async (path) => path.endsWith('/capabilities') ? { configured: true, model: 'local-test' } : response.promise)
    await open()
    fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '写策略' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    fireEvent.click(screen.getByRole('button', { name: '停止' }))
    await act(async () => response.resolve({ explanation: 'late response', code: '# late' }))
    expect(screen.queryByText('late response')).toBeNull()
    expect(screen.queryByRole('button', { name: '应用到编辑器' })).toBeNull()
  })
  it('does not display stale syntax results on newly edited code', async () => {
    const response = deferred<{ valid: boolean; error: null }>()
    vi.mocked(request).mockImplementation(async (path) => path.endsWith('/capabilities') ? { configured: true, model: 'local-test' } : response.promise)
    await open()
    fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
    fireEvent.change(screen.getByLabelText('Python 策略代码'), { target: { value: 'def broken(' } })
    await act(async () => response.resolve({ valid: true, error: null }))
    expect(screen.queryByText('语法检查通过')).toBeNull()
    expect(screen.getByText('代码已修改，请重新检查当前版本。')).toBeTruthy()
  })
  it('imports a Python file only after confirming replacement of dirty code', async () => {
    const { container } = await open()
    const editor = screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement
    fireEvent.change(editor, { target: { value: '# keep this' } })
    const file = new File(['# imported'], 'imported.py')
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('# imported').buffer })
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
    await screen.findByRole('alertdialog')
    expect(editor.value).toBe('# keep this')
    fireEvent.click(screen.getByRole('button', { name: '替换代码' }))
    expect(editor.value).toBe('# imported')
    expect((screen.getByLabelText('代码策略名称') as HTMLInputElement).value).toBe('imported')
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('shows provider errors and restores the prompt for retry', async () => {
    vi.mocked(request).mockImplementation(async (path) => {
      if (path.endsWith('/capabilities')) return { configured: true, model: 'local-test' }
      throw new Error('模型暂时不可用')
    })
    await open()
    fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '解释代码' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('模型暂时不可用'))
    expect((screen.getByLabelText('告诉 AI 你想实现什么') as HTMLTextAreaElement).value).toBe('解释代码')
  })
})

it('keeps separate language drafts and sends the selected language to AI', async () => {
  await open()
  fireEvent.change(screen.getByLabelText('Python 策略代码'), { target: { value: '# saved python draft' } })
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'cpp' } })
  expect((screen.getByLabelText('C++ 策略代码') as HTMLTextAreaElement).value).toContain('#include <vector>')
  expect((screen.getByRole('button', { name: '检查代码' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('C++ 策略代码'), { target: { value: '// cpp draft' } })
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '解释代码' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(request).toHaveBeenLastCalledWith('/strategy-code/assist', expect.objectContaining({ body: JSON.stringify({ prompt: '解释代码', code: '// cpp draft', language: 'cpp' }) }), 90000))
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'python' } })
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe('# saved python draft')
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'cpp' } })
  expect((screen.getByLabelText('C++ 策略代码') as HTMLTextAreaElement).value).toBe('// cpp draft')
})

it('detects the source extension on import and preserves the other language draft', async () => {
  const { container } = await open()
  fireEvent.change(screen.getByLabelText('Python 策略代码'), { target: { value: '# keep python' } })
  const file = new File(['// imported rust'], 'signal.RS')
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('// imported rust').buffer })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  await screen.findByRole('alertdialog')
  fireEvent.click(screen.getByRole('button', { name: '替换代码' }))
  expect((screen.getByLabelText('策略编程语言') as HTMLSelectElement).value).toBe('rust')
  expect((screen.getByLabelText('Rust 策略代码') as HTMLTextAreaElement).value).toBe('// imported rust')
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'python' } })
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe('# keep python')
})

it('discards an AI response after switching languages', async () => {
  const response = deferred<{ explanation: string; code: string }>()
  vi.mocked(request).mockImplementation(async (path) => path.endsWith('/capabilities') ? { configured: true, model: 'local-test' } : response.promise)
  await open()
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '写策略' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'java' } })
  await act(async () => response.resolve({ explanation: 'old python response', code: '# stale' }))
  expect(screen.queryByText('old python response')).toBeNull()
  expect((screen.getByLabelText('Java 策略代码') as HTMLTextAreaElement).value).toContain('class Strategy')
})


it.each(STRATEGY_LANGUAGES)('loads and downloads the $label source with its extension', async (language) => {
  await open()
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: language.id } })
  expect((screen.getByLabelText(`${language.label} 策略代码`) as HTMLTextAreaElement).value).toBe(language.template)
  for (const extension of language.extensions) expect(languageForFile(`strategy${extension.toUpperCase()}`)?.id).toBe(language.id)
  const create = vi.fn(() => 'blob:test')
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }))
  let downloaded = ''
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { downloaded = this.download })
  fireEvent.click(screen.getByRole('button', { name: '下载保存' }))
  expect(downloaded).toBe(`我的均线策略${language.extensions[0]}`)
  expect(create).toHaveBeenCalledOnce()
  click.mockRestore(); vi.unstubAllGlobals()
})
