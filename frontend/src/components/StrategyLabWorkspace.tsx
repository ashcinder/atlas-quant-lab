import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Code2, LockKeyhole, Plus, Upload } from 'lucide-react'
import { api } from '../api'
import { formatPercent } from '../format'
import { LAB_NAVIGATION, guardLabHashChange, pushAtlasHash, setLabHashGuard, trackAtlasHistoryEntry } from '../lab-navigation'
import { defaultMultiSettings, labMultiEngineLabels, labOwnerHeaders, multiJobActive, multiJobEngine, multiJobStatus } from '../lab-strategy-types'
import type { LabBacktestSettings, LabDraft, LabMultiCoverage, LabMultiDraft, LabMultiEngine, LabMultiJob, LabRunSummary, LabSingleDraft, LabStrategy, LabStrategyKind, LabStrategySummary } from '../lab-strategy-types'
import { encodeLabPackage, labMultiApi, type LabMultiCapabilities, type LabMultiExample } from '../lab-multi-api'
import { sha256 } from '../compute/market'
import { ApiError, request, RUNTIME_CHANGED_EVENT } from '../request'
import type { Asset, BacktestResult, StrategyRelease } from '../types'
import { CodeStrategyWorkspace } from './CodeStrategyWorkspace'
import { LabBacktestForm, LabRunSettings } from './LabBacktestForm'
import { LabConfirmDialog } from './LabConfirmDialog'
import { LabMultiBacktestForm, LabMultiBacktestResult } from './LabMultiBacktest'
import { CloudProofControl } from './CloudProofControl'
import { BkcSubscription } from './BkcControls'
import { ResultsPanel } from './ResultsPanel'
import { SectorBacktest } from './SectorBacktest'
import { MAX_BOUNDED_SOURCE, readStrategyFile, sourceBytes, STRATEGY_FILE_ACCEPT, STRATEGY_LANGUAGES } from './strategy-languages'
import './lab-workbench.css'

interface Props {
  ownerId: string
  assets: Asset[]
  defaults: LabBacktestSettings
  active: boolean
  onRunSaved: () => void
}

const message = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message : fallback
const draftOf = (draft: LabDraft): LabDraft => draft.kind === 'multi_python'
  ? { kind: draft.kind, name: draft.name, language: draft.language, source: draft.source, settings: draft.settings, ...(draft.package_b64 ? { package_b64: draft.package_b64 } : {}) }
  : { name: draft.name, language: draft.language, source: draft.source, settings: draft.settings }
const labRoute = () => window.location.hash.split('?')[0]
const strategyTypes: Record<LabStrategyKind, string> = { single_bounded: '单标的受限 Python', multi_python: 'A 股多标的 Python' }
const multiStarter = `from atlas_strategy_sdk import TargetPosition

class Strategy:
    def generate_targets(self, context):
        ready = [
            symbol for symbol in context.symbols
            if len(context.history(symbol, 20)) == 20
            and symbol not in context.suspended
        ]
        if not ready:
            return []
        strongest = max(
            ready,
            key=lambda symbol: context.history(symbol, 20)[-1].close / context.history(symbol, 20)[0].close,
        )
        return [
            TargetPosition(symbol, 0.5 if symbol == strongest else 0.0, 1.0, "relative_momentum")
            for symbol in ready
        ]
`

const rqalphaStarter = `from rqalpha.api import order_target_percent, update_universe


def init(context):
    context.placed = False
    update_universe(context.symbols)


def handle_bar(context, bar_dict):
    if context.placed:
        return
    weight = float(context.parameters.get("weight", 0.8 / len(context.symbols)))
    for symbol in context.symbols:
        order_target_percent(symbol, weight)
    context.placed = True
`

type SingleRunSnapshot = { settings: LabBacktestSettings; source_sha256?: string; source?: string; historical?: boolean }

function snapshotSettings(settings: LabBacktestSettings) {
  return JSON.stringify(Object.entries(settings).sort(([left], [right]) => left.localeCompare(right)))
}
const languageLabel = (language: LabDraft['language']) => STRATEGY_LANGUAGES.find(item => item.id === language)?.label ?? language
const displayTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

