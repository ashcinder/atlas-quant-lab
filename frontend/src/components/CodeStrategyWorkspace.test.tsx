import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../request'
import { STRATEGY_LANGUAGES, languageForFile } from './strategy-languages'
import { CodeStrategyWorkspace, RUNNABLE_PYTHON_TEMPLATE } from './CodeStrategyWorkspace'
import type { BacktestResult } from '../types'

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
  expect((screen.getByLabelText(`${language.label} 策略代码`) as HTMLTextAreaElement).value).toBe(language.id === 'python' ? RUNNABLE_PYTHON_TEMPLATE : language.template)
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

const checked = { valid: true, error: null, syntax_valid: true, backtest_compatible: true, proof_compatible: true, dry_run: { passed: true, synthetic: true, scenarios: 4, bars_per_scenario: 520 } }

it('uses the platform check and distinguishes compatibility from real backtests and Proof', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true } : checked)
  await open()
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  await screen.findByText('代码检测通过')
  expect(request).toHaveBeenLastCalledWith('/strategy-code/validate', expect.objectContaining({ body: JSON.stringify({ code: RUNNABLE_PYTHON_TEMPLATE, language: 'python', profile: 'bounded' }) }))
  expect(screen.getByText(/语法：通过 · 回测兼容：通过 · 证明兼容：通过 · 合成试跑：通过/)).toBeTruthy()
  expect(screen.getByText('使用合成行情检查执行兼容性；不是历史回测，未生成 Proof。')).toBeTruthy()
})

it('shows the exact semantic error even when ordinary Python syntax is valid', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true } : { ...checked, valid: false, backtest_compatible: false, proof_compatible: false, dry_run: null, error: { message: '价格乘法推导范围超出限制', line: 2, offset: 14, kind: 'numeric_bounds' } })
  await open()
  fireEvent.click(screen.getByRole('button', { name: '检查代码' }))
  await screen.findByText('第 2 行，第 14 列：价格乘法推导范围超出限制')
  expect(screen.getByText(/语法：通过 · 回测兼容：未通过 · 证明兼容：未通过/)).toBeTruthy()
})

it('requests structured rules, previews checked code and waits for explicit application', async () => {
  const candidate = 'def target_bps(index, close, sma):\n    return 3000 if sma(5) > sma(20) else 0\n'
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true } : { explanation: '均线过滤与分档仓位', code: candidate, validation: checked })
  await open()
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '写一个复杂点的策略' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByText('均线过滤与分档仓位')
  expect(request).toHaveBeenLastCalledWith('/strategy-code/assist', expect.objectContaining({ body: JSON.stringify({ prompt: '写一个复杂点的策略', code: RUNNABLE_PYTHON_TEMPLATE, language: 'python', generation_mode: 'rules' }) }), 120000)
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(RUNNABLE_PYTHON_TEMPLATE)
  fireEvent.click(screen.getByRole('button', { name: '应用到编辑器' }))
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(candidate)
})

it('retains a failed candidate for inspection and prevents applying it', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true } : { explanation: '候选未能通过', code: 'def target_bps(index, close, sma):\n    return 9501', validation: { ...checked, valid: false, dry_run: null, error: { message: '仓位超出9500', line: 2, offset: 5 } } })
  await open()
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '保持全部条件' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByText('候选未能通过')
  expect(screen.getByText('第 2 行，第 5 列：仓位超出9500')).toBeTruthy()
  const apply = screen.getByRole('button', { name: '应用到编辑器' }) as HTMLButtonElement
  expect(apply.disabled).toBe(true)
  expect(screen.getByText('查看建议代码 · 2 行')).toBeTruthy()
  fireEvent.click(apply)
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(RUNNABLE_PYTHON_TEMPLATE)
})

