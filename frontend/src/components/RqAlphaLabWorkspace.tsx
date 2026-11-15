import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, Code2, FolderArchive, LockKeyhole, Plus, Upload } from 'lucide-react'
import { api } from '../api'
import type { ImportedPythonProject } from '../compute/pythonProject'
import { listLabProjects, readLabProject, saveLabProject, type LabProjectEntry } from '../lab-project-library'
import { formatPercent } from '../format'
import { LAB_NAVIGATION, guardLabHashChange, pushAtlasHash, setLabHashGuard, trackAtlasHistoryEntry } from '../lab-navigation'
import { defaultMultiSettings, labMultiEngineLabels, labOwnerHeaders, multiJobActive, multiJobEngine, multiJobStatus } from '../lab-strategy-types'
import type { LabBacktestSettings, LabDraft, LabSingleDraft, LabMultiCoverage, LabMultiDraft, LabMultiEngine, LabMultiJob, LabRunSummary, LabStrategy, LabStrategySummary } from '../lab-strategy-types'
import { labMultiApi, type LabIndustryCoverage, type LabMultiCapabilities } from '../lab-multi-api'
import { ApiError, request, RUNTIME_CHANGED_EVENT } from '../request'
import type { Asset, BacktestResult, StrategyRelease } from '../types'
import { RqAlphaCodeWorkspace } from './RqAlphaCodeWorkspace'
import { LabBacktestForm, LabRunSettings } from './LabBacktestForm'
import { LabConfirmDialog } from './LabConfirmDialog'
import { LabMultiBacktestForm, LabMultiBacktestResult } from './LabMultiBacktest'
import { ResultsPanel } from './ResultsPanel'
import { readStrategyFile, STRATEGY_LANGUAGES } from './strategy-languages'
import './lab-workbench.css'
import { BacktestComparison } from './BacktestComparison'
import { compareBacktests, type ComparisonRow } from '../compute/compareBacktests'
import PythonProjectWorkspace from './PythonProjectWorkspace'
import { PORTABLE_PYTHON_TEMPLATE } from './CodeStrategyWorkspace'

interface Props {
  typeControl?: ReactNode
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
const nativeDraft = (draft: LabDraft) => draft.kind !== 'multi_python' || draft.settings.engine_id === 'rqalpha'

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
    if (settings.universe) return '此设置属于旧版行业策略，只能查看历史。'
    if (settings.interval !== '1d' && !settings.industry) return '分钟回测仅支持已准备的行业/题材股票池，请先选择股票池。'
    if (settings.symbols.some(symbol => symbol.endsWith('.BJ'))) return 'RQAlpha 仅支持沪深 A 股，请移除北交所标的。'
  }
  return ''
}

