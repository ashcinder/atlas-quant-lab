import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Code2, LockKeyhole, Plus, Upload } from 'lucide-react'
import { api } from '../api'
import { formatPercent } from '../format'
import { LAB_NAVIGATION, pushAtlasHash, setLabHashGuard, trackAtlasHistoryEntry } from '../lab-navigation'
import type { LabBacktestSettings, LabDraft, LabRunSummary, LabStrategy, LabStrategySummary } from '../lab-strategy-types'
import { ApiError } from '../request'
import type { Asset, BacktestResult } from '../types'
import { CodeStrategyWorkspace } from './CodeStrategyWorkspace'
import { LabBacktestForm, LabRunSettings } from './LabBacktestForm'
import { LabConfirmDialog } from './LabConfirmDialog'
import { ResultsPanel } from './ResultsPanel'
import { SectorBacktest } from './SectorBacktest'
import { readStrategyFile, STRATEGY_FILE_ACCEPT, STRATEGY_LANGUAGES } from './strategy-languages'
import './lab-workbench.css'

interface Props {
  ownerId: string
  assets: Asset[]
  defaults: LabBacktestSettings
  active: boolean
  onRunSaved: () => void
}

const message = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message : fallback
const draftOf = ({ name, language, source, settings }: LabDraft): LabDraft => ({ name, language, source, settings })
const languageLabel = (language: LabDraft['language']) => STRATEGY_LANGUAGES.find(item => item.id === language)?.label ?? language
const displayTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

function settingsError(settings: LabBacktestSettings) {
  if (settings.start && settings.end && Date.parse(settings.start) >= Date.parse(settings.end)) return '结束时间必须晚于开始时间。'
  if (!Number.isFinite(settings.initial_capital) || settings.initial_capital <= 0) return '初始资金必须大于零。'
  if ([settings.commission_rate, settings.slippage_rate, settings.spread_rate].some(value => !Number.isFinite(value) || value < 0 || value > 0.1)) return '手续费、滑点和价差须在 0% 到 10% 之间。'
  if ([settings.max_position, settings.max_participation_rate].some(value => !Number.isFinite(value) || value <= 0 || value > 1)) return '最大仓位和成交参与率须大于 0%，且不超过 100%。'
  return ''
}

