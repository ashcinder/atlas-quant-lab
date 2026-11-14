import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { formatMoney, formatNumber, formatPercent } from '../format'
import { labMultiEngineLabels, multiJobActive, multiJobEngine, multiJobStatus } from '../lab-strategy-types'
import type { LabMultiCoverage, LabMultiJob, LabMultiSettings, LabMultiTrade } from '../lab-strategy-types'
import type { Asset } from '../types'
import { LabBacktestReport } from './LabBacktestReport'

const EquityChart = lazy(() => import('./EquityChart').then(module => ({ default: module.EquityChart })))
const tradeTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Shanghai' })
const marketTime = (seconds: number) => tradeTime.format(new Date(seconds * 1000))
const localDate = (value: string | null) => value ? new Date(Date.parse(value) + 8 * 60 * 60 * 1000).toISOString().slice(0, 16) : ''
const marketDate = (value: string) => value ? new Date(`${value}+08:00`).toISOString() : null

const costs = [
  ['commission_rate', '手续费', 10], ['slippage_rate', '滑点', 10],
  ['max_position', '单股仓位上限', 100], ['max_participation_rate', '最大成交参与率', 100],
] as const

const cnSymbol = /^(?:[036][0-9]{5}\.(?:SS|SZ)|[489][0-9]{5}\.BJ)$/
const cnEquity = (item: Asset) => item.currency === 'CNY' && item.asset_class === 'equity' && cnSymbol.test(item.symbol)
const symbolsLabel = (settings: LabMultiSettings) => settings.universe ? `行业成员名单 · ${settings.universe}` : settings.symbols.join('、') || '尚未选择'

