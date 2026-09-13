import { memo, useEffect, useMemo, useRef, useState } from 'react'
import type React from 'react'
import { Beaker, Check, FlaskConical, LoaderCircle, Play, Plus, Save, ShieldCheck, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { formatNumber, formatPercent } from '../format'
import { LabConfirmDialog } from './LabConfirmDialog'
import type { ExecutionPipeline } from './ExecutionPipelinePanel'
import type {
  Asset,
  BacktestResult,
  CustomStrategyRecord,
  CustomStrategySpec,
  DataSource,
  IndicatorSpec,
  Interval,
  ResearchJob,
  ResearchResult,
  RuleNode,
  Strategy,
} from '../types'

export interface ResearchWorkspaceProps {
  executionPipeline?: ExecutionPipeline
  asset: Asset | null
  strategies: Strategy[]
  interval: Interval
  source: DataSource
  initialCapital: number
  commission: number
  slippage: number
  spread: number
  maxPosition: number
  maxParticipation: number
  onLoading: (loading: boolean) => void
  onError: (message: string) => void
  onCustomResult: (result: BacktestResult) => void
  onStrategySaved?: (record: CustomStrategyRecord) => void
  onResearchCompleted?: (job: ResearchJob) => void
  onDraftChange?: (dirty: boolean) => void
  view?: 'optimize' | 'builder'
  showHeader?: boolean
}

type Objective = 'sharpe' | 'calmar' | 'cagr' | 'total_return'
type BuilderSide = 'entry' | 'exit'

interface BuilderCondition {
  id: string
  left: IndicatorSpec
  operator: NonNullable<RuleNode['operator']>
  rightMode: 'value' | 'indicator'
  rightValue: number
  rightIndicator: IndicatorSpec
}

const FIELD_OPTIONS: Array<{ value: IndicatorSpec['field']; label: string; period: boolean }> = [
  { value: 'close', label: '收盘价', period: false },
  { value: 'open', label: '开盘价', period: false },
  { value: 'high', label: '最高价', period: false },
  { value: 'low', label: '最低价', period: false },
  { value: 'volume', label: '成交量', period: false },
  { value: 'sma', label: 'SMA', period: true },
  { value: 'ema', label: 'EMA', period: true },
  { value: 'rsi', label: 'RSI', period: true },
  { value: 'macd', label: 'MACD', period: false },
  { value: 'macd_signal', label: 'MACD Signal', period: false },
  { value: 'boll_upper', label: '布林上轨', period: true },
  { value: 'boll_lower', label: '布林下轨', period: true },
  { value: 'roc', label: '动量 ROC', period: true },
]

const OPERATORS: Array<{ value: BuilderCondition['operator']; label: string }> = [
  { value: 'gt', label: '大于' }, { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' }, { value: 'lte', label: '小于等于' },
  { value: 'crosses_above', label: '上穿' }, { value: 'crosses_below', label: '下穿' },
]

function uid() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
}

function condition(left: IndicatorSpec, operator: BuilderCondition['operator'], right: IndicatorSpec | number): BuilderCondition {
  return {
    id: uid(), left, operator,
    rightMode: typeof right === 'number' ? 'value' : 'indicator',
    rightValue: typeof right === 'number' ? right : 0,
    rightIndicator: typeof right === 'number' ? { field: 'sma', period: 20 } : right,
  }
}

function strategyDefaults(strategy: Strategy) {
  return Object.fromEntries(strategy.parameters.map((parameter) => [parameter.key, parameter.default]))
}

function defaultGrid(strategy: Strategy) {
  const grid: Record<string, string> = {}
  strategy.parameters.filter((parameter) => parameter.kind === 'number' || parameter.kind === 'integer').slice(0, 2).forEach((parameter) => {
    const base = Number(parameter.default)
    const delta = Math.max(Number(parameter.step ?? 1) * 5, Math.abs(base) * 0.25)
    const values = [base - delta, base, base + delta].map((value) => {
      const clipped = Math.min(Number(parameter.maximum ?? value), Math.max(Number(parameter.minimum ?? value), value))
      return parameter.kind === 'integer' ? Math.round(clipped) : Number(clipped.toPrecision(6))
    })
    grid[parameter.key] = [...new Set(values)].join(', ')
  })
  return grid
}

function parseGrid(text: string) {
  return [...new Set(text.trim().split(/[,，\s]+/).filter(Boolean).map(Number).filter(Number.isFinite))].slice(0, 20)
}

function metric(candidate: Record<string, number | null>, key: string) {
  return candidate[key] ?? null
}

function metricText(value: number | null, percent = false) {
  if (value == null) return '—'
  return percent ? formatPercent(value) : formatNumber(value, 2)
}

function IndicatorEditor({ value, onChange, label }: { value: IndicatorSpec; onChange: (value: IndicatorSpec) => void; label: string }) {
  const option = FIELD_OPTIONS.find((item) => item.value === value.field)
  return <span className="indicator-editor">
    <select aria-label={label} value={value.field} onChange={(event) => {
      const field = event.target.value as IndicatorSpec['field']
      const needsPeriod = FIELD_OPTIONS.find((item) => item.value === field)?.period
      onChange({ field, period: needsPeriod ? (value.period ?? 20) : null })
    }}>{FIELD_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
    {option?.period ? <input aria-label="指标周期" type="number" min={2} max={500} value={value.period ?? 20} onChange={(event) => onChange({ ...value, period: Number(event.target.value) })} /> : null}
  </span>
}

function RuleRow({ row, onChange, onDelete }: { row: BuilderCondition; onChange: (row: BuilderCondition) => void; onDelete: () => void }) {
  return <div className="rule-row">
    <div className="rule-field"><span>观察指标</span><IndicatorEditor label="观察指标" value={row.left} onChange={(left) => onChange({ ...row, left })} /></div>
    <label className="rule-field"><span>满足条件</span><select aria-label="条件操作符" value={row.operator} onChange={(event) => onChange({ ...row, operator: event.target.value as BuilderCondition['operator'] })}>{OPERATORS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
    <label className="rule-field"><span>比较对象</span><select aria-label="右值类型" value={row.rightMode} onChange={(event) => onChange({ ...row, rightMode: event.target.value as BuilderCondition['rightMode'] })}><option value="value">数值</option><option value="indicator">指标</option></select></label>
    <div className="rule-field"><span>{row.rightMode === 'value' ? '阈值' : '目标指标'}</span>{row.rightMode === 'value'
      ? <input aria-label="条件阈值" type="number" step="any" value={row.rightValue} onChange={(event) => onChange({ ...row, rightValue: Number(event.target.value) })} />
      : <IndicatorEditor label="目标指标" value={row.rightIndicator} onChange={(rightIndicator) => onChange({ ...row, rightIndicator })} />}</div>
    <button className="rule-delete" title="删除条件" onClick={onDelete}><Trash2 size={13} /></button>
  </div>
}

function conditionsToRule(rows: BuilderCondition[], combinator: 'all' | 'any'): RuleNode {
  return {
    kind: 'group', combinator,
    children: rows.map((row) => ({
      kind: 'condition', left: row.left, operator: row.operator,
      right_value: row.rightMode === 'value' ? row.rightValue : null,
      right_indicator: row.rightMode === 'indicator' ? row.rightIndicator : null,
    })),
  }
}

function ruleToConditions(rule: RuleNode): BuilderCondition[] {
  const nodes = rule.kind === 'group' ? (rule.children ?? []) : [rule]
  return nodes.filter((node) => node.kind === 'condition' && node.left && node.operator).map((node) => condition(
    node.left as IndicatorSpec,
    node.operator as BuilderCondition['operator'],
    node.right_indicator ?? Number(node.right_value ?? 0),
  ))
}

function ValidationRibbon({ result }: { result: ResearchResult }) {
  const robust = Boolean(result.summary.is_robust)
  return <div className="validation-ribbon">
    <div><small>IS</small><strong>{result.tested_combinations}</strong><span>训练组合</span></div>
    <i />
    <div><small>OOS</small><strong>{Number(result.summary.holdout_bars ?? 0)}</strong><span>留出K线</span></div>
    <i />
    <div><small>WF</small><strong>{Number(result.summary.walk_forward_windows ?? 0)}</strong><span>滚动窗口</span></div>
    <i />
    <div className={robust ? 'is-pass' : 'is-caution'}>{robust ? <ShieldCheck size={17} /> : <Beaker size={17} />}<strong>{robust ? '通过' : '待验证'}</strong><span>稳健性结论</span></div>
  </div>
}

export const ResearchWorkspace = memo(function ResearchWorkspace(props: ResearchWorkspaceProps) {
  const [localTab, setLocalTab] = useState<'optimize' | 'builder'>('optimize')
  const tab = props.view ?? localTab
  const [selected, setSelected] = useState<Set<string>>(() => new Set(['sma_cross', 'ema_cross', 'macd']))
  const [selectedCustom, setSelectedCustom] = useState<Set<string>>(() => new Set())
  const [gridStrategy, setGridStrategy] = useState('sma_cross')
  const [gridText, setGridText] = useState<Record<string, string>>(() => {
    const initial = props.strategies.find((item) => item.id === 'sma_cross') ?? props.strategies[0]
    return initial ? defaultGrid(initial) : {}
  })
  const [objective, setObjective] = useState<Objective>('sharpe')
  const [holdout, setHoldout] = useState(0.2)
  const [trainBars, setTrainBars] = useState(500)
  const [testBars, setTestBars] = useState(120)
  const [stepBars, setStepBars] = useState(120)
  const [maxWindows, setMaxWindows] = useState(6)
  const [job, setJob] = useState<ResearchJob | null>(null)
  const pollingRef = useRef<AbortController | null>(null)
  const activeGridStrategy = props.strategies.find((item) => item.id === gridStrategy) ?? props.strategies[0]

  const [builderName, setBuilderName] = useState('价格突破趋势')
  const [builderId, setBuilderId] = useState('price_trend')
  const [entryMode, setEntryMode] = useState<'all' | 'any'>('all')
  const [exitMode, setExitMode] = useState<'all' | 'any'>('any')
  const [entryRules, setEntryRules] = useState<BuilderCondition[]>(() => [condition({ field: 'close' }, 'crosses_above', { field: 'sma', period: 20 })])
  const [exitRules, setExitRules] = useState<BuilderCondition[]>(() => [condition({ field: 'close' }, 'crosses_below', { field: 'sma', period: 20 })])
  const [targetPosition, setTargetPosition] = useState(0.95)
  const [templates, setTemplates] = useState<CustomStrategyRecord[]>([])
  const [saving, setSaving] = useState(false)
  const [builderRunning, setBuilderRunning] = useState(false)
  const [builderDirty, setBuilderDirty] = useState(false)
  const [builderNotice, setBuilderNotice] = useState<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [pendingTemplate, setPendingTemplate] = useState<CustomStrategyRecord | null>(null)
  const [pendingDelete, setPendingDelete] = useState<CustomStrategyRecord | null>(null)
  const [templateLoadError, setTemplateLoadError] = useState('')
  const builderRevision = useRef(0)
  const savingRef = useRef(false)
  const runningRef = useRef(false)
  const researchStarting = useRef(false)
  const onDraftChange = props.onDraftChange

  const loadTemplates = async () => {
    try { setTemplates(await api.listCustomStrategies()); setTemplateLoadError('') }
    catch (reason) { setTemplateLoadError(reason instanceof Error ? reason.message : '无法读取已保存策略') }
  }

  useEffect(() => {
    let active = true
    api.listCustomStrategies().then((records) => {
      if (active) { setTemplates(records); setTemplateLoadError('') }
    }).catch((reason) => {
      if (active) setTemplateLoadError(reason instanceof Error ? reason.message : '无法读取已保存策略')
    })
    return () => { active = false; pollingRef.current?.abort() }
  }, [])

  useEffect(() => { onDraftChange?.(builderDirty) }, [builderDirty, onDraftChange])
  useEffect(() => {
    if (!builderDirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [builderDirty])
  const markBuilderEdited = () => {
    builderRevision.current += 1
    setBuilderDirty(true)
    setBuilderNotice(null)
  }

  const bestCandidates = useMemo(() => job?.result?.candidates.filter((candidate) => Object.keys(candidate.test_metrics).length > 0) ?? [], [job?.result])
  const heatmapCandidates = useMemo(() => job?.result?.candidates.filter((candidate) => candidate.strategy_id === gridStrategy) ?? [], [gridStrategy, job?.result])
  const heatmapKeys = activeGridStrategy?.parameters.filter((parameter) => gridText[parameter.key] != null).map((parameter) => parameter.key).slice(0, 2) ?? []
  const heatValues = heatmapCandidates.map((candidate) => candidate.objective_train).filter((value): value is number => value != null)
  const heatMin = heatValues.length ? Math.min(...heatValues) : 0
  const heatMax = heatValues.length ? Math.max(...heatValues) : 1

  const pollJob = async (id: string) => {
    pollingRef.current?.abort()
    const controller = new AbortController()
    pollingRef.current = controller
    try {
      while (!controller.signal.aborted) {
        const current = await api.getResearchJob(id, controller.signal)
        if (controller.signal.aborted) return
        setJob(current)
        if (!['queued', 'running'].includes(current.status)) {
          props.onLoading(false)
          if (current.status === 'failed') props.onError(current.error ?? '研究任务失败')
          if (current.status === 'completed') props.onResearchCompleted?.(current)
          break
        }
        await new Promise((resolve) => window.setTimeout(resolve, 700))
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        props.onLoading(false)
        props.onError(reason instanceof Error ? reason.message : '无法读取研究进度')
      }
    }
  }

  const runResearch = async () => {
    if (!props.asset || researchStarting.current || (job && ['queued', 'running'].includes(job.status))) return
    const chosen = props.strategies.filter((strategy) => selected.has(strategy.id))
    const customChosen = templates.filter((record) => selectedCustom.has(record.id))
    if (!chosen.length && !customChosen.length) return props.onError('至少选择一个策略')
    const parameterGrid: Record<string, number[]> = {}
    if (selected.has(gridStrategy)) {
      Object.entries(gridText).forEach(([key, value]) => {
        const values = parseGrid(value)
        if (values.length) parameterGrid[key] = values
      })
    }
    researchStarting.current = true
    props.onLoading(true)
    try {
      const created = await api.createResearchJob({
        execution_pipeline: props.executionPipeline,
        symbol: props.asset.symbol, asset_class: props.asset.asset_class,
        interval: props.interval, data_source: props.source, adjustment: 'auto', objective,
        holdout_ratio: holdout,
        experiments: [
          ...chosen.map((strategy) => ({ strategy_id: strategy.id, base_params: strategyDefaults(strategy), parameter_grid: strategy.id === gridStrategy ? parameterGrid : {} })),
          ...customChosen.map((record) => ({ strategy_id: record.id, base_params: {}, parameter_grid: {}, custom_strategy: record.spec })),
        ],
        walk_forward: { enabled: true, train_bars: trainBars, test_bars: testBars, step_bars: stepBars, max_windows: maxWindows },
        initial_capital: props.initialCapital, commission_rate: props.commission,
        slippage_rate: props.slippage, spread_rate: props.spread,
        max_position: props.maxPosition, max_participation_rate: props.maxParticipation,
      })
      setJob(created)
      void pollJob(created.id)
    } catch (reason) {
      props.onLoading(false)
      props.onError(reason instanceof Error ? reason.message : '无法创建研究任务')
    } finally { researchStarting.current = false }
  }

  const cancelJob = async () => {
    if (!job) return
    try {
      const cancelled = await api.cancelResearchJob(job.id)
      pollingRef.current?.abort()
      setJob(cancelled)
      props.onLoading(false)
    } catch (reason) { props.onError(reason instanceof Error ? reason.message : '取消失败；任务仍在执行，请重试') }
  }

  const updateRule = (side: BuilderSide, id: string, next: BuilderCondition) => {
    markBuilderEdited()
    const setter = side === 'entry' ? setEntryRules : setExitRules
    setter((current) => current.map((row) => row.id === id ? next : row))
  }
  const deleteRule = (side: BuilderSide, id: string) => {
    markBuilderEdited()
    const setter = side === 'entry' ? setEntryRules : setExitRules
    setter((current) => current.length > 1 ? current.filter((row) => row.id !== id) : current)
  }
  const addRule = (side: BuilderSide) => {
    markBuilderEdited()
    const setter = side === 'entry' ? setEntryRules : setExitRules
    setter((current) => [...current, condition({ field: 'rsi', period: 14 }, side === 'entry' ? 'lt' : 'gt', side === 'entry' ? 40 : 60)])
  }
  const buildSpec = (): CustomStrategySpec => ({
    id: builderId.trim().replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 64) || 'custom_strategy',
    name: builderName.trim() || '未命名策略', description: '由 Atlas 视觉策略构建器生成',
    entry: conditionsToRule(entryRules, entryMode), exit: conditionsToRule(exitRules, exitMode), target_position: targetPosition,
  })
  const saveBuilder = async () => {
    if (savingRef.current) return
    const revision = builderRevision.current
    savingRef.current = true
    setSaving(true)
    try {
      const record = await api.saveCustomStrategy(buildSpec())
      setTemplates((current) => [record, ...current.filter((item) => item.id !== record.id)])
      setSelectedCustom((current) => new Set(current).add(record.id))
      if (builderRevision.current === revision) setBuilderDirty(false)
      setBuilderNotice({ tone: 'success', text: builderRevision.current === revision ? `已保存“${record.spec.name}”，可在研究验证中选择此规则。` : `已保存提交时的版本；你在保存期间的新修改仍未保存。` })
      props.onStrategySaved?.(record)
    } catch (reason) { setBuilderNotice({ tone: 'error', text: `${reason instanceof Error ? reason.message : '保存失败'}；草稿已保留，可重试。` }) }
    finally { savingRef.current = false; setSaving(false) }
  }
  const runBuilder = async () => {
    if (!props.asset || runningRef.current) return
    runningRef.current = true
    setBuilderRunning(true)
    props.onLoading(true)
    try {
      const result = await api.runBacktest({
        execution_pipeline: props.executionPipeline,
        symbol: props.asset.symbol, asset_class: props.asset.asset_class, interval: props.interval,
        data_source: props.source, strategy_id: buildSpec().id, custom_strategy: buildSpec(), params: {},
        initial_capital: props.initialCapital, commission_rate: props.commission,
        slippage_rate: props.slippage, spread_rate: props.spread,
        max_position: props.maxPosition, max_participation_rate: props.maxParticipation, persist: true,
      })
      props.onCustomResult(result)
    } catch (reason) { props.onError(reason instanceof Error ? reason.message : '自定义策略回测失败') }
    finally { runningRef.current = false; setBuilderRunning(false); props.onLoading(false) }
  }
  const loadTemplate = (record: CustomStrategyRecord) => {
    builderRevision.current += 1
    setBuilderDirty(false)
    setPendingTemplate(null)
    setBuilderNotice({ tone: 'info', text: `已载入“${record.spec.name}”。编辑后保存相同 ID 将更新该模板；修改 ID 可另存副本。` })
    setBuilderId(record.spec.id); setBuilderName(record.spec.name); setTargetPosition(record.spec.target_position)
    setEntryMode(record.spec.entry.combinator ?? 'all'); setExitMode(record.spec.exit.combinator ?? 'any')
    setEntryRules(ruleToConditions(record.spec.entry)); setExitRules(ruleToConditions(record.spec.exit))
  }
  const deleteTemplate = async (record: CustomStrategyRecord) => {
    setPendingDelete(null)
    try {
      await api.deleteCustomStrategy(record.id)
      setTemplates((current) => current.filter((item) => item.id !== record.id))
      setSelectedCustom((current) => { const next = new Set(current); next.delete(record.id); return next })
      if (builderId === record.spec.id) setBuilderDirty(true)
      setBuilderNotice({ tone: 'info', text: `已删除“${record.spec.name}”模板；编辑器中的草稿未被删除，可以重新保存。` })
    } catch (reason) { setBuilderNotice({ tone: 'error', text: `${reason instanceof Error ? reason.message : '模板删除失败'}；列表未更改。` }) }
  }

  return <main className={`research-workspace ${props.showHeader === false ? 'is-embedded' : ''}`}>
    {pendingTemplate ? <LabConfirmDialog title="替换未保存的规则？" description={`载入“${pendingTemplate.spec.name}”会替换当前规则草稿。尚未保存的名称、参数和条件将丢失；取消后可以先保存模板。`} confirmLabel="放弃草稿并载入" destructive onCancel={() => setPendingTemplate(null)} onConfirm={() => loadTemplate(pendingTemplate)} /> : null}
    {pendingDelete ? <LabConfirmDialog title="删除已保存的模板？" description={`“${pendingDelete.spec.name}”将从模板库移除，无法在列表中撤销。已生成的回测记录不会删除，当前编辑草稿也会保留。`} confirmLabel="确认删除模板" destructive onCancel={() => setPendingDelete(null)} onConfirm={() => void deleteTemplate(pendingDelete)} /> : null}
    {props.showHeader === false ? null : <header className="research-header">
      <div><FlaskConical size={17} /><span><strong>策略研究中心</strong><small>{props.asset?.symbol ?? '请先选择标的'} · {props.interval}</small></span></div>
      <nav><button className={tab === 'optimize' ? 'is-active' : ''} onClick={() => setLocalTab('optimize')}>参数研究</button><button className={tab === 'builder' ? 'is-active' : ''} onClick={() => setLocalTab('builder')}>策略构建</button></nav>
    </header>}
    {tab === 'optimize' ? <div className="research-layout">
      <aside className="research-config">
        <section><h3>对比策略</h3><div className="strategy-checks">{templates.map((record) => <label className="is-custom" key={record.id}><input type="checkbox" checked={selectedCustom.has(record.id)} onChange={() => setSelectedCustom((current) => { const next = new Set(current); if (next.has(record.id)) next.delete(record.id); else next.add(record.id); return next })} /><span><strong>{record.spec.name}</strong><small>视觉规则 · 当前项目制品</small></span></label>)}{props.strategies.map((strategy) => <label key={strategy.id}><input type="checkbox" checked={selected.has(strategy.id)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(strategy.id)) next.delete(strategy.id); else next.add(strategy.id); return next })} /><span><strong>{strategy.name}</strong><small>{strategy.category}</small></span></label>)}</div></section>
        <section><h3>参数网格</h3><label className="field"><span>优化策略</span><select value={gridStrategy} onChange={(event) => { const id = event.target.value; setGridStrategy(id); const strategy = props.strategies.find((item) => item.id === id); if (strategy) setGridText(defaultGrid(strategy)) }}>{props.strategies.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.name}</option>)}</select></label>{activeGridStrategy?.parameters.filter((parameter) => parameter.kind === 'number' || parameter.kind === 'integer').slice(0, 2).map((parameter) => <label className="field" key={parameter.key}><span>{parameter.label}<small>逗号分隔，最多20个</small></span><input value={gridText[parameter.key] ?? ''} onChange={(event) => setGridText((current) => ({ ...current, [parameter.key]: event.target.value }))} /></label>)}</section>
        <section><h3>验证设置</h3><label className="field"><span>排名目标</span><select value={objective} onChange={(event) => setObjective(event.target.value as Objective)}><option value="sharpe">Sharpe</option><option value="calmar">Calmar</option><option value="cagr">CAGR</option><option value="total_return">总收益</option></select></label><label className="field"><span>留出集比例</span><input type="number" min={10} max={40} value={Math.round(holdout * 100)} onChange={(event) => setHoldout(Number(event.target.value) / 100)} /></label><div className="wf-grid"><label><span>训练</span><input type="number" value={trainBars} onChange={(event) => setTrainBars(Number(event.target.value))} /></label><label><span>测试</span><input type="number" value={testBars} onChange={(event) => setTestBars(Number(event.target.value))} /></label><label><span>步长</span><input type="number" value={stepBars} onChange={(event) => setStepBars(Number(event.target.value))} /></label><label><span>窗口</span><input type="number" value={maxWindows} onChange={(event) => setMaxWindows(Number(event.target.value))} /></label></div></section>
        {job && ['queued', 'running'].includes(job.status) ? <div className="research-progress"><span><LoaderCircle size={13} className="spin" />{job.message}</span><div><i style={{ width: `${job.progress * 100}%` }} /></div><button onClick={cancelJob}><X size={12} />取消</button></div> : <button className="research-run" onClick={runResearch} disabled={!props.asset}><Play size={14} fill="currentColor" />运行稳健性研究</button>}
      </aside>
      <section className="research-results">
        {job?.result ? <><ValidationRibbon result={job.result} /><div className="research-summary"><div><small>平均 OOS Sharpe</small><strong>{metricText(Number(job.result.summary.average_oos_sharpe ?? 0))}</strong></div><div><small>最差 OOS Sharpe</small><strong>{metricText(Number(job.result.summary.worst_oos_sharpe ?? 0))}</strong></div><div><small>盈利窗口比例</small><strong>{metricText(Number(job.result.summary.profitable_window_ratio ?? 0), true)}</strong></div></div><div className="research-table-wrap"><table className="research-table"><thead><tr><th>#</th><th>策略 / 胜出参数</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS收益</th><th>OOS回撤</th><th>修正p值</th><th>稳健分</th></tr></thead><tbody>{bestCandidates.map((candidate) => <tr key={`${candidate.strategy_id}-${candidate.rank}`}><td>{candidate.rank}</td><td><strong>{props.strategies.find((item) => item.id === candidate.strategy_id)?.name ?? templates.find((item) => item.id === candidate.strategy_id)?.spec.name ?? candidate.strategy_id}</strong><small>{Object.entries(candidate.params).map(([key, value]) => `${key}=${value}`).join(' · ') || '固定规则版本'}</small>{candidate.warnings.length ? <em title={candidate.warnings.join('\n')}>{candidate.warnings.length}项风险</em> : <em className="pass"><Check size={10} />无硬性警告</em>}</td><td>{metricText(metric(candidate.train_metrics, 'sharpe'))}</td><td>{metricText(metric(candidate.test_metrics, 'sharpe'))}</td><td>{metricText(metric(candidate.test_metrics, 'total_return'), true)}</td><td>{metricText(metric(candidate.test_metrics, 'max_drawdown'), true)}</td><td>{metricText(candidate.adjusted_p_value)}</td><td><b>{candidate.robustness_score.toFixed(0)}</b></td></tr>)}</tbody></table></div>{heatmapKeys.length >= 2 && heatmapCandidates.length ? <section className="parameter-map"><header><strong>训练集参数地形</strong><small>颜色只表示 IS {objective}，不代表样本外结论</small></header><div className="heat-grid">{heatmapCandidates.map((candidate, index) => { const value = candidate.objective_train ?? heatMin; const intensity = (value - heatMin) / Math.max(heatMax - heatMin, 1e-9); return <div key={index} style={{ '--heat': intensity } as React.CSSProperties}><span>{heatmapKeys.map((key) => `${key} ${candidate.params[key]}`).join(' / ')}</span><strong>{metricText(value)}</strong></div> })}</div></section> : null}</> : <div className="research-empty"><FlaskConical size={28} /><strong>让策略离开样本内</strong><span>选择策略和参数网格，Atlas 会完成留出测试、多重测试修正与 Walk-forward 滚动验证。</span></div>}
      </section>
    </div> : <div className="builder-layout">
      <aside className="builder-library"><details><summary>已保存的规则</summary>
        {templateLoadError ? <div className="lab-inline-error" role="alert"><strong>无法读取模板库</strong><span>{templateLoadError}</span><button onClick={() => void loadTemplates()}>重试读取</button></div> : null}
        {templates.length ? templates.map((record) => <div className="template-row" key={record.id}>
          <button aria-label={`载入模板 ${record.spec.name}`} disabled={saving} onClick={() => builderDirty ? setPendingTemplate(record) : loadTemplate(record)}><strong>{record.spec.name}</strong><small>{record.id}</small></button>
          <button disabled={saving} aria-label={`删除模板 ${record.spec.name}`} onClick={() => setPendingDelete(record)}><Trash2 size={12} /></button>
        </div>) : !templateLoadError ? <p>保存第一套规则后，可在这里重新载入。草稿只保留在当前页面内存中。</p> : null}
      </details></aside>
      <section className="builder-canvas">
        <div className="builder-status-area">
          <div className={`lab-draft-status ${builderDirty ? 'is-dirty' : ''}`}><strong>{builderDirty ? '规则草稿 · 未保存' : '规则编辑器'}</strong><span>切换实验室步骤会保留草稿；刷新或关闭页面前请保存。</span></div>
          {builderNotice ? <div className={`lab-builder-feedback is-${builderNotice.tone}`} role={builderNotice.tone === 'error' ? 'alert' : 'status'}>
            <span>{builderNotice.tone === 'success' ? <Check size={13} /> : builderNotice.tone === 'error' ? <X size={13} /> : <Beaker size={13} />}{builderNotice.text}</span>
            <button type="button" aria-label="关闭规则编辑器提示" title="关闭提示" onClick={() => setBuilderNotice(null)}><X size={13} /></button>
          </div> : null}
        </div>
        <header><div><label><span>策略名称</span><input value={builderName} onChange={(event) => { markBuilderEdited(); setBuilderName(event.target.value) }} /></label><label><span>策略 ID</span><input value={builderId} onChange={(event) => { markBuilderEdited(); setBuilderId(event.target.value) }} /></label></div><label className="target-position"><span>目标仓位</span><input type="number" min={1} max={100} value={Math.round(targetPosition * 100)} onChange={(event) => { markBuilderEdited(); setTargetPosition(Number(event.target.value) / 100) }} /><em>%</em></label></header>
        <div className="logic-flow">
          <section className="logic-block entry"><header><span><i />ENTRY 入场条件</span><select aria-label="入场条件组合" value={entryMode} onChange={(event) => { markBuilderEdited(); setEntryMode(event.target.value as 'all' | 'any') }}><option value="all">全部满足 AND</option><option value="any">任一满足 OR</option></select></header>{entryRules.map((row) => <RuleRow key={row.id} row={row} onChange={(next) => updateRule('entry', row.id, next)} onDelete={() => deleteRule('entry', row.id)} />)}<button className="add-rule" onClick={() => addRule('entry')}><Plus size={12} />添加入场条件</button></section>
          <div className="logic-connector"><i /><span>持有</span><i /></div>
          <section className="logic-block exit"><header><span><i />EXIT 退出条件</span><select aria-label="退出条件组合" value={exitMode} onChange={(event) => { markBuilderEdited(); setExitMode(event.target.value as 'all' | 'any') }}><option value="all">全部满足 AND</option><option value="any">任一满足 OR</option></select></header>{exitRules.map((row) => <RuleRow key={row.id} row={row} onChange={(next) => updateRule('exit', row.id, next)} onDelete={() => deleteRule('exit', row.id)} />)}<button className="add-rule" onClick={() => addRule('exit')}><Plus size={12} />添加退出条件</button></section>
        </div>
        <footer><p><ShieldCheck size={13} /><span>条件在收盘确认，下一根开盘执行。回测使用当前草稿，不等于保存规则。</span></p><button onClick={saveBuilder} disabled={saving}>{saving ? <LoaderCircle className="spin" size={13} /> : <Save size={13} />}{saving ? '保存中…' : '保存模板'}</button><button className="builder-run" onClick={runBuilder} disabled={!props.asset || builderRunning}><Play size={13} fill="currentColor" />{builderRunning ? '回测中…' : '运行自定义回测'}</button></footer>
      </section>
    </div>}
  </main>
})