it('sends previous suggestions for follow-ups while preserving the unapplied editor', async () => {
  const candidate = 'def target_bps(index, close, sma):\n    return 3000 if sma(5) > sma(20) else 0\n'
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true, conversation_context: true } : { explanation: '第一轮均线建议', code: candidate, validation: checked })
  await open()
  const prompt = screen.getByLabelText('告诉 AI 你想实现什么')
  fireEvent.change(prompt, { target: { value: '先写一个简单策略' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByText('第一轮均线建议')
  fireEvent.change(prompt, { target: { value: '在刚才建议上改成几十行多条件策略' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => {
    const assist = vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/assist'))
    expect(assist).toHaveLength(2)
    const body = JSON.parse(assist[1][1]!.body as string)
    expect(body.history).toEqual([
      { role: 'user', content: '先写一个简单策略' },
      { role: 'assistant', content: `第一轮均线建议\n此前建议代码（不代表已应用，当前编辑器代码另行提供）：\n${candidate}` },
    ])
    expect(body.code).toBe(RUNNABLE_PYTHON_TEMPLATE)
    expect(body.prompt).toBe('在刚才建议上改成几十行多条件策略')
  })
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(RUNNABLE_PYTHON_TEMPLATE)
})

it('bounds long conversation history and clears it when switching languages', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true, conversation_context: true } : { explanation: '长建议', code: 'x'.repeat(8000) })
  await open()
  for (let turn = 0; turn < 5; turn += 1) {
    fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: `问题${turn}` } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(screen.getAllByText('长建议')).toHaveLength(turn + 1))
  }
  const assist = vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/assist'))
  const body = JSON.parse(assist.at(-1)![1]!.body as string)
  expect(body.history).toHaveLength(6)
  expect(body.history[0].content).toBe('问题1')
  expect(body.history.every((turn: { content: string }) => turn.content.length <= 4000)).toBe(true)
  expect(body.history.at(-1).content).toContain('[历史消息过长，已截断]')
  fireEvent.change(screen.getByLabelText('策略编程语言'), { target: { value: 'cpp' } })
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '新语言问题' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => {
    const latest = vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/assist')).at(-1)!
    expect(JSON.parse(latest[1]!.body as string).history).toEqual([])
  })
})