export function RqAlphaLabWorkspace({ ownerId, assets, active, typeControl, defaults, onRunSaved }: Props) {
  const [comparisons, setComparisons] = useState<ComparisonRow[]>([])
  const [incomingArchive, setIncomingArchive] = useState<{ file: File } | null>(null)
  const archiveInput = useRef<HTMLInputElement>(null)
  const [openedProject, setOpenedProject] = useState<ImportedPythonProject | null>(null)
  const [archiveBusy, setArchiveBusy] = useState(false)
  const [localLibrary, setLocalLibrary] = useState<{ ownerId: string; entries: LabProjectEntry[] } | null>(null)
  const [projectListError, setProjectListError] = useState('')
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
  const [industryCheck, setIndustryCheck] = useState<{ owner: string; asOf: string | undefined; rows: LabIndustryCoverage[] | null; error: string } | null>(null)
  const [industryAttempt, setIndustryAttempt] = useState(0)
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
  const pendingImport = useRef<{ id: string; signature: string } | null>(null)
  const pendingExit = useRef<(() => void) | null>(null)
  const multiSubmitId = useRef<{ revision: number; id: string } | null>(null)
  const coverageRequest = useRef<AbortController | null>(null)
  const jobMutation = useRef<AbortController | null>(null)
  const navigationHandled = useRef('')
  const currentOwner = useRef(ownerId)

  const projectEntries = localLibrary?.ownerId === ownerId ? localLibrary.entries : []
  const libraryBusy = opening || archiveBusy
  const libraryEntries = [
    ...(items ?? []).map(item => ({ type: 'strategy' as const, item })),
    ...projectEntries.map(item => ({ type: 'project' as const, item })),
  ].sort((left, right) => right.item.updated_at.localeCompare(left.item.updated_at))
  const dirty = !!draft && JSON.stringify(draft) !== baseline
  const strategyId = record?.id
  const multi = draft?.kind === 'multi_python' ? draft : null
  const multiId = multi ? strategyId : undefined
  const isMulti = !!multi
  const multiEngine = multi?.settings.engine_id ?? 'atlas_portfolio'
  const rqalpha = isMulti && multiEngine === 'rqalpha'
  const readOnly = !!draft && !nativeDraft(draft)
  const industryAsOf = multi?.settings.start ? new Date(Date.parse(multi.settings.start) + 8 * 60 * 60 * 1000).toISOString().slice(0, 10) : undefined
  const industryCheckCurrent = industryCheck?.owner === ownerId && industryCheck.asOf === industryAsOf
  const industries = industryCheckCurrent ? industryCheck.rows : null
  const industryError = industryCheckCurrent ? industryCheck.error : ''
  const selectedIndustry = industries?.find(row => row.id === multi?.settings.industry)
  const capability = capabilityCheck?.engine === multiEngine ? capabilityCheck.data : null
  const capabilityError = capabilityCheck?.engine === multiEngine ? capabilityCheck.error : ''
  const coverage = coverageCheck?.settings === multi?.settings ? coverageCheck : null
  const inFlightJob = multiJobActive(job) ? job : jobs?.find(multiJobActive) ?? null
  const activeJobId = inFlightJob?.id
  const runningMulti = multiJobActive(inFlightJob) || running
  const industryUnavailable = multi?.settings.industry
    ? industryError || (industries === null ? '正在读取行业股票池。' : !selectedIndustry?.symbols.length ? selectedIndustry?.reason || '行业股票池尚未准备。'
      : multi.settings.symbols.some(symbol => !selectedIndustry.symbols.some(item => item.symbol === symbol && (multi.settings.interval === '1d' || item.minute_available !== false))) ? '所选股票不属于所选日期的行业名单，或尚无可用分钟行情，请核对并手动移除。' : '')
    : ''
  const minuteUnavailable = multi && multi.settings.interval !== '1d'
    ? !multi.settings.industry ? '分钟回测仅支持已准备的行业/题材股票池，请先选择股票池。'
      : !selectedIndustry?.start || !selectedIndustry.end || !capability?.minute_intervals?.includes(multi.settings.interval) || !selectedIndustry.minute_intervals.includes(multi.settings.interval)
        ? selectedIndustry?.reason || capability?.minute_reason || '尚未准备与当前行业配套的冻结分钟行情。' : ''
    : ''
  const runDisabledReason = readOnly ? '旧版策略只读保留，请新建 RQAlpha 策略。' : !multi ? dirty || !record ? '请先保存策略，再运行回测。' : draft?.language !== 'python' ? '当前语言支持编辑与下载，回测需要 Python。' : undefined
    : dirty ? '请先保存当前修改，再运行回测。'
    : capability?.available === false ? capability.reason || '执行环境未就绪。'
    : !capability?.available ? capabilityError || '正在读取执行环境。'
    : settingsError(multi.settings) ? settingsError(multi.settings)
    : industryUnavailable || minuteUnavailable ? industryUnavailable || minuteUnavailable
    : multi.settings.symbols.length < 1 ? '请加入至少一只 A 股。'
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
    let cancelled = false
    listLabProjects(ownerId).then(entries => {
      if (!cancelled) {
        setProjectListError('')
        setLocalLibrary({ ownerId, entries })
      }
    }).catch(reason => {
      if (!cancelled) setProjectListError(message(reason, '无法读取 ZIP 项目列表'))
    })
    return () => { cancelled = true }
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
    }).catch(reason => { if (!controller.signal.aborted) setJobsError(message(reason, '无法读取回测历史')) })
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
    if (!rqalpha) return
    const controller = new AbortController()
    labMultiApi.industries(ownerId, controller.signal, industryAsOf).then(rows => {
      if (!controller.signal.aborted) setIndustryCheck({ owner: ownerId, asOf: industryAsOf, rows, error: '' })
    }).catch(reason => {
      if (!controller.signal.aborted) setIndustryCheck({ owner: ownerId, asOf: industryAsOf, rows: null, error: message(reason, '无法读取行业股票池。') })
    })
    return () => controller.abort()
  }, [rqalpha, ownerId, industryAttempt, industryAsOf, editorKey])

  useEffect(() => {
    if (!rqalpha) return
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
  }, [rqalpha, multiEngine, ownerId, capabilityAttempt, editorKey])

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
    pendingImport.current = null
    multiSubmitId.current = null
    setEditorKey(key => key + 1)
    setOpening(false); setRunning(false); setLoadingRun(false)
    setOpenedProject(null); setIncomingArchive(null); setArchiveBusy(false)
    setDraft(next); setRecord(saved); setBaseline(initial ? JSON.stringify(initial) : '')
    setError(''); setConflict(false); setRunError(''); setResult(null); setComparisons([])
    setHistoryOpen(false); setHistory(null); setHistoryError(''); setSelectedRun(null)
    setJob(null); setPreviousSuccess(null); setJobs(null); setJobsError(''); setPollError(''); setCancelling(false)
    setCoverageCheck(null); setCoverageBusy(false); setReleases([])
    setCapabilityCheck(null)
  }, [])

  useEffect(() => {
    if (currentOwner.current === ownerId) return
    currentOwner.current = ownerId
    resetEditor(null)
    setItems(null)
    setProjectListError('')
    setIndustryCheck(null)
  }, [ownerId, resetEditor])

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

  const blankMulti = (source = rqalphaStarter): LabMultiDraft => ({
    kind: 'multi_python', name: '未命名策略', language: 'python', source,
    settings: { ...defaultMultiSettings, symbols: [], engine_id: 'rqalpha', interval: '1d' },
  })
  const blankSingle = (): LabSingleDraft => ({ name: '未命名策略', language: 'python', source: PORTABLE_PYTHON_TEMPLATE, settings: { ...defaults } })
  async function importNew(file: File) {
    const started = ++operation.current
    setError(''); setOpening(true)
    try {
      const imported = await readStrategyFile(file)
      if (started !== operation.current) return
      const isNative = imported.language === 'python' && /(?:from|import)\s+rqalpha\b|def\s+(?:handle_bar|init)\s*\(/.test(imported.source)
      const snapshot: LabDraft = isNative
        ? { ...blankMulti(imported.source), name: imported.name }
        : { ...blankSingle(), language: imported.language, name: imported.name, source: imported.source }
      const signature = JSON.stringify(snapshot)
      const submission = pendingImport.current?.signature === signature ? pendingImport.current
        : { id: crypto.randomUUID().replaceAll('-', ''), signature }
      pendingImport.current = submission
      const saved = await api.createLabStrategy(ownerId, submission.id, snapshot)
      if (started !== operation.current) return
      setItems(current => [saved, ...(current ?? []).filter(item => item.id !== saved.id)])
      resetEditor(draftOf(saved), saved)
    } catch (reason) {
      if (started === operation.current) {
        if (reason instanceof ApiError && reason.kind === 'http' && (reason.status ?? 500) < 500) pendingImport.current = null
        setError(message(reason, '无法导入源码'))
      }
    } finally {
      if (started === operation.current) setOpening(false)
    }
  }

  async function persistArchive(file: File, id?: string) {
    const saved = id ? await saveLabProject(ownerId, file, id) : await saveLabProject(ownerId, file)
    if (currentOwner.current === ownerId) {
      setLocalLibrary(current => ({
        ownerId,
        entries: [saved, ...(current?.ownerId === ownerId ? current.entries.filter(item => item.id !== saved.id) : [])],
      }))
    }
    return saved.id
  }

  async function openProject(source: File | LabProjectEntry) {
    openRequest.current?.abort()
    const controller = new AbortController()
    openRequest.current = controller
    const started = ++operation.current
    setArchiveBusy(true); setError('')
    try {
      const file = source instanceof File ? source : await readLabProject(ownerId, source)
      const { inspectPythonProject } = await import('../compute/pythonProject')
      const inspected = await inspectPythonProject(file, controller.signal)
      if (started !== operation.current || controller.signal.aborted) return
      const libraryId = source instanceof File ? await persistArchive(file) : source.id
      if (started !== operation.current || controller.signal.aborted) return
      resetEditor(null)
      setOpenedProject({ ...inspected, file, libraryId })
    } catch (reason) {
      if (started === operation.current && !controller.signal.aborted) setError(message(reason, '无法打开 ZIP 项目'))
    } finally {
      if (started === operation.current) setArchiveBusy(false)
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
        if (started === operation.current) {
          const next = draftOf(copied)
          resetEditor(next, null, nativeDraft(next) ? null : next)
        }
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
    if (!draft || readOnly || saveInFlight.current) return false
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

  const checkCoverage = async () => {
    if (!multi || readOnly || coverageBusy || industryUnavailable || minuteUnavailable) return
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

  const runSingle = async () => {
    if (!draft || draft.kind === 'multi_python' || !record || runDisabledReason || runRequest.current) return
    const snapshot = draft
    const started = operation.current
    const invalid = settingsError(snapshot.settings)
    if (invalid || !snapshot.settings.symbol) { setRunError(invalid || '请选择回测标的。'); return }
    const controller = new AbortController()
    runRequest.current = controller
    resultRequest.current += 1
    setRunning(true); setLoadingRun(false); setRunError(''); setComparisons([])
    const portable = /\bdef\s+target\s*\(/.test(snapshot.source)
    try {
      const rows = await compareBacktests({
        ...snapshot.settings, strategy_name: snapshot.name,
        adjustment: snapshot.settings.data_source === 'huggingface' ? 'raw' : 'auto',
        strategy_id: portable ? 'python_portable' : 'python_bounded',
        python_source: portable ? undefined : snapshot.source,
        portable_python: portable ? snapshot.source : undefined,
        lab_strategy_id: record.id, params: {},
      }, controller.signal, rows => { if (operation.current === started) setComparisons(rows) }, ownerId)
      if (controller.signal.aborted) return
      const next = rows.find(row => row.result)?.result
      if (next) setResult(next)
      setSelectedRun({ settings: snapshot.settings, source: snapshot.source })
      setHistoryAttempt(value => value + 1)
      onRunSaved()
    } catch (reason) {
      if (!controller.signal.aborted) setRunError(message(reason, '回测失败'))
    } finally {
      if (runRequest.current === controller) { runRequest.current = null; setRunning(false) }
    }
  }

  const runMulti = async () => {
    if (readOnly || !multi || !record || runDisabledReason || runningMulti || runRequest.current) return
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

  const openRun = async (row: LabRunSummary) => {
    const sequence = ++resultRequest.current
    setLoadingRun(true); setRunError('')
    try {
      const next = await api.getRun<BacktestResult>(row.id)
      if (sequence === resultRequest.current) {
        setComparisons([])
        setResult(next)
        setSelectedRun({ ...row, historical: true })
      }
    } catch (reason) {
      if (sequence === resultRequest.current) setRunError(message(reason, '无法打开回测结果'))
    } finally {
      if (sequence === resultRequest.current) setLoadingRun(false)
    }
  }

  const singleResultNotice = singleResultStale ? '结果对应旧版本，当前修改尚未回测。'
    : runError && result ? '下方为上次成功的回测结果。'
    : selectedRun?.historical ? '正在查看历史回测快照。' : ''

  const backToLibrary = () => requestExit(() => {
    if (labRoute() === '#research' && window.location.hash !== '#research') window.history.replaceState(window.history.state, '', '#research')
    resetEditor(null)
  })

  return <main className="lab-workbench" aria-label="策略实验室">
    <input ref={archiveInput} type="file" accept=".zip" hidden onChange={event => {
      const file = event.target.files?.[0]; event.target.value = ''
      if (!file || libraryBusy) return
      if (draft || openedProject) setIncomingArchive({ file })
      else void openProject(file)
    }} />
    {nextAction ? <LabConfirmDialog
      title="保存未完成的修改？"
      description={error || '源码或回测设置已修改。保存后可在当前账号继续编辑。'}
      confirmLabel="保存并离开" confirmDisabled={saving}
      onCancel={dismissExit}
      onConfirm={() => void save().then(ok => { if (ok) finishExit(nextAction) })}
      extraAction={<button disabled={saving} onClick={() => finishExit(nextAction)}>放弃修改</button>}
    /> : null}
    <section className="lab-library" aria-labelledby="lab-library-heading" hidden={!!draft || !!openedProject}>
      <header className="lab-library-header">
        <div className="lab-library-title">{typeControl}<div><h1 id="lab-library-heading">我的策略</h1><p><LockKeyhole size={15} />单文件随账号保存，ZIP 项目保存在当前浏览器。</p></div></div>
        <div className="lab-command-actions">
          <input ref={fileInput} type="file" accept=".py,.js,.ts,.rs,.go,.java,.cs,.cpp,.r,.jl" hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file && !libraryBusy) void importNew(file) }} />
          <button disabled={libraryBusy || items === null} onClick={() => fileInput.current?.click()}><Upload size={15} />导入代码</button>
          <button disabled={libraryBusy} onClick={() => archiveInput.current?.click()}>导入项目 ZIP</button>
          <button className="lab-primary" disabled={libraryBusy || items === null} onClick={() => resetEditor(blankSingle())}><Plus size={16} />新建策略</button>
        </div>
      </header>
      {!draft && !openedProject && error ? <p className="lab-error" role="alert">{error}</p> : null}
      {listError ? <div className="lab-empty" role="alert"><p>{listError}</p><button onClick={() => { setListError(''); setListAttempt(value => value + 1) }}>重新加载</button></div> : null}
      {projectListError ? <p className="lab-error" role="alert">{projectListError}</p> : null}
      {archiveBusy ? <p className="lab-empty" role="status">正在校验 ZIP 项目…</p>
        : opening ? <p className="lab-empty" role="status">正在打开策略…</p>
          : items === null && !listError ? <p className="lab-empty" role="status">正在加载策略…</p> : null}
      {libraryEntries.length ? <div className="lab-table-scroll"><table className="lab-table">
        <thead><tr><th scope="col">策略名称</th><th scope="col">类型</th><th scope="col">最近修改</th></tr></thead>
        <tbody>{libraryEntries.map(row => {
          const { item } = row
          const isProject = row.type === 'project'
          const itemType = isProject ? 'ZIP 项目' : row.item.language === 'python'
            ? row.item.kind === 'multi_python' ? 'Python 策略' : '单标的 Python 策略' : '历史 ' + languageLabel(row.item.language) + ' 源码'
          return <tr className="lab-strategy-row" key={row.type + ':' + item.id} onClick={() => {
            if (libraryBusy) return
            if (row.type === 'project') void openProject(row.item)
            else void open(row.item.id)
          }}>
            <th scope="row"><button type="button" className="lab-strategy-row-link" disabled={libraryBusy}
              aria-label={`打开 ${item.name}`}>
              {isProject ? <FolderArchive size={16} /> : <Code2 size={16} />}<span>{item.name}</span><ArrowRight className="lab-row-chevron" size={15} />
            </button></th>
            <td>{itemType}</td><td><time dateTime={item.updated_at}>{displayTime.format(new Date(item.updated_at))}</time></td>
          </tr>
        })}</tbody>
      </table></div> : !libraryBusy && items !== null && !listError ? <div className="lab-empty"><Code2 size={27} /><h2>还没有策略</h2><p>新建策略，或导入源码和 ZIP 项目。</p></div> : null}
    </section>
    {openedProject ? <PythonProjectWorkspace
      initialProject={openedProject} comparisonContext={{ settings: defaults, assets, ownerId }}
      draftDirty={false} draftToolbar={null} incomingArchive={incomingArchive} importDisabled={false}
      onOpenArchive={() => archiveInput.current?.click()} onArchiveImported={persistArchive} onBackToLibrary={backToLibrary}>
      {null}
    </PythonProjectWorkspace> : null}
    {draft ? <>
      {error ? <div className="lab-error" role="alert"><span>{error}</span>
        {conflict && record ? <button onClick={() => requestExit(() => void open(record.id))}>重新加载已保存版本</button> : null}
      </div> : null}
      {opening ? <p role="status" className="lab-empty">正在重新加载策略…</p> : null}
      {readOnly && <p className="lab-legacy-notice">旧版策略只读保留，可查看源码、下载和历史结果；不会转换为 RQAlpha 或重新执行。新策略请返回“我的策略”后新建。</p>}
      <PythonProjectWorkspace compact comparisonContext={{ settings: draft.kind === 'multi_python' ? defaults : draft.settings, assets, ownerId }} draftFilename="strategy.py" draftDirty={dirty} draftToolbar={null}
        incomingArchive={incomingArchive} importDisabled={running || saving} onOpenArchive={() => archiveInput.current?.click()} onArchiveImported={persistArchive} onBackToLibrary={backToLibrary}>
      <RqAlphaCodeWorkspace key={`${editorKey}:${multiEngine}`} draft={draft} ownerId={ownerId} readOnly={readOnly}
        navigation={<div className="lab-editor-navigation">
          {typeControl}
          <button disabled={saving} onClick={backToLibrary}><ArrowLeft size={16} />我的策略</button>
          <button type="button" disabled={running || saving} onClick={() => archiveInput.current?.click()}>打开项目 ZIP</button>
          <h1 className="lab-editor-heading">{readOnly ? '查看历史策略' : '编辑策略'}</h1>
        </div>}
        onEdit={patch => setDraft(current => {
          if (!current || readOnly) return current
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
        onSave={() => void save()} onRun={() => void (multi ? runMulti() : runSingle())}
        onHistory={() => {
          if (!historyOpen) requestAnimationFrame(() => historyHeading.current?.focus())
          setHistoryOpen(!historyOpen)
          setHistoryError('')
        }}
        runtimeActions={rqalpha ? <p className="lab-form-note">RQAlpha 历史回测不支持创建旧版运行版本、发布订阅、持续模拟或 Proof。</p> : null}
        runFeedback={<div className="lab-run-feedback">
          <span role="status">{multi
            ? running ? '正在提交回测…' : runError ? '回测未完成' : inFlightJob ? `回测${multiJobStatus[inFlightJob.status]}` : job ? multiJobStatus[job.status] : runDisabledReason || ''
            : running ? '正在运行回测…' : runError ? '回测未完成' : singleResultNotice || (result ? '回测结果已就绪' : '')}</span>
          {!multi && running && <button type="button" onClick={() => { runRequest.current?.abort(); setRunning(false); setRunError('本次回测已取消，可重新运行。') }}>取消回测</button>}
          {inFlightJob && <button type="button" disabled={cancelling} onClick={() => void cancelJob()}>{cancelling ? '取消中…' : '取消任务'}</button>}
          {!running && (runError || result || job) ? <button onClick={() => resultHeading.current?.focus()}>{runError ? '查看原因' : '查看回测结果'}</button> : null}
          {multi && (capabilityError || capability?.available === false) && <button type="button" onClick={() => { setCapabilityCheck(null); setCapabilityAttempt(value => value + 1) }}>重试环境检查</button>}
        </div>}
        dirty={dirty} saved={!!record} saving={saving} running={multi ? runningMulti : running}>
        <fieldset className="lab-readonly-settings" disabled={readOnly}>
          {draft.kind === 'multi_python'
            ? <LabMultiBacktestForm value={draft.settings} assets={assets} coverage={coverage?.data ?? null} coverageError={coverage?.error ?? ''}
                coverageBusy={coverageBusy} onCoverage={() => void checkCoverage()} readOnly={readOnly}
                industries={industries} industryError={industryError} capabilities={capability}
                onReloadIndustries={() => { setIndustryCheck(null); setIndustryAttempt(value => value + 1) }}
                onChange={patch => {
                  if (readOnly) return
                  coverageRequest.current?.abort(); setCoverageBusy(false); setCoverageCheck(null)
                  setDraft(current => current?.kind === 'multi_python' ? { ...current, settings: { ...current.settings, ...patch } } : current)
                }} />
            : <LabBacktestForm value={draft.settings} assets={assets} onChange={patch => setDraft(current => current && current.kind !== 'multi_python' ? { ...current, settings: { ...current.settings, ...patch } } : current)} />}
        </fieldset>
        {readOnly && releases.length > 0 && <section className="lab-history" aria-label="关联运行版本">
          <h2>关联运行版本</h2>
          <ul>{releases.map(release => <li key={release.id}>
            <strong>v{release.version}</strong> · 草稿修订 {release.lab_revision ?? '未关联'} · {release.published ? '已公开' : '私有版本'}
            <p className="lab-form-note">已有运行版本保留，不从历史策略页面创建、发布或启动新实例。</p>
          </li>)}</ul>
        </section>}
        {historyOpen && multi ? <section className="lab-history" aria-labelledby="lab-history-heading">
          <header><h2 id="lab-history-heading" ref={historyHeading} tabIndex={-1}>历史回测</h2><button onClick={() => setHistoryOpen(false)}>收起</button></header>
          {jobsError ? <div className="lab-error" role="alert">{jobsError}<button onClick={() => { setJobsError(''); setJobsAttempt(value => value + 1) }}>重试</button></div>
            : jobs === null ? <p role="status">正在读取回测任务…</p>
            : jobs.length ? <div className="lab-table-scroll"><table className="lab-table lab-history-table">
              <thead><tr><th scope="col">运行时间</th><th scope="col">引擎</th><th scope="col">修订</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
              <tbody>{jobs.map(row => <tr key={row.id} className={job?.id === row.id ? 'lab-active-run' : undefined}>
                <td><time dateTime={row.created_at}>{displayTime.format(new Date(row.created_at))}</time></td>
                <td>{labMultiEngineLabels[multiJobEngine(row)]}</td>
                <td>{row.revision}</td><td>{multiJobStatus[row.status]}</td>
                <td><button onClick={() => void openJob(row)} aria-label={`查看 ${displayTime.format(new Date(row.created_at))} 的回测`}>查看</button></td>
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
              <summary>上次成功的回测结果</summary><LabMultiBacktestResult job={previousSuccess} ownerId={ownerId} />
            </details>}
          </> : <>
            {singleResultNotice && <p className="lab-form-note">{singleResultNotice}</p>}
            {selectedRun && <details className="lab-original-settings">
              <summary>本次运行参数和源码摘要</summary>
              {selectedRun.source_sha256 && <code>{selectedRun.source_sha256}</code>}
              {result?.compute?.dataset_ids?.length ? <p>行情版本 {result.compute.dataset_ids.join('、')}</p> : null}
              <LabRunSettings settings={selectedRun.settings} />
            </details>}
            {comparisons.length ? <BacktestComparison rows={comparisons} />
              : <ResultsPanel result={result} loading={running || loadingRun} panelMode="normal" onPanelMode={() => undefined} controls={false} />}
          </>}
        </section>
      </RqAlphaCodeWorkspace>
      </PythonProjectWorkspace>
    </> : null}
  </main>
}