function settingsError(settings: LabDraft['settings']) {
  if (settings.start && settings.end && Date.parse(settings.start) >= Date.parse(settings.end)) return '结束时间必须晚于开始时间。'
  if (!Number.isFinite(settings.initial_capital) || settings.initial_capital <= 0) return '初始资金必须大于零。'
  if ([settings.commission_rate, settings.slippage_rate, ...('spread_rate' in settings ? [settings.spread_rate] : [])].some(value => !Number.isFinite(value) || value < 0 || value > 0.1)) return '手续费、滑点和价差须在 0% 到 10% 之间。'
  if ([settings.max_position, settings.max_participation_rate].some(value => !Number.isFinite(value) || value <= 0 || value > 1)) return '最大仓位和成交参与率须大于 0%，且不超过 100%。'
  if ('symbols' in settings && settings.engine_id === 'rqalpha') {
    if (settings.interval !== '1d' || settings.universe) return 'RQAlpha 首期仅支持静态股票池日线回测。'
    if (settings.symbols.some(symbol => symbol.endsWith('.BJ'))) return 'RQAlpha 首期仅支持沪深 A 股，请移除北交所标的。'
  }
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
  const [selectedRun, setSelectedRun] = useState<SingleRunSnapshot | null>(null)
  const [entry, setEntry] = useState<{ mode: 'new' | 'import'; file?: File } | null>(null)
  const [examples, setExamples] = useState<LabMultiExample[] | null>(null)
  const [exampleError, setExampleError] = useState('')
  const [job, setJob] = useState<LabMultiJob | null>(null)
  const [previousSuccess, setPreviousSuccess] = useState<LabMultiJob | null>(null)
  const [jobs, setJobs] = useState<LabMultiJob[] | null>(null)
  const [jobsError, setJobsError] = useState('')
  const [jobsAttempt, setJobsAttempt] = useState(0)
  const [pollError, setPollError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [capabilityCheck, setCapabilityCheck] = useState<{ engine: LabMultiEngine; data: LabMultiCapabilities | null; error: string } | null>(null)
  const [capabilityAttempt, setCapabilityAttempt] = useState(0)
  const [coverageCheck, setCoverageCheck] = useState<{ settings: LabMultiDraft['settings']; data: LabMultiCoverage | null; error: string } | null>(null)
  const [coverageBusy, setCoverageBusy] = useState(false)
  const [releases, setReleases] = useState<StrategyRelease[]>([])
  const [createdRelease, setCreatedRelease] = useState<StrategyRelease | null>(null)
  const [releaseBusy, setReleaseBusy] = useState(false)
  const [releaseError, setReleaseError] = useState('')
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
  const multiSubmitId = useRef<{ revision: number; id: string } | null>(null)
  const coverageRequest = useRef<AbortController | null>(null)
  const jobMutation = useRef<AbortController | null>(null)
  const releaseMutation = useRef(false)
  const navigationHandled = useRef('')

  const dirty = !!draft && JSON.stringify(draft) !== baseline
  const strategyId = record?.id
  const multi = draft?.kind === 'multi_python' ? draft : null
  const multiId = multi ? strategyId : undefined
  const isMulti = !!multi
  const multiEngine = multi?.settings.engine_id ?? 'atlas_portfolio'
  const rqalpha = isMulti && multiEngine === 'rqalpha'
  const capability = capabilityCheck?.engine === multiEngine ? capabilityCheck.data : null
  const capabilityError = capabilityCheck?.engine === multiEngine ? capabilityCheck.error : ''
  const coverage = coverageCheck?.settings === multi?.settings ? coverageCheck : null
  const inFlightJob = multiJobActive(job) ? job : jobs?.find(multiJobActive) ?? null
  const activeJobId = inFlightJob?.id
  const runningMulti = multiJobActive(inFlightJob) || running
  const runDisabledReason = !multi ? undefined
    : dirty ? '请先保存当前修改，再运行多股回测。'
    : capability?.available === false ? capability.reason || '多股执行环境未就绪。'
    : !capability?.available ? capabilityError || '正在读取多股执行环境。'
    : settingsError(multi.settings) ? settingsError(multi.settings)
    : !multi.settings.universe && multi.settings.symbols.length < 2 ? '请加入至少两只 A 股。'
    : coverage?.data?.available === false ? coverage.data.reason || '当前配置的行情覆盖不完整。'
    : undefined
  const singleResultStale = !!(draft && draft.kind !== 'multi_python' && selectedRun &&
    ((selectedRun.source !== undefined && selectedRun.source !== draft.source) ||
      snapshotSettings(selectedRun.settings) !== snapshotSettings(draft.settings)))
  const multiResultStale = !!(job && (job.revision !== record?.revision || multiJobEngine(job) !== multiEngine || dirty))

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
    if (!strategyId || isMulti || !historyOpen) return
    const controller = new AbortController()
    api.listLabRuns(ownerId, strategyId, controller.signal).then(value => {
      if (!controller.signal.aborted) setHistory(value)
    }).catch(reason => {
      if (!controller.signal.aborted) setHistoryError(message(reason, '无法读取回测历史'))
    })
    return () => controller.abort()
  }, [ownerId, strategyId, isMulti, historyOpen, historyAttempt])


  useEffect(() => {
    if (!multiId) return
    const sequence = resultRequest.current
    const controller = new AbortController()
    labMultiApi.jobs(ownerId, multiId, controller.signal).then(async rows => {
      if (controller.signal.aborted) return
      setJobs(rows)
      const latest = rows.find(multiJobActive) ?? rows[0]
      const recentSuccess = rows.find(row => row.status === 'succeeded')
      const [details, success] = await Promise.all([
        latest ? labMultiApi.job(ownerId, latest.id, controller.signal) : null,
        recentSuccess && recentSuccess.id !== latest?.id ? labMultiApi.job(ownerId, recentSuccess.id, controller.signal) : null,
      ])
      if (controller.signal.aborted) return
      if (details && sequence === resultRequest.current) setJob(current => current ?? details)
      if (success) setPreviousSuccess(current => current ?? success)
    }).catch(reason => { if (!controller.signal.aborted) setJobsError(message(reason, '无法读取多股回测历史')) })
    return () => controller.abort()
  }, [ownerId, multiId, jobsAttempt])

  useEffect(() => {
    if (!activeJobId || !active) return
    const controller = new AbortController()
    let timer: number | undefined
    const poll = async () => {
      try {
        const next = await labMultiApi.job(ownerId, activeJobId, controller.signal)
        if (controller.signal.aborted) return
        setPollError('')
        setJob(current => current?.id === next.id && multiJobActive(current) ? next : current)
        if (!multiJobActive(next)) {
          if (next.status === 'succeeded') setPreviousSuccess(next)
          setJobs(current => current ? [next, ...current.filter(row => row.id !== next.id)] : [next])
          return
        }
      } catch (reason) {
        if (controller.signal.aborted) return
        setPollError(message(reason, '无法读取任务状态，稍后重试'))
      }
      timer = window.setTimeout(poll, 1_500)
    }
    timer = window.setTimeout(poll, 750)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [active, activeJobId, ownerId])

  useEffect(() => {
    if (!isMulti) return
    const controller = new AbortController()
    labMultiApi.capabilities(ownerId, controller.signal, multiEngine).then(value => {
      if (!controller.signal.aborted) {
        setCapabilityCheck(value.engine_id && value.engine_id !== multiEngine
          ? { engine: multiEngine, data: null, error: '执行环境返回的引擎不匹配，请重试。' }
          : { engine: multiEngine, data: value, error: '' })
      }
    }).catch(reason => {
      if (!controller.signal.aborted) setCapabilityCheck({ engine: multiEngine, data: null, error: message(reason, '无法检查隔离执行环境') })
    })
    return () => controller.abort()
  }, [isMulti, multiEngine, ownerId, capabilityAttempt, editorKey])

  useEffect(() => {
    if (!strategyId) return
    const controller = new AbortController()
    const load = () => {
      request<StrategyRelease[]>('/strategy-releases', { headers: labOwnerHeaders(ownerId), signal: controller.signal }).then(rows => {
        if (!controller.signal.aborted && Array.isArray(rows)) setReleases(rows.filter(row => row.owned && row.lab_strategy_id === strategyId))
      }).catch(() => undefined)
    }
    load()
    window.addEventListener(RUNTIME_CHANGED_EVENT, load)
    return () => { controller.abort(); window.removeEventListener(RUNTIME_CHANGED_EVENT, load) }
  }, [ownerId, strategyId])

  useEffect(() => () => {
    operation.current += 1
    resultRequest.current += 1
    openRequest.current?.abort()
    runRequest.current?.abort()
    coverageRequest.current?.abort()
    jobMutation.current?.abort()
    pendingExit.current = null
  }, [])

  const resetEditor = useCallback((next: LabDraft | null, saved: LabStrategy | null = null, initial = next) => {
    operation.current += 1
    resultRequest.current += 1
    openRequest.current?.abort()
    runRequest.current?.abort()
    runRequest.current = null
    coverageRequest.current?.abort()
    jobMutation.current?.abort()
    pendingCreate.current = null
    multiSubmitId.current = null
    setEditorKey(key => key + 1)
    setOpening(false); setRunning(false); setLoadingRun(false)
    setDraft(next); setRecord(saved); setBaseline(initial ? JSON.stringify(initial) : '')
    setError(''); setConflict(false); setRunError(''); setResult(null)
    setHistoryOpen(false); setHistory(null); setHistoryError(''); setSelectedRun(null)
    setEntry(null); setJob(null); setPreviousSuccess(null); setJobs(null); setJobsError(''); setPollError(''); setCancelling(false)
    setCoverageCheck(null); setCoverageBusy(false); setReleases([]); setCreatedRelease(null); setReleaseBusy(false); setReleaseError('')
    setCapabilityCheck(null)
  }, [])

  useEffect(() => {
    if (!active || !dirty) return
    const sourceIndex = trackAtlasHistoryEntry()
    const sourceHash = window.location.hash
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
      if (restore || new URL(event.oldURL).hash.split('?')[0] !== '#research' || target === new URL(event.oldURL).hash) return false
      const delta = trackAtlasHistoryEntry() - sourceIndex
      if (delta === 0) {
        pushAtlasHash(sourceHash)
        protect(() => { window.location.hash = target })
        return true
      }
      restore = () => { restore = null; protect(() => window.history.go(delta)) }
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

  const blank = (): LabSingleDraft => ({ name: '未命名策略', language: 'python', source: '', settings: { ...defaults } })
  const blankMulti = (source = multiStarter, engine: LabMultiEngine = 'atlas_portfolio'): LabMultiDraft => ({
    kind: 'multi_python', name: '未命名策略', language: 'python', source,
    settings: { ...defaultMultiSettings, symbols: [], ...(engine === 'rqalpha' ? { engine_id: engine, interval: '1d' } : {}) },
  })
  const importNew = async (file: File, kind: LabStrategyKind, engine: LabMultiEngine = 'atlas_portfolio') => {
    const initial = kind === 'multi_python' ? blankMulti('', engine) : blank()
    const started = ++operation.current
    setError(''); setOpening(true)
    try {
      if (/\.(?:zip|qstrategy)$/i.test(file.name)) {
        const package_b64 = await encodeLabPackage(file)
        const imported = await labMultiApi.inspect(ownerId, package_b64)
        const defaults = blankMulti('')
        if (operation.current === started) resetEditor({
          ...defaults, name: imported.name, source: imported.source, package_b64,
          settings: { ...defaults.settings, ...imported.settings },
        }, null, defaults)
      } else {
        const imported = await readStrategyFile(file)
        if (initial.kind === 'multi_python' && imported.language !== 'python') throw new Error('多标的策略使用 Python 源码。')
        const next: LabDraft = initial.kind === 'multi_python'
          ? { ...initial, ...imported, language: 'python' }
          : { ...initial, ...imported }
        if (operation.current === started) resetEditor(next, null, initial)
      }
    } catch (reason) {
      if (operation.current === started) setError(message(reason, '无法导入源码'))
    } finally {
      if (operation.current === started) setOpening(false)
    }
  }
  const startImport = (file: File) => {
    if (file.name.toLowerCase().endsWith('.py')) setEntry({ mode: 'import', file })
    else void importNew(file, /\.(?:zip|qstrategy)$/i.test(file.name) ? 'multi_python' : 'single_bounded')
  }
  const loadExamples = async () => {
    const started = operation.current
    try {
      const rows = await labMultiApi.examples(ownerId)
      if (started === operation.current) { setExamples(rows); setExampleError('') }
    } catch (reason) {
      if (started === operation.current) setExampleError(message(reason, '无法读取可编辑示例'))
    }
  }
  const openExample = async (id: string) => {
    const started = ++operation.current
    setOpening(true); setError('')
    try {
      const example = await labMultiApi.example(ownerId, id)
      if (started === operation.current) resetEditor(draftOf(example), null, null)
    } catch (reason) {
      if (started === operation.current) setError(message(reason, '无法打开策略示例'))
    } finally {
      if (started === operation.current) setOpening(false)
    }
  }

  const open = useCallback(async (id: string, fromRelease = false) => {
    openRequest.current?.abort()
    const controller = new AbortController()
    openRequest.current = controller
    const started = ++operation.current
    setOpening(true); setError('')
    try {
      if (fromRelease) {
        const copied = await labMultiApi.fromRelease(ownerId, id, controller.signal)
        if (started === operation.current) resetEditor(draftOf(copied), null, null)
      } else {
        const saved = await api.getLabStrategy(ownerId, id, controller.signal)
        if (started === operation.current) resetEditor(draftOf(saved), saved)
      }
    } catch (reason) {
      if (started === operation.current) setError(message(reason, '无法打开策略'))
    } finally {
      if (started === operation.current) setOpening(false)
    }
  }, [ownerId, resetEditor])

  useEffect(() => {
    if (!active) return
    const read = () => {
      const hash = window.location.hash
      if (labRoute() !== '#research' || !hash.includes('?')) { navigationHandled.current = ''; return }
      if (navigationHandled.current === hash) return
      const query = new URLSearchParams(hash.split('?')[1])
      const strategy = query.get('strategy')
      const copy = query.get('copy')
      if (!strategy && !copy) return
      navigationHandled.current = hash
      void open(strategy ?? copy!, !strategy)
    }
    const timer = window.setTimeout(read, 0)
    const onHash = (event: HashChangeEvent) => { if (!guardLabHashChange(event)) read() }
    window.addEventListener('hashchange', onHash)
    return () => { window.clearTimeout(timer); window.removeEventListener('hashchange', onHash) }
  }, [active, open])

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
    if (!record || !draft || draft.kind === 'multi_python' || draft.language !== 'python' || !draft.source.trim() || runRequest.current) return
    const invalid = settingsError(draft.settings)
    if (invalid || !draft.settings.symbol || sourceBytes(draft.source) > MAX_BOUNDED_SOURCE) {
      setRunError(invalid || (!draft.settings.symbol ? '请先选择回测标的。' : '受限 Python 回测最多支持 16 KiB 源码。'))
      return
    }
    const controller = new AbortController()
    runRequest.current = controller
    resultRequest.current += 1
    setLoadingRun(false); setRunning(true); setRunError('')
    const sourceHash = sha256(new TextEncoder().encode(draft.source).buffer).catch(() => undefined)
    try {
      const next = await api.runBacktest({
        ...draft.settings, strategy_id: 'python_bounded', python_source: draft.source,
        params: {}, persist: true, lab_strategy_id: record.id,
      }, controller.signal, ownerId)
      const source_sha256 = await sourceHash
      if (controller.signal.aborted) return
      setResult(next); setSelectedRun({ settings: draft.settings, source: draft.source, source_sha256 })
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

  const checkCoverage = async () => {
    if (!multi || coverageBusy) return
    const controller = new AbortController()
    coverageRequest.current?.abort()
    coverageRequest.current = controller
    setCoverageBusy(true); setCoverageCheck(null)
    try {
      const data = await labMultiApi.preflight(ownerId, multi.settings, controller.signal)
      if (!controller.signal.aborted) setCoverageCheck({ settings: multi.settings, data, error: '' })
    } catch (reason) {
      if (!controller.signal.aborted) setCoverageCheck({ settings: multi.settings, data: null, error: message(reason, '无法读取行情覆盖') })
    } finally {
      if (!controller.signal.aborted) setCoverageBusy(false)
      if (coverageRequest.current === controller) coverageRequest.current = null
    }
  }

  const runMulti = async () => {
    if (!multi || !record || runDisabledReason || runningMulti || runRequest.current) return
    const invalid = settingsError(multi.settings)
    if (invalid) { setRunError(invalid); return }
    const controller = new AbortController()
    runRequest.current = controller
    resultRequest.current += 1
    const submission = multiSubmitId.current?.revision === record.revision
      ? multiSubmitId.current
      : { id: crypto.randomUUID(), revision: record.revision }
    multiSubmitId.current = submission
    setRunError(''); setPollError(''); setRunning(true); setLoadingRun(false)
    try {
      const data = await labMultiApi.preflight(ownerId, multi.settings, controller.signal)
      if (controller.signal.aborted) return
      setCoverageCheck({ settings: multi.settings, data, error: '' })
      if (!data.available) { setRunError(data.reason || '当前配置的行情覆盖不完整。'); return }
      const next = await labMultiApi.start(ownerId, record.id, record.revision, submission.id, controller.signal)
      if (controller.signal.aborted) return
      multiSubmitId.current = null
      if (job?.status === 'succeeded') setPreviousSuccess(job)
      if (next.status === 'succeeded') setPreviousSuccess(next)
      setJob(next)
      setJobs(current => [next, ...(current ?? []).filter(row => row.id !== next.id)])
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason instanceof ApiError && reason.kind === 'http' && (reason.status ?? 500) < 500) multiSubmitId.current = null
        setRunError(message(reason, '无法创建回测任务，请重试'))
      }
    } finally {
      if (runRequest.current === controller) { runRequest.current = null; setRunning(false) }
    }
  }

  const cancelJob = async () => {
    if (!inFlightJob || jobMutation.current) return
    const controller = new AbortController()
    jobMutation.current = controller
    setCancelling(true); setPollError('')
    try {
      const next = await labMultiApi.cancel(ownerId, inFlightJob.id, controller.signal)
      if (!controller.signal.aborted) {
        setJob(current => current?.id === next.id ? next : current)
        setJobs(current => current?.map(row => row.id === next.id ? next : row) ?? [next])
      }
    } catch (reason) {
      if (!controller.signal.aborted) setPollError(message(reason, '无法取消回测任务'))
    } finally {
      if (jobMutation.current === controller) jobMutation.current = null
      if (!controller.signal.aborted) setCancelling(false)
    }
  }

  const openJob = async (row: LabMultiJob) => {
    const sequence = ++resultRequest.current
    setLoadingRun(true); setRunError('')
    try {
      const next = await labMultiApi.job(ownerId, row.id)
      if (sequence === resultRequest.current) setJob(next)
    } catch (reason) {
      if (sequence === resultRequest.current) setRunError(message(reason, '无法打开回测快照'))
    } finally {
      if (sequence === resultRequest.current) setLoadingRun(false)
    }
  }

  const createRelease = async () => {
    if (rqalpha || capability?.can_release === false && isMulti) return
    if (!record || !draft || draft.language !== 'python' || dirty || releaseMutation.current) return
    if (draft.kind === 'multi_python' && (!job || job.status !== 'succeeded' || multiResultStale)) return
    const started = operation.current
    releaseMutation.current = true; setReleaseBusy(true); setReleaseError('')
    try {
      const next = draft.kind === 'multi_python' && job
        ? await labMultiApi.release(ownerId, record.id, record.revision, job.id)
        : await request<StrategyRelease>('/strategy-releases', {
          method: 'POST', headers: labOwnerHeaders(ownerId),
          body: JSON.stringify({
            name: draft.name.trim(), source_kind: 'python', strategy_id: 'python_bounded', python_source: draft.source,
            markets: ['CRYPTO', 'US', 'CN'], published: false,
            lab_strategy_id: record.id, lab_revision: record.revision,
            ...(result && selectedRun?.source === draft.source && !singleResultStale ? { lab_run_id: result.run_id } : {}),
          }),
        })
      if (operation.current !== started) return
      setCreatedRelease(next)
      setReleases(current => [next, ...current.filter(row => row.id !== next.id)])
      window.dispatchEvent(new Event(RUNTIME_CHANGED_EVENT))
    } catch (reason) {
      if (operation.current === started) setReleaseError(message(reason, '无法创建运行版本'))
    } finally {
      releaseMutation.current = false
      if (operation.current === started) setReleaseBusy(false)
    }
  }

  const publicize = async (release: StrategyRelease) => {
    if (releaseMutation.current) return
    const started = operation.current
    releaseMutation.current = true; setReleaseBusy(true); setReleaseError('')
    try {
      await request(`/strategy-releases/${encodeURIComponent(release.id)}/publish`, { method: 'POST', headers: labOwnerHeaders(ownerId) })
      if (operation.current !== started) return
      const published = { ...release, published: true }
      setCreatedRelease(current => current?.id === release.id ? published : current)
      setReleases(current => current.map(row => row.id === release.id ? published : row))
    } catch (reason) {
      if (operation.current === started) setReleaseError(message(reason, '无法公开运行版本'))
    } finally {
      releaseMutation.current = false
      if (operation.current === started) setReleaseBusy(false)
    }
  }

  const openRun = async (row: LabRunSummary) => {
    const sequence = ++resultRequest.current
    setLoadingRun(true); setRunError('')
    try {
      const next = await api.getRun<BacktestResult>(row.id)
      if (sequence === resultRequest.current) { setResult(next); setSelectedRun({ ...row, historical: true }) }
    } catch (reason) {
      if (sequence === resultRequest.current) setRunError(message(reason, '无法打开回测结果'))
    } finally {
      if (sequence === resultRequest.current) setLoadingRun(false)
    }
  }

  const singleResultNotice = singleResultStale ? '结果对应旧版本，当前修改尚未回测。'
    : runError && result ? '下方为上次成功的回测结果。'
    : selectedRun?.historical ? '正在查看历史回测快照。' : ''
  const currentRelease = createdRelease?.lab_revision === record?.revision ? createdRelease : null

  return <main className="lab-workbench" aria-label="策略实验室">
    {nextAction ? <LabConfirmDialog
      title="保存未完成的修改？"
      description={error || '源码或回测设置已修改。保存后可在当前账号继续编辑。'}
      confirmLabel="保存并离开" confirmDisabled={saving}
      onCancel={dismissExit}
      onConfirm={() => void save().then(ok => { if (ok) finishExit(nextAction) })}
      extraAction={<button disabled={saving} onClick={() => finishExit(nextAction)}>放弃修改</button>}
    /> : null}
    <section className="lab-library" aria-labelledby="lab-library-heading" hidden={!!draft}>

      <header className="lab-library-header">
        <div><h1 id="lab-library-heading">我的策略</h1><p><LockKeyhole size={15} />源码和回测设置保存在当前账号</p></div>
        <div className="lab-command-actions">
          <input ref={fileInput} type="file" accept={`${STRATEGY_FILE_ACCEPT},.zip,.qstrategy`} hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) startImport(file) }} />
          <button disabled={opening || items === null} onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
          <button className="lab-primary" disabled={opening || items === null} aria-expanded={entry?.mode === 'new'} onClick={() => {
            setEntry(entry?.mode === 'new' ? null : { mode: 'new' })
            if (!examples) void loadExamples()
          }}><Plus size={16} />新建策略</button>
        </div>
      </header>
      {entry && <section className="lab-entry-choice" aria-label={entry.mode === 'new' ? '新建策略类型' : '导入策略类型'}>
        <p>{entry.mode === 'new' ? '选择策略类型' : `导入 ${entry.file?.name} · 选择执行方式`}</p>
        <div className="lab-command-actions">
          {(['single_bounded', 'multi_python'] as const).map(kind => <button type="button" key={kind} disabled={opening} onClick={() => {
            if (entry.file) void importNew(entry.file, kind)
            else resetEditor(kind === 'multi_python' ? blankMulti() : blank())
          }}>{strategyTypes[kind]}</button>)}
          <button type="button" disabled={opening} onClick={() => {
            if (entry.file) void importNew(entry.file, 'multi_python', 'rqalpha')
            else resetEditor(blankMulti(rqalphaStarter, 'rqalpha'))
          }}>RQAlpha 原生日线 Python</button>
          {entry.mode === 'import' && <button type="button" onClick={() => setEntry(null)}>取消导入</button>}
        </div>
        {entry.mode === 'new' && !!examples?.length && <div className="lab-command-actions lab-coverage">
          <span>从行业示例创建</span>
          {examples.map(example => <button type="button" key={example.id} disabled={opening} onClick={() => void openExample(example.id)}>{example.name}</button>)}
        </div>}
        {entry.mode === 'new' && exampleError && <div className="lab-command-actions lab-coverage">
          <p role="alert">{exampleError}</p><button type="button" onClick={() => void loadExamples()}>重试示例</button>
        </div>}
      </section>}
      <SectorBacktest key={ownerId} ownerId={ownerId} />
      {!draft && error ? <p className="lab-error" role="alert">{error}</p> : null}
      {listError ? <div className="lab-empty" role="alert"><p>{listError}</p><button onClick={() => { setListError(''); setListAttempt(value => value + 1) }}>重新加载</button></div>
        : items === null || opening ? <p className="lab-empty" role="status">{opening ? '正在打开策略…' : '正在加载策略…'}</p>
        : items.length ? <div className="lab-table-scroll"><table className="lab-table">
          <thead><tr><th scope="col">策略名称</th><th scope="col">类型</th><th scope="col">最近修改</th><th scope="col">操作</th></tr></thead>
          <tbody>{items.map(item => <tr key={item.id}>
            <th scope="row"><Code2 size={16} /><span>{item.name}</span></th>
            <td>{item.language === 'python' ? strategyTypes[item.kind ?? 'single_bounded'] : `${languageLabel(item.language)} 源码`}</td><td><time dateTime={item.updated_at}>{displayTime.format(new Date(item.updated_at))}</time></td>
            <td><button aria-label={`打开 ${item.name}`} onClick={() => void open(item.id)}>打开<ArrowRight size={15} /></button></td>
          </tr>)}</tbody>
        </table></div> : <div className="lab-empty"><Code2 size={27} /><h2>还没有代码策略</h2><p>新建空白策略，或导入已有的源码文件。</p></div>}
    </section>
    {draft ? <>
      <header className="lab-editor-navigation">
        <button disabled={saving} onClick={() => requestExit(() => {
          if (labRoute() === '#research' && window.location.hash !== '#research') window.history.replaceState(window.history.state, '', '#research')
          resetEditor(null)
        })}><ArrowLeft size={16} />我的策略</button>
        <h1>{rqalpha ? '编辑 RQAlpha 日线策略' : multi ? '编辑 A 股多标的策略' : '编辑策略'}</h1>
      </header>
      {error ? <div className="lab-error" role="alert"><span>{error}</span>
        {conflict && record ? <button onClick={() => requestExit(() => void open(record.id))}>重新加载已保存版本</button> : null}
      </div> : null}
      {opening ? <p role="status" className="lab-empty">正在重新加载策略…</p> : null}
      <CodeStrategyWorkspace key={`${editorKey}:${multiEngine}`} draft={draft} ownerId={ownerId}
        onEdit={patch => setDraft(current => {
          if (!current) return current
          if (current.kind === 'multi_python') {
            const { name = current.name, source = current.source } = patch
            return { ...current, name, source }
          }
          const { name = current.name, source = current.source, language = current.language } = patch
          return { ...current, name, source, language }
        })}
        packageB64={multi?.package_b64}
        engineId={isMulti ? multiEngine : undefined}
        runDisabledReason={runDisabledReason}
        onSave={() => void save()} onRun={() => void (multi ? runMulti() : run())}
        onHistory={() => {
          if (!historyOpen) requestAnimationFrame(() => historyHeading.current?.focus())
          setHistoryOpen(!historyOpen)
          setHistoryError('')
        }}
        runtimeActions={rqalpha ? <p className="lab-form-note">RQAlpha 首期仅支持历史回测，不支持创建运行版本、发布订阅、持续模拟或 Proof。</p> : draft.language === 'python' ? <div className="lab-command-actions">
          <button type="button" disabled={running || !record || dirty || !draft.source.trim() || releaseBusy ||
            (multi ? !job || job.status !== 'succeeded' || multiResultStale : sourceBytes(draft.source) > MAX_BOUNDED_SOURCE)}
            onClick={() => void createRelease()}>{releaseBusy ? '提交中…' : '创建运行版本'}</button>
          {!record || dirty ? <span className="lab-form-note">先保存当前草稿。</span>
            : multi && (!job || job.status !== 'succeeded' || multiResultStale) ? <span className="lab-form-note">当前草稿需有成功的回测。</span> : null}
          {releaseError && <span role="alert">{releaseError}</span>}
        </div> : null}
        runFeedback={<div className="lab-run-feedback">
          <span role="status">{multi
            ? running ? '正在提交多股回测…' : runError ? '回测未完成' : inFlightJob ? `多股回测${multiJobStatus[inFlightJob.status]}` : job ? multiJobStatus[job.status] : runDisabledReason || ''
            : running ? '正在运行回测…' : runError ? '回测未完成' : singleResultNotice || (result ? '回测结果已就绪' : '')}</span>
          {inFlightJob && <button type="button" disabled={cancelling} onClick={() => void cancelJob()}>{cancelling ? '取消中…' : '取消任务'}</button>}
          {!running && (runError || result || job) ? <button onClick={() => resultHeading.current?.focus()}>{runError ? '查看原因' : '查看回测结果'}</button> : null}
          {multi && (capabilityError || capability?.available === false) && <button type="button" onClick={() => { setCapabilityCheck(null); setCapabilityAttempt(value => value + 1) }}>重试环境检查</button>}
        </div>}
        dirty={dirty} saved={!!record} saving={saving} running={multi ? runningMulti : running}>
        {draft.kind === 'multi_python'
          ? <LabMultiBacktestForm value={draft.settings} assets={assets} coverage={coverage?.data ?? null} coverageError={coverage?.error ?? ''}
              coverageBusy={coverageBusy} onCoverage={() => void checkCoverage()} engineLocked={!!draft.package_b64 || runningMulti}
              onChange={patch => {
                if (patch.engine_id && patch.engine_id !== multiEngine) {
                  setCapabilityCheck(null)
                  coverageRequest.current?.abort(); setCoverageBusy(false); setCoverageCheck(null)
                }
                setDraft(current => current?.kind === 'multi_python' ? { ...current, settings: { ...current.settings, ...patch } } : current)
              }} />
          : <LabBacktestForm value={draft.settings} assets={assets}
              onChange={patch => setDraft(current => current && current.kind !== 'multi_python' ? { ...current, settings: { ...current.settings, ...patch } } : current)} />}
        {!rqalpha && (releases.length > 0 || currentRelease) && <section className="lab-history" aria-label="关联运行版本">
          <h2>关联运行版本</h2>
          <ul>{(currentRelease && !releases.some(row => row.id === currentRelease.id) ? [currentRelease, ...releases] : releases).map(release => <li key={release.id}>
            <strong>v{release.version}</strong> · 草稿修订 {release.lab_revision ?? '未关联'} · {release.published ? '已公开' : '私有版本'}
            <div className="lab-command-actions">
              <a href={`#/trading?release=${encodeURIComponent(release.id)}`}>配置平台模拟</a>
              {!release.published && <button type="button" disabled={releaseBusy} onClick={() => void publicize(release)}>公开此版本</button>}
              {release.published && <BkcSubscription releaseId={release.id} owned subscribed={false} onChanged={() => undefined} />}
              {release.source_kind === 'python' && <CloudProofControl releaseId={release.id} owned proofStatus={release.proof_status} proofId={release.proof_id} sourceKind={release.source_kind} />}
            </div>
          </li>)}</ul>
        </section>}
        {historyOpen && multi ? <section className="lab-history" aria-labelledby="lab-history-heading">
          <header><h2 id="lab-history-heading" ref={historyHeading} tabIndex={-1}>历史回测</h2><button onClick={() => setHistoryOpen(false)}>收起</button></header>
          {jobsError ? <div className="lab-error" role="alert">{jobsError}<button onClick={() => { setJobsError(''); setJobsAttempt(value => value + 1) }}>重试</button></div>
            : jobs === null ? <p role="status">正在读取多股回测任务…</p>
            : jobs.length ? <div className="lab-table-scroll"><table className="lab-table lab-history-table">
              <thead><tr><th scope="col">运行时间</th><th scope="col">引擎</th><th scope="col">修订</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
              <tbody>{jobs.map(row => <tr key={row.id} className={job?.id === row.id ? 'lab-active-run' : undefined}>
                <td><time dateTime={row.created_at}>{displayTime.format(new Date(row.created_at))}</time></td>
                <td>{labMultiEngineLabels[multiJobEngine(row)]}</td>
                <td>{row.revision}</td><td>{multiJobStatus[row.status]}</td>
                <td><button onClick={() => void openJob(row)} aria-label={`查看 ${displayTime.format(new Date(row.created_at))} 的多股回测`}>查看</button></td>
              </tr>)}</tbody>
            </table></div> : <p>创建的任务会出现在这里。</p>}
        </section> : historyOpen ? <section className="lab-history" aria-labelledby="lab-history-heading">
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
          {multi ? <>
            {pollError && <p className="lab-error" role="alert">{pollError}</p>}
            {multiResultStale && <p className="lab-form-note">任务使用已保存的历史快照，当前修改尚未回测。</p>}
            {loadingRun ? <p role="status">正在读取回测快照…</p> : job ? <LabMultiBacktestResult job={job} ownerId={ownerId} /> : <p>保存并提交后，任务和结果可在历史回测中重新打开。</p>}
            {previousSuccess && previousSuccess.id !== job?.id && (runError || job?.status === 'failed') && <details className="lab-original-settings">
              <summary>上次成功的多股回测结果</summary><LabMultiBacktestResult job={previousSuccess} ownerId={ownerId} />
            </details>}
          </> : <>
            {singleResultNotice && <p className="lab-form-note">{singleResultNotice}</p>}
            {selectedRun && <details className="lab-original-settings">
              <summary>本次运行参数和源码摘要</summary>
              {selectedRun.source_sha256 && <code>{selectedRun.source_sha256}</code>}
              {result?.compute?.dataset_ids?.length ? <p>行情版本 {result.compute.dataset_ids.join('、')}</p> : null}
              <LabRunSettings settings={selectedRun.settings} />
            </details>}
            <ResultsPanel result={result} loading={running || loadingRun} panelMode="normal" onPanelMode={() => undefined} controls={false} />
          </>}
        </section>
      </CodeStrategyWorkspace>
    </> : null}
  </main>
}