it('shows unsupported requirements without offering replacement code', async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith('/capabilities') ? { configured: true, model: 'local-test', bounded_authoring: true } : { explanation: '当前不支持持仓成本止损，请调整需求。', code: '' })
  await open()
  fireEvent.change(screen.getByLabelText('告诉 AI 你想实现什么'), { target: { value: '成本止损' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByText('当前不支持持仓成本止损，请调整需求。')
  expect(screen.queryByRole('button', { name: '应用到编辑器' })).toBeNull()
  expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(RUNNABLE_PYTHON_TEMPLATE)
})

it('refreshes the visible model status when AI settings change', async () => {
  await open()
  vi.mocked(request).mockResolvedValue({configured:true,model:'deepseek-flash'})
  act(()=>window.dispatchEvent(new Event('atlas-ai-config-changed')))
  expect(await screen.findByText('deepseek-flash 已配置')).toBeTruthy()
})

it('asks for a bounded minute range before submitting a potentially huge history', async () => {
  const { api }=await import('../api')
  const run=vi.spyOn(api,'runBacktest')
  render(<CodeStrategyWorkspace research={{asset:{symbol:'BTC-USD',name:'Bitcoin',asset_class:'crypto',exchange:'CRYPTO',currency:'USD',timezone:'UTC',tags:[]},strategies:[],interval:'1m',source:'auto',initialCapital:10000,commission:.001,slippage:0,spread:0,maxPosition:.5,maxParticipation:.01,onLoading:vi.fn(),onError:vi.fn(),onCustomResult:vi.fn()}} />)
  fireEvent.click(screen.getByRole('button',{name:'运行回测'}))
  expect(await screen.findByText('请先设置分钟回测的开始与结束时间。')).toBeTruthy()
  expect(run).not.toHaveBeenCalled()
  run.mockRestore()
})

it('blocks real backtest execution when the current code fails compatibility validation', async () => {
  const { api }=await import('../api')
  const run=vi.spyOn(api,'runBacktest')
  vi.mocked(request).mockImplementation(async path=>path.endsWith('/capabilities')?{configured:true,model:'local-test',bounded_authoring:true}:{valid:false,error:{message:'不支持的代码'},backtest_compatible:false})
  render(<CodeStrategyWorkspace research={{asset:{symbol:'603986.SS',name:'兆易创新',asset_class:'equity',exchange:'SSE',currency:'CNY',timezone:'Asia/Shanghai',tags:[]},strategies:[],interval:'1d',source:'auto',initialCapital:10000,commission:.001,slippage:0,spread:0,maxPosition:.5,maxParticipation:.01,onLoading:vi.fn(),onError:vi.fn(),onCustomResult:vi.fn()}} />)
  await screen.findByText('local-test 已配置')
  fireEvent.click(screen.getByRole('button',{name:'运行回测'}))
  expect(await screen.findAllByText('不支持的代码')).not.toHaveLength(0)
  expect(run).not.toHaveBeenCalled()
  run.mockRestore()
})

it.each(['atlas','vnpy','rqalpha'] as const)('submits unchanged general Python to %s without the bounded-language gate',async(engine)=>{
 const {api}=await import('../api')
 const run=vi.spyOn(api,'runBacktest').mockResolvedValue({backtest_engine:engine,trades:[]} as unknown as BacktestResult)
 vi.stubGlobal('crypto',{subtle:{digest:async()=>new ArrayBuffer(32)}})
 try {
  const onCustomResult=vi.fn()
  render(<CodeStrategyWorkspace research={{asset:{symbol:'300750.SZ',name:'宁德时代',asset_class:'equity',exchange:'SZSE',currency:'CNY',timezone:'Asia/Shanghai',tags:[]},strategies:[],interval:'1m',source:'huggingface',initialCapital:100000,commission:.001,slippage:0,spread:0,maxPosition:.95,maxParticipation:.01,onLoading:vi.fn(),onError:vi.fn(),onCustomResult}} />)
  await screen.findByText('local-test 已配置')
  const code='def initialize(c):\n    c.state["n"]=0\ndef target(c):\n    c.state["n"]+=1\n    return 0.4 if c.state["n"]>20 else 0\n'
  fireEvent.change(screen.getByLabelText('Python 策略代码'),{target:{value:code}})
  fireEvent.change(screen.getByLabelText('代码回测框架'),{target:{value:engine}})
  fireEvent.click(screen.getByRole('button',{name:'运行回测'}))
  await waitFor(()=>expect(onCustomResult).toHaveBeenCalled())
  expect(run).toHaveBeenCalledWith(expect.objectContaining({backtest_engine:engine,execution_model:'unified',strategy_id:'python_portable',portable_python:code,python_source:undefined,start:null,end:null}),expect.any(AbortSignal))
  expect(request).toHaveBeenCalledTimes(1)
  expect(onCustomResult).toHaveBeenCalledWith(expect.objectContaining({backtest_engine:engine}),expect.objectContaining({source:code,strategyKind:'python_portable'}))
 } finally {run.mockRestore();vi.unstubAllGlobals()}
})

const workspaceResearch={asset:{symbol:'300750.SZ',name:'宁德时代',asset_class:'equity',exchange:'SZSE',currency:'CNY',timezone:'Asia/Shanghai',tags:[]},strategies:[],interval:'1d' as const,source:'huggingface' as const,initialCapital:100000,commission:.001,slippage:0,spread:0,maxPosition:.95,maxParticipation:.01,onLoading:vi.fn(),onError:vi.fn(),onCustomResult:vi.fn()}

it('offers a usable starting point for an empty draft and opens examples without discarding code',async()=>{
 render(<CodeStrategyWorkspace research={workspaceResearch}/>)
 const editor=screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement
 fireEvent.change(editor,{target:{value:''}})
 expect((screen.getByRole('button',{name:'运行回测'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText('从一个想法，开始一份策略')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'载入通用 Python 示例'}))
 expect(editor.value).toContain('def target(context):')
 expect(screen.queryByRole('alertdialog')).toBeNull()
 fireEvent.click(screen.getByLabelText('代码文件与工具'))
 fireEvent.click(screen.getByRole('button',{name:/载入 Python 示例/}))
 expect(screen.getByRole('alertdialog')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'取消，保留当前内容'}))
 expect(editor.value).toContain('def target(context):')
})