export function StrategyLabWorkspace({ ownerId, assets, defaults, active, onRunSaved }: Props) {
  const [items, setItems] = useState<LabStrategySummary[] | null>(null)
  const [listError, setListError] = useState('')
  const [listAttempt, setListAttempt] = useState(0)
  const [draft, setDraft] = useState<LabDraft | null>(null)
  const [record, setRecord] = useState<LabStrategy | null>(null)
  const [baseline, setBaseline] = useState('')
  const [editorKey, setEditorKey] = useState(0)
  const [opening, setOpening] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [nextAction, setNextAction] = useState<(() => void) | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState<LabRunSummary[] | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [historyAttempt, setHistoryAttempt] = useState(0)
  const [selectedRun, setSelectedRun] = useState<LabRunSummary | null>(null)
  const [loadingRun, setLoadingRun] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const resultHeading = useRef<HTMLHeadingElement>(null)
  const historyHeading = useRef<HTMLHeadingElement>(null)
  const operation = useRef(0)
  const resultRequest = useRef(0)
  const runRequest = useRef<AbortController | null>(null)
  const openRequest = useRef<AbortController | null>(null)
  const saveInFlight = useRef(false)
  const pendingCreate = useRef<{ id: string; snapshot: LabDraft } | null>(null)
  const pendingExit = useRef<(() => void) | null>(null)

  const dirty = !!draft && JSON.stringify(draft) !== baseline
  const strategyId = record?.id

  useEffect(() => {
    const controller = new AbortController()
    api.listLabStrategies(ownerId, controller.signal).then(value => {
      if (!controller.signal.aborted) setItems(value)
    }).catch(reason => {
      if (!controller.signal.aborted) setListError(message(reason, '无法读取策略列表'))
    })
    return () => controller.abort()
  }, [listAttempt, ownerId])

  useEffect(() => {
    if (!strategyId || !historyOpen) return
    const controller = new AbortController()
    api.listLabRuns(ownerId, strategyId, controller.signal).then(value => {
      if (!controller.signal.aborted) setHistory(value)
    }).catch(reason => {
      if (!controller.signal.aborted) setHistoryError(message(reason, '无法读取回测历史'))
    })
    return () => controller.abort()
  }, [ownerId, strategyId, historyOpen, historyAttempt])

  useEffect(() => () => {
    operation.current += 1
    resultRequest.current += 1
    openRequest.current?.abort()
    runRequest.current?.abort()
    pendingExit.current = null
  }, [])

  function resetEditor(next: LabDraft | null, saved: LabStrategy | null = null, initial = next) {
    operation.current += 1
    resultRequest.current += 1
    openRequest.current?.abort()
    runRequest.current?.abort()
    runRequest.current = null
    pendingCreate.current = null
    setEditorKey(key => key + 1)
    setOpening(false); setRunning(false); setLoadingRun(false)
    setDraft(next); setRecord(saved); setBaseline(initial ? JSON.stringify(initial) : '')
    setError(''); setConflict(false); setRunError(''); setResult(null)
    setHistoryOpen(false); setHistory(null); setHistoryError(''); setSelectedRun(null)
  }

  useEffect(() => {
    if (!active || !dirty) return
    const sourceIndex = trackAtlasHistoryEntry()
    let restore: (() => void) | null = null
    const protect = (action: () => void) => {
      if (pendingExit.current) return
      pendingExit.current = action
      setNextAction(() => action)
    }
    const navigate = (event: Event) => {
      event.preventDefault()
      protect((event as CustomEvent<() => void>).detail)
    }
    const stopGuardingHash = setLabHashGuard(event => {
      const target = new URL(event.newURL).hash
      if (new URL(event.oldURL).hash !== '#research' || target === '#research') return false
      const delta = trackAtlasHistoryEntry() - sourceIndex
      if (delta === 0) {
        pushAtlasHash('#research')
        protect(() => { window.location.hash = target })
        return true
      }
      restore = () => protect(() => window.history.go(delta))
      window.addEventListener('hashchange', restore, { once: true })
      window.history.go(-delta)
      return true
    })
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener(LAB_NAVIGATION, navigate)
    window.addEventListener('beforeunload', unload)
    return () => {
      window.removeEventListener(LAB_NAVIGATION, navigate)
      stopGuardingHash()
      if (restore) window.removeEventListener('hashchange', restore)
      window.removeEventListener('beforeunload', unload)
    }
  }, [active, dirty])

  function requestExit(action: () => void) {
    if (!dirty) { action(); return }
    if (pendingExit.current) return
    pendingExit.current = action
    setNextAction(() => action)
  }

  function dismissExit() {
    pendingExit.current = null
    setNextAction(null)
  }

  function finishExit(action: () => void) {
    if (pendingExit.current !== action) return
    dismissExit()
    resetEditor(null)
    action()
  }

  const blank = (): LabDraft => ({ name: '未命名策略', language: 'python', source: '', settings: { ...defaults } })
  const importNew = async (file: File) => {
    const initial = blank()
    const started = ++operation.current
    setError('')
    try {
      const imported = await readStrategyFile(file)
      if (operation.current === started) resetEditor({ ...initial, ...imported }, null, initial)
    } catch (reason) {
      if (operation.current === started) setError(message(reason, '无法导入源码'))
    }
  }

  const open = async (id: string) => {
    openRequest.current?.abort()
    const controller = new AbortController()
    openRequest.current = controller
    const started = ++operation.current
    setOpening(true); setError('')
    try {
      const saved = await api.getLabStrategy(ownerId, id, controller.signal)
      if (started === operation.current) resetEditor(draftOf(saved), saved)
    } catch (reason) {
      if (started === operation.current) setError(message(reason, '无法打开策略'))
    } finally {
      if (started === operation.current) setOpening(false)
    }
  }

  const save = async (): Promise<boolean> => {
    if (!draft || saveInFlight.current) return false
    const invalid = !draft.name.trim() ? '请输入策略名称。' : settingsError(draft.settings)
    if (invalid) { setError(invalid); return false }
    const snapshot = draft
    const create = record ? null : pendingCreate.current ?? { id: crypto.randomUUID().replaceAll('-', ''), snapshot }
    pendingCreate.current = create
    const started = operation.current
    saveInFlight.current = true
    setSaving(true); setError(''); setConflict(false)
    try {
      const saved = create ? await api.createLabStrategy(ownerId, create.id, create.snapshot)
        : await api.updateLabStrategy(ownerId, record!.id, record!.revision, snapshot)
      if (started !== operation.current) return false
      pendingCreate.current = null
      const submitted = create?.snapshot ?? snapshot
      setRecord(saved)
      setBaseline(JSON.stringify(draftOf(saved)))
      setDraft(current => current === submitted ? draftOf(saved) : current)
      setItems(current => [saved, ...(current ?? []).filter(item => item.id !== saved.id)])
      if (submitted !== snapshot) {
        setError('已恢复上次保存。请再保存一次，提交后续修改。')
        return false
      }
      return true
    } catch (reason) {
      if (started === operation.current) {
        if (reason instanceof ApiError && reason.kind === 'http' && (reason.status ?? 500) < 500) pendingCreate.current = null
        setConflict(reason instanceof ApiError && reason.status === 409)
        setError(message(reason, '策略保存失败'))
      }
      return false
    } finally {
      saveInFlight.current = false
      setSaving(false)
    }
  }

  const run = async () => {
    if (!record || !draft || draft.language !== 'python' || !draft.source.trim() || runRequest.current) return
    const invalid = settingsError(draft.settings)
    if (invalid || !draft.settings.symbol || draft.source.length > 16_384) {
      setRunError(invalid || (!draft.settings.symbol ? '请先选择回测标的。' : '受限 Python 回测最多支持 16,384 字符。'))
      return
    }
    const controller = new AbortController()
    runRequest.current = controller
    resultRequest.current += 1
    setLoadingRun(false); setRunning(true); setRunError('')
    try {
      const next = await api.runBacktest({
        ...draft.settings, strategy_id: 'python_bounded', python_source: draft.source,
        params: {}, persist: true, lab_strategy_id: record.id,
      }, controller.signal, ownerId)
      if (controller.signal.aborted) return
      setResult(next); setSelectedRun(null)
      setHistoryAttempt(value => value + 1)
      onRunSaved()
    } catch (reason) {
      if (!controller.signal.aborted) setRunError(message(reason, '回测失败'))
    } finally {
      if (runRequest.current === controller) {
        runRequest.current = null
        setRunning(false)
      }
    }
  }

  const openRun = async (row: LabRunSummary) => {
    const sequence = ++resultRequest.current
    setLoadingRun(true); setRunError('')
    try {
      const next = await api.getRun<BacktestResult>(row.id)
      if (sequence === resultRequest.current) { setResult(next); setSelectedRun(row) }
    } catch (reason) {
      if (sequence === resultRequest.current) setRunError(message(reason, '无法打开回测结果'))
    } finally {
      if (sequence === resultRequest.current) setLoadingRun(false)
    }
  }

  return <main className="lab-workbench" aria-label="策略实验室">
    {nextAction ? <LabConfirmDialog
      title="保存未完成的修改？"
      description={error || '源码或回测设置已修改。保存后可在当前账号继续编辑。'}
      confirmLabel="保存并离开" confirmDisabled={saving}
      onCancel={dismissExit}
      onConfirm={() => void save().then(ok => { if (ok) finishExit(nextAction) })}
      extraAction={<button disabled={saving} onClick={() => finishExit(nextAction)}>放弃修改</button>}
    /> : null}
    {!draft ? <section className="lab-library" aria-labelledby="lab-library-heading">
      <header className="lab-library-header">
        <div><h1 id="lab-library-heading">我的策略</h1><p><LockKeyhole size={15} />源码和回测设置保存在当前账号</p></div>
        <div className="lab-command-actions">
          <input ref={fileInput} type="file" accept={STRATEGY_FILE_ACCEPT} hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void importNew(file) }} />
          <button disabled={opening || items === null} onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
          <button className="lab-primary" disabled={opening || items === null} onClick={() => resetEditor(blank())}><Plus size={16} />新建策略</button>
        </div>
      </header>
      <SectorBacktest key={ownerId} ownerId={ownerId} />
      {error ? <p className="lab-error" role="alert">{error}</p> : null}
      {listError ? <div className="lab-empty" role="alert"><p>{listError}</p><button onClick={() => { setListError(''); setListAttempt(value => value + 1) }}>重新加载</button></div>
        : items === null || opening ? <p className="lab-empty" role="status">{opening ? '正在打开策略…' : '正在加载策略…'}</p>
        : items.length ? <div className="lab-table-scroll"><table className="lab-table">
          <thead><tr><th scope="col">策略名称</th><th scope="col">语言</th><th scope="col">最近修改</th><th scope="col">操作</th></tr></thead>
          <tbody>{items.map(item => <tr key={item.id}>
            <th scope="row"><Code2 size={16} /><span>{item.name}</span></th>
            <td>{languageLabel(item.language)}</td><td><time dateTime={item.updated_at}>{displayTime.format(new Date(item.updated_at))}</time></td>
            <td><button aria-label={`打开 ${item.name}`} onClick={() => void open(item.id)}>打开<ArrowRight size={15} /></button></td>
          </tr>)}</tbody>
        </table></div> : <div className="lab-empty"><Code2 size={27} /><h2>还没有代码策略</h2><p>新建空白策略，或导入已有的源码文件。</p></div>}
    </section> : <>
      <header className="lab-editor-navigation">
        <button disabled={saving} onClick={() => requestExit(() => resetEditor(null))}><ArrowLeft size={16} />我的策略</button>
        <h1>编辑策略</h1>
      </header>
      {error ? <div className="lab-error" role="alert"><span>{error}</span>
        {conflict && record ? <button onClick={() => requestExit(() => void open(record.id))}>重新加载已保存版本</button> : null}
      </div> : null}
      {opening ? <p role="status" className="lab-empty">正在重新加载策略…</p> : null}
      <CodeStrategyWorkspace key={editorKey} draft={draft} ownerId={ownerId}
        onEdit={patch => setDraft(current => current && { ...current, ...patch })}
        onSave={() => void save()} onRun={() => void run()}
        onHistory={() => {
          if (!historyOpen) requestAnimationFrame(() => historyHeading.current?.focus())
          setHistoryOpen(!historyOpen)
          setHistoryError('')
        }}
        runFeedback={<div className="lab-run-feedback">
          <span role="status">{running ? '正在运行回测…' : runError ? '回测未完成' : result ? '回测结果已就绪' : ''}</span>
          {!running && (runError || result) ? <button onClick={() => resultHeading.current?.focus()}>{runError ? '查看原因' : '查看回测结果'}</button> : null}
        </div>}
        dirty={dirty} saved={!!record} saving={saving} running={running}>
        <LabBacktestForm value={draft.settings} assets={assets}
          onChange={patch => setDraft(current => current && { ...current, settings: { ...current.settings, ...patch } })} />
        {historyOpen ? <section className="lab-history" aria-labelledby="lab-history-heading">
          <header><h2 id="lab-history-heading" ref={historyHeading} tabIndex={-1}>历史回测</h2><button onClick={() => setHistoryOpen(false)}>收起</button></header>
          {historyError ? <div role="alert" className="lab-error">{historyError}<button onClick={() => { setHistoryError(''); setHistoryAttempt(value => value + 1) }}>重试</button></div>
            : history === null ? <p role="status">正在读取历史回测…</p>
            : history.length ? <div className="lab-table-scroll"><table className="lab-table lab-history-table">
              <thead><tr><th scope="col">运行时间</th><th scope="col">收益</th><th scope="col">源码摘要</th><th scope="col">操作</th></tr></thead>
              <tbody>{history.map(row => <tr key={row.id} className={result?.run_id === row.id ? 'lab-active-run' : undefined}>
                <td><time dateTime={row.created_at}>{displayTime.format(new Date(row.created_at))}</time></td>
                <td>{formatPercent(row.total_return)}</td><td><code title={row.source_sha256}>{row.source_sha256.slice(0, 10)}</code></td>
                <td><button disabled={running} onClick={() => void openRun(row)} aria-label={`查看 ${displayTime.format(new Date(row.created_at))} 的回测`}>查看</button></td>
              </tr>)}</tbody>
            </table></div> : <p>成功完成的回测会出现在这里。</p>}
        </section> : null}
        <section className="lab-results">
          <h2 ref={resultHeading} tabIndex={-1}>回测结果</h2>
          {runError ? <p className="lab-error" role="alert">{runError}</p> : null}
          {selectedRun ? <details className="lab-original-settings">
            <summary>本次运行参数和源码摘要</summary>
            <code>{selectedRun.source_sha256}</code><LabRunSettings settings={selectedRun.settings} />
          </details> : null}
          <ResultsPanel result={result} loading={running || loadingRun} panelMode="normal" onPanelMode={() => undefined} controls={false} />
        </section>
      </CodeStrategyWorkspace>
    </>}
  </main>
}