export function LabMultiBacktestForm({ value, assets, onChange, coverage, coverageBusy, coverageError, onCoverage, engineLocked = false }: {
  value: LabMultiSettings
  assets: Asset[]
  onChange: (patch: Partial<LabMultiSettings>) => void
  coverage: LabMultiCoverage | null
  coverageBusy: boolean
  coverageError: string
  onCoverage: () => void
  engineLocked?: boolean
}) {
  const rqalpha = value.engine_id === 'rqalpha'
  const acceptsSymbol = (symbol: string) => cnSymbol.test(symbol) && (!rqalpha || !symbol.endsWith('.BJ'))
  const invalidPool = rqalpha && (!!value.universe || value.symbols.some(symbol => !acceptsSymbol(symbol)))
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Asset[]>([])
  const [searchError, setSearchError] = useState('')
  const [selected, setSelected] = useState('')
  const [parameterText, setParameterText] = useState(JSON.stringify(value.parameters ?? {}, null, 2))
  const [parameterError, setParameterError] = useState('')
  useEffect(() => {
    const text = query.trim()
    if (!text) return
    let active = true
    const timer = window.setTimeout(() => {
      api.searchAssets(text).then(items => {
        if (active) setMatches(items.filter(cnEquity))
      }).catch(() => { if (active) setSearchError('无法搜索行情目录。') })
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query])
  const catalog = useMemo(() => new Map([...assets.filter(cnEquity), ...matches].map(asset => [asset.symbol, asset])), [assets, matches])
  const choices = [...catalog.values()].filter(asset => !value.symbols.includes(asset.symbol) && acceptsSymbol(asset.symbol))
  const add = () => {
    const code = (selected || query.trim()).toUpperCase()
    if (!acceptsSymbol(code) || value.symbols.includes(code) || value.symbols.length >= 150) return
    onChange({ symbols: [...value.symbols, code] })
    setSelected(''); setQuery(''); setMatches([])
  }
  const candidate = selected || query.trim().toUpperCase()
  const parameterChanged = parameterText !== JSON.stringify(value.parameters ?? {}, null, 2)
  const applyParameters = () => {
    try {
      const parsed = JSON.parse(parameterText) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || Object.values(parsed).some(item => !['number', 'boolean', 'string'].includes(typeof item) || typeof item === 'number' && !Number.isFinite(item))) {
        throw new Error('参数必须是由字符串、数值或布尔值组成的 JSON 对象。')
      }
      const parameters = parsed as NonNullable<LabMultiSettings['parameters']>
      onChange({ parameters }); setParameterText(JSON.stringify(parameters, null, 2)); setParameterError('')
    } catch (reason) {
      setParameterError(reason instanceof SyntaxError ? '请检查 JSON 格式。' : reason instanceof Error ? reason.message : '无法读取参数。')
    }
  }

  return <section className="lab-settings" aria-labelledby="lab-settings-title">
    <h2 id="lab-settings-title">多股回测设置</h2>
    <div className="lab-settings-grid"><label>回测引擎<select value={value.engine_id ?? 'atlas_portfolio'} disabled={engineLocked || !!value.universe} onChange={event => {
      const engine_id = event.target.value === 'rqalpha' ? 'rqalpha' : 'atlas_portfolio'
      onChange({ engine_id, ...(engine_id === 'rqalpha' ? { interval: '1d' } : { benchmark: null }) })
    }}>
      <option value="atlas_portfolio">Atlas 自研引擎</option>
      <option value="rqalpha">RQAlpha 公开版 · 日线</option>
    </select></label></div>
    <p className="lab-form-note">切换引擎只修改配置，不会转换或替换源码；请按所选协议编写，保存后重新回测。</p>
    {(engineLocked || value.universe) && <p className="lab-form-note">现有策略包和行业示例使用 Atlas 协议；RQAlpha 请从原生源码入口新建。</p>}
    {rqalpha && <p className="lab-form-note">学术非商用 · 原生 init / handle_bar · 仅静态沪深 A 股日线。按当前 K 线收盘价撮合（current_bar），不等于收盘后可按该价格实盘成交。最低佣金 5 元，卖出印花税按历史日期计算；仓位上限为订单前风控，不能作为实盘保障。首期不支持发布、持续模拟或 Proof，结果未经 ZKP 验证。</p>}
    {invalidPool && <p className="lab-form-note" role="alert">RQAlpha 首期不支持北交所或动态行业股票池，请移除不支持的标的或切回 Atlas。</p>}
    <div className="lab-stock-pool">
      {value.universe ? <p>{symbolsLabel(value)}</p> : <>
        <div className="lab-settings-grid">
          <label>搜索或输入股票代码<input type="search" value={query} placeholder="例如 600519.SS" onChange={event => { setQuery(event.target.value); setSelected(''); setMatches([]); setSearchError('') }} /></label>
          <label>行情目录<select value={selected} onChange={event => setSelected(event.target.value)}>
            <option value="">选择 A 股</option>
            {choices.map(asset => <option key={asset.symbol} value={asset.symbol}>{asset.symbol} · {asset.name}</option>)}
          </select></label>
        </div>
        {searchError && <p className="lab-form-note" role="status">{searchError}</p>}
        <div className="lab-command-actions">
          <button type="button" disabled={!acceptsSymbol(candidate) || value.symbols.includes(candidate) || value.symbols.length >= 150} onClick={add}>加入股票池</button>
          <span className="lab-form-note">已选 {value.symbols.length} / 150 只 · 静态股票池</span>
        </div>
        {value.symbols.length > 0 && <ul aria-label="已选股票" className="lab-pool-symbols">
          {value.symbols.map(symbol => <li key={symbol}>{symbol}<button type="button" aria-label={`移除 ${symbol}`} onClick={() => onChange({ symbols: value.symbols.filter(value => value !== symbol) })}>×</button></li>)}
        </ul>}
      </>}
    </div>
    <div className="lab-settings-grid">
      <label>开始时间（北京时间）<input type="datetime-local" value={localDate(value.start)} onChange={event => onChange({ start: marketDate(event.target.value) })} /></label>
      <label>结束时间（北京时间）<input type="datetime-local" value={localDate(value.end)} onChange={event => onChange({ end: marketDate(event.target.value) })} /></label>
      <label>行情周期<select value={value.interval} disabled={rqalpha} onChange={event => onChange({ interval: event.target.value === '15m' ? '15m' : '1d' })}>
        <option value="1d">日线</option>{!rqalpha && <option value="15m">15 分钟</option>}
      </select></label>
      <label>共享初始资金（元）<input type="number" min="0.01" step="any" value={value.initial_capital || ''} onChange={event => onChange({ initial_capital: Number(event.target.value) })} /></label>
      {rqalpha && <label>收益基准<select value={value.benchmark ?? ''} onChange={event => onChange({ benchmark: event.target.value ? event.target.value as LabMultiSettings['benchmark'] : null })}>
        <option value="">无基准</option><option value="000300.SS">沪深300 · 000300.SS</option><option value="000905.SS">中证500 · 000905.SS</option><option value="000001.SS">上证指数 · 000001.SS</option>
      </select></label>}
      {rqalpha && <p className="lab-form-note">基准仅使用已冻结且覆盖完整区间的数据；缺少覆盖时会明确提示，不下载或订购行情。</p>}
    </div>
    <details className="lab-advanced">
      <summary>撮合和策略参数</summary>
      <div className="lab-settings-grid">
        {costs.map(([key, label, max]) => <label key={key}>{label}（%）<input type="number" min={max === 100 ? 0.0001 : 0} max={max} step="any" value={Number((value[key] * 100).toFixed(8))} onChange={event => onChange({ [key]: Number(event.target.value) / 100 })} /></label>)}
        <label className="lab-form-note">策略参数（JSON）<textarea value={parameterText} rows={4} onChange={event => setParameterText(event.target.value)} /></label>
        <div className="lab-command-actions"><button type="button" disabled={!parameterChanged} onClick={applyParameters}>应用参数</button></div>
        {parameterChanged && <p className="lab-form-note">修改后的参数需应用后才进入策略设置。</p>}
        {parameterError && <p role="alert" className="lab-form-note">{parameterError}</p>}
      </div>
    </details>
    <div className="lab-command-actions lab-coverage">
      <p className="lab-form-note">覆盖检查只读取已准备的数据快照，不会下载或订购行情。</p>
      <button type="button" disabled={coverageBusy || invalidPool || !value.universe && value.symbols.length < 2} onClick={onCoverage}>{coverageBusy ? '检查中…' : '检查行情覆盖'}</button>
      {coverage && <p role="status">{coverage.available ? '可回测' : '暂不可回测'}{coverage.start != null && coverage.end != null ? ` · ${marketTime(coverage.start)} 至 ${marketTime(coverage.end)}` : ''}{coverage.reason ? ` · ${coverage.reason}` : ''}</p>}
      {coverageError && <p role="alert">{coverageError}</p>}
    </div>
  </section>
}

export function LabMultiTradeTable({ trades }: { trades: LabMultiTrade[] }) {
  if (!trades.length) return <p>暂无成交。</p>
  return <div className="lab-table-scroll"><table className="lab-table">
    <thead><tr><th scope="col">成交时间</th><th scope="col">股票</th><th scope="col">方向</th><th scope="col">股数</th><th scope="col">价格</th><th scope="col">费用</th></tr></thead>
    <tbody>{trades.map((trade, index) => <tr key={`${trade.time}:${trade.symbol}:${index}`}>
      <td>{marketTime(trade.time)}</td><th scope="row">{trade.symbol}</th><td>{trade.side === 'buy' ? '买入' : '卖出'}</td>
      <td>{formatNumber(trade.quantity, 0)}</td><td>{formatMoney(trade.price)}</td><td>{formatMoney(trade.fee)}</td>
    </tr>)}</tbody>
  </table></div>
}

function downloadResult(job: LabMultiJob) {
  const engine_id = multiJobEngine(job)
  const snapshot = { ...job, engine_id, engine_version: job.engine_version ?? job.result?.engine_version,
    matching_type: job.matching_type ?? job.result?.matching_type ?? (engine_id === 'rqalpha' ? 'current_bar' : 'next_open') }
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `atlas-backtest-${job.id}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export function LabMultiBacktestResult({ job, ownerId = '' }: { job: LabMultiJob; ownerId?: string }) {
  const { result, settings } = job
  const engine = multiJobEngine(job)
  const version = job.engine_version ?? result?.engine_version
  const matching = job.matching_type ?? result?.matching_type ?? (engine === 'rqalpha' ? 'current_bar' : 'next_open')
  const matchingLabel = matching === 'current_bar' ? '当前 K 线收盘价（current_bar）' : matching === 'next_open' ? '下一根 K 线开盘价（next_open）' : matching
  const points = useMemo(() => {
    if (!result) return []
    let peak = result.initial_capital
    return result.equity.map(point => {
      peak = Math.max(peak, point.equity)
      return { time: point.time, equity: point.equity, drawdown: point.equity / peak - 1 }
    })
  }, [result])
  if (engine === 'rqalpha') return <LabBacktestReport key={job.id} job={job} ownerId={ownerId} onLegacyDownload={() => downloadResult(job)} legacyOverview={result && <>
    <dl className="lab-run-settings">
      <div><dt>共享初始资金</dt><dd>{formatMoney(result.initial_capital)}</dd></div>
      <div><dt>期末权益</dt><dd>{formatMoney(result.final_equity)}</dd></div>
      <div><dt>扣费后收益</dt><dd>{formatPercent(result.total_return)}</dd></div>
      <div><dt>最大回撤</dt><dd>{formatPercent(result.max_drawdown)}</dd></div>
    </dl>
    <Suspense fallback={<p role="status">正在加载权益曲线…</p>}><EquityChart points={points} /></Suspense>
    {result.native_metrics && <details className="lab-original-settings"><summary>米筐原生指标</summary><p>保留引擎原始指标口径，不将其视为经过证明的业绩。</p><pre>{JSON.stringify(result.native_metrics, null, 2)}</pre></details>}
    <details className="lab-original-settings"><summary>成交明细（{result.trades.length}）</summary><LabMultiTradeTable trades={result.trades} /></details>
  </>} />
  return <>
    <p>草稿修订 {job.revision} · {multiJobStatus[job.status]} · {labMultiEngineLabels[engine]}{version ? ` ${version}` : ''} · 未经 ZKP 验证</p>
    <p className="lab-form-note">本次撮合：{matchingLabel}</p>
    {job.error && <p className="lab-error" role="alert">{job.error}</p>}
    {multiJobActive(job) && <progress aria-label="多股回测进度" max={1} value={job.progress ?? undefined} />}
    {result && <>
      <dl className="lab-run-settings">
        <div><dt>共享初始资金</dt><dd>{formatMoney(result.initial_capital)}</dd></div>
        <div><dt>期末权益</dt><dd>{formatMoney(result.final_equity)}</dd></div>
        <div><dt>扣费后收益</dt><dd>{formatPercent(result.total_return)}</dd></div>
        <div><dt>最大回撤</dt><dd>{formatPercent(result.max_drawdown)}</dd></div>
      </dl>
      <Suspense fallback={<p role="status">正在加载权益曲线…</p>}><EquityChart points={points} /></Suspense>
      <details className="lab-original-settings"><summary>本次运行参数和源码摘要</summary>
        <p>{labMultiEngineLabels[engine]} · 引擎版本 {version ?? '历史未记录'} · {matchingLabel}</p>
        <p>{settings.interval === '15m' ? '15 分钟' : '日线'} · {symbolsLabel(settings)}</p>
        <p>{settings.start ? marketTime(Date.parse(settings.start) / 1_000) : '可用数据起点'} 至 {settings.end ? marketTime(Date.parse(settings.end) / 1_000) : '可用数据终点'}</p>
        <dl className="lab-run-settings">{costs.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{formatPercent(settings[key])}</dd></div>)}</dl>
        {!!Object.keys(settings.parameters ?? {}).length && <pre>{JSON.stringify(settings.parameters, null, 2)}</pre>}
        <code>源码 SHA-256 {job.source_sha256}</code>
        {job.dataset_sha256 && <code>行情 SHA-256 {job.dataset_sha256}</code>}
      </details>
      <details className="lab-original-settings"><summary>成交明细（{result.trades.length}）</summary><LabMultiTradeTable trades={result.trades} /></details>
      <div className="lab-command-actions lab-coverage"><button type="button" onClick={() => downloadResult(job)}>下载回测快照</button></div>
    </>}
  </>
}