it('closes the file menu with Escape or an outside click',async()=>{
 await open()
 const summary=screen.getByLabelText('代码文件与工具'),menu=summary.closest('details')!
 fireEvent.click(summary);expect(menu.open).toBe(true)
 fireEvent.keyDown(window,{key:'Escape'});expect(menu.open).toBe(false)
 fireEvent.click(summary);expect(menu.open).toBe(true)
 fireEvent.pointerDown(screen.getByLabelText('Python 策略代码'));expect(menu.open).toBe(false)
})

it('uses edited backtest settings and the keyboard shortcut for all framework requests',async()=>{
 const {api}=await import('../api')
 const run=vi.spyOn(api,'runBacktest').mockResolvedValue({backtest_engine:'vnpy',trades:[]} as unknown as BacktestResult)
 vi.stubGlobal('crypto',{subtle:{digest:async()=>new ArrayBuffer(32)}})
 try{
  const onCustomResult=vi.fn()
  render(<CodeStrategyWorkspace research={{...workspaceResearch,onCustomResult}}/>)
  const editor=screen.getByLabelText('Python 策略代码')
  fireEvent.change(editor,{target:{value:'def target(c):\n    return 0.4\n'}})
  fireEvent.change(screen.getByLabelText('代码回测框架'),{target:{value:'vnpy'}})
  fireEvent.click(screen.getByText('资金与交易成本'))
  fireEvent.change(screen.getByLabelText('代码回测初始资金'),{target:{value:'250000'}})
  fireEvent.change(screen.getByLabelText('代码回测手续费率'),{target:{value:'0.05'}})
  fireEvent.keyDown(editor,{key:'Enter',ctrlKey:true})
  await waitFor(()=>expect(onCustomResult).toHaveBeenCalled())
  expect(run).toHaveBeenCalledWith(expect.objectContaining({initial_capital:250000,commission_rate:.0005,backtest_engine:'vnpy'}),expect.any(AbortSignal))
  expect(onCustomResult).toHaveBeenCalledWith(expect.anything(),expect.objectContaining({backtestSettings:expect.objectContaining({capital:250000,commission:.0005})}))
 }finally{run.mockRestore();vi.unstubAllGlobals()}
})

it('keeps the assistant available without a model and leads directly to connection settings',async()=>{
 vi.mocked(request).mockResolvedValue({configured:false})
 render(<CodeStrategyWorkspace research={workspaceResearch}/>)
 fireEvent.click(screen.getByRole('tab',{name:'AI 助手'}))
 fireEvent.click(screen.getByRole('button',{name:'连接 AI 服务'}))
 expect(await screen.findByLabelText('API Key')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:/返回对话/}))
 expect((screen.getByRole('button',{name:'发送'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('tab',{name:'回测设置'}))
 expect(screen.getByLabelText('代码回测标的')).toBeTruthy()
})

it('cancels a pending code check and preserves the source',async()=>{
 vi.mocked(request).mockImplementation(async(path,options)=>{
  if(path.endsWith('/capabilities'))return {configured:false}
  if(path==='/strategy-code/validate')return new Promise((_,reject)=>options?.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))
  return {configured:false}
 })
 render(<CodeStrategyWorkspace research={workspaceResearch}/>)
 fireEvent.click(screen.getByRole('button',{name:'检查代码'}))
 fireEvent.click(await screen.findByRole('button',{name:'停止本次执行'}))
 expect(await screen.findByText('已取消本次检查，代码已保留。')).toBeTruthy()
 expect((screen.getByLabelText('Python 策略代码') as HTMLTextAreaElement).value).toBe(RUNNABLE_PYTHON_TEMPLATE)
})
