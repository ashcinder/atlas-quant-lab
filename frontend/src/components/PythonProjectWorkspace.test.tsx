import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { inspectPythonProject, runPythonProject } from '../compute/pythonProject'
import PythonProjectWorkspace from './PythonProjectWorkspace'

vi.mock('../compute/pythonProject', () => ({
  inspectPythonProject: vi.fn(),
  runPythonProject: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('keeps the configured entry when opening a helper and changes it only on request', async () => {
  const archive = new File(['archive'], 'strategies.zip')
  const strategy = 'research/main.py'
  const helper = 'research/helpers.py'
  vi.mocked(inspectPythonProject).mockResolvedValue({
    root: 'research',
    scripts: [helper, strategy],
    files: [helper, strategy].map(path => ({ path, size: 1 })),
    sources: { [helper]: '# helper', [strategy]: '# entry' },
  })
  vi.mocked(runPythonProject).mockResolvedValue({ log: '', summaries: [], warnings: [], archive: new Blob() })

  render(<PythonProjectWorkspace draftToolbar={null} draftFilename="draft.py" draftDirty={false}
    incomingArchive={{ file: archive }} importDisabled={false} onOpenArchive={() => undefined}>
    <div>策略草稿</div>
  </PythonProjectWorkspace>)

  const editor = await screen.findByRole('region', { name: 'Python 项目工作区' })
  const entry = within(editor).getByRole('combobox', { name: '运行入口' })
  expect(entry).toHaveValue(strategy)

  const explorer = screen.getByRole('complementary', { name: '文件资源管理器' })
  fireEvent.click(within(explorer).getByRole('button', { name: 'helpers.py' }))
  expect(within(editor).getByRole('textbox', { name: '项目 Python 源码' })).toHaveValue('# helper')
  expect(entry).toHaveValue(strategy)

  fireEvent.click(within(editor).getByRole('button', { name: '运行脚本' }))
  await waitFor(() => expect(runPythonProject).toHaveBeenCalledWith(archive, strategy, {}, expect.any(AbortSignal)))
  await waitFor(() => expect(within(editor).getByRole('button', { name: '设为入口' })).toBeEnabled())
  fireEvent.click(within(editor).getByRole('button', { name: '设为入口' }))
  expect(entry).toHaveValue(helper)
})
