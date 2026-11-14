import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { formatMoney, formatNumber, formatPercent } from '../format'
import { labIndustryLabels, labMembershipBasisLabels, labMultiEngineLabels, multiJobActive, multiJobEngine, multiJobStatus } from '../lab-strategy-types'
import type { LabIndustry, LabMinuteInterval, LabMultiCoverage, LabMultiJob, LabMultiSettings, LabMultiTrade } from '../lab-strategy-types'
import type { LabIndustryCoverage, LabMultiCapabilities } from '../lab-multi-api'
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

export function LabMultiBacktestForm({ value, assets, onChange, coverage, coverageBusy, coverageError, onCoverage, readOnly = false, industries = null, industryError = '', onReloadIndustries, capabilities = null }: {
  value: LabMultiSettings
  assets: Asset[]
  onChange: (patch: Partial<LabMultiSettings>) => void
  coverage: LabMultiCoverage | null
  coverageBusy: boolean
  coverageError: string
  onCoverage: () => void
  readOnly?: boolean
  industries?: LabIndustryCoverage[] | null
  industryError?: string
  onReloadIndustries?: () => void
  capabilities?: LabMultiCapabilities | null
}) {
  const rqalpha = value.engine_id === 'rqalpha'
  const industry = industries?.find(row => row.id === value.industry)
  const configuredPools = Object.entries(labIndustryLabels).filter(([id]) => id !== 'strait' || industries?.some(row => row.id === id))
  const restricted = rqalpha && !!value.industry
  const minute = rqalpha && value.interval !== '1d'
  const acceptsSymbol = (symbol: string) => cnSymbol.test(symbol) && (!rqalpha || !symbol.endsWith('.BJ'))
    && (!restricted || !!industry?.symbols.some(item => item.symbol === symbol && (!minute || item.minute_available !== false)))
  const poolMembers = industry?.symbols.filter(item => !minute || item.minute_available !== false) ?? []
  const invalidPool = rqalpha && (!!value.universe || value.symbols.some(symbol => !acceptsSymbol(symbol)))
  const industryUnavailable = restricted && (!industry?.symbols.length || !!industryError || industries === null)
  const minutePeriods: LabMinuteInterval[] = ['1m', '5m', '15m', '30m', '60m']
  const minuteReady = (period: LabMinuteInterval) => !readOnly && !industryError && capabilities?.available === true && !!industry
    && !!industry.start && !!industry.end
    && !!capabilities?.minute_intervals?.includes(period) && industry.minute_intervals.includes(period)
  const minuteBlocked = value.interval !== '1d' && !minuteReady(value.interval)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Asset[]>([])
  const [searchError, setSearchError] = useState('')
  const [selected, setSelected] = useState('')
  const [parameterText, setParameterText] = useState(JSON.stringify(value.parameters ?? {}, null, 2))
  const [parameterError, setParameterError] = useState('')
  useEffect(() => {
    const text = query.trim()
    if (!text || readOnly || restricted) return
    let active = true
    const timer = window.setTimeout(() => {
      api.searchAssets(text).then(items => {
        if (active) setMatches(items.filter(cnEquity))
      }).catch(() => { if (active) setSearchError('无法搜索行情目录。') })
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query, readOnly, restricted])
  const catalog = useMemo(() => new Map([...assets.filter(cnEquity), ...matches].map(asset => [asset.symbol, asset])), [assets, matches])
  const choices = (restricted ? industry?.symbols ?? [] : [...catalog.values()]).filter(asset => !value.symbols.includes(asset.symbol) && acceptsSymbol(asset.symbol))
  const add = () => {
    const code = (selected || query.trim()).toUpperCase()
    if (readOnly || !acceptsSymbol(code) || value.symbols.includes(code) || value.symbols.length >= 150) return
    onChange({ symbols: [...value.symbols, code] })
    setSelected(''); setQuery(''); setMatches([])
  }
  const candidate = selected || query.trim().toUpperCase()
  const parameterChanged = parameterText !== JSON.stringify(value.parameters ?? {}, null, 2)
  const applyParameters = () => {
    if (readOnly) return
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
    <h2 id="lab-settings-title">回测设置</h2>
    {rqalpha && <>
      <div className="lab-settings-grid"><label>行业股票池<select value={value.industry ?? ''} onChange={event => {
        if (readOnly) return
        const id = (event.target.value || null) as LabIndustry | null
        const next = industries?.find(row => row.id === id)
        onChange({ industry: id, symbols: id ? value.symbols.filter(symbol => next?.symbols.some(item => item.symbol === symbol)) : value.symbols })
        setSelected(''); setQuery(''); setMatches([])
      }}><option value="">不指定行业（日线）</option>{configuredPools.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></div>
      <p className="lab-form-note">RQAlpha Python · 学术非商用。分钟回测使用已准备的行业/题材股票池和 HF 固定历史快照，按各股实际完整日期开放{industries?.some(row => row.id === 'strait') ? '，含海峡两岸研究池' : ''}；日线可选择一只或多只沪深 A 股。</p>
      {industryError ? <div role="alert" className="lab-command-actions"><span>{industryError}</span>{onReloadIndustries && <button type="button" onClick={onReloadIndustries}>重试行业股票池</button>}</div> : restricted && industries === null ? <p role="status">正在读取行业股票池…</p> : null}
      {industry && <div className="lab-industry-coverage">
        <p>{industry.name} · {industry.id === 'strait' ? '研究样本' : '已核验成员'} {industry.symbols.length} 只{industry.as_of ? ` · 名单时点 ${industry.as_of}` : ''}</p>
        {industry.membership_note && <p className="lab-form-note">{industry.membership_note}</p>}
        {!!Object.keys(industry.membership_evidence ?? {}).length && <details className="lab-advanced">
          <summary>查看题材样本依据</summary>
          {industry.membership_selected_on && <p className="lab-form-note">本次样本整理日期：{industry.membership_selected_on}；不代表当时完整成分或无偏选股。</p>}
          {Object.entries(industry.membership_evidence ?? {}).map(([symbol, evidence]) => <div key={symbol}>
            <p className="lab-form-note"><strong>{evidence.name} · {symbol}</strong> · {labMembershipBasisLabels[evidence.basis] ?? evidence.basis} · 公开日期 {evidence.published}</p>
            <code>{evidence.source}</code>
            {evidence.basis === 'annual-report-business-proxy' && <p className="lab-form-note">两岸医疗业务关联不等于福建区域股，也不证明当时行情商的概念标签或龙头身份。</p>}
          </div>)}
        </details>}
        {industry.membership_sha256 && <code>成员版本 SHA-256 {industry.membership_sha256}</code>}
        <p className="lab-form-note">分钟覆盖：{industry.start && industry.end ? `${industry.start} 至 ${industry.end}（成员可用范围外边界）` : '尚未核验完整历史覆盖'}</p>
        {industry.coverage_note && <p className="lab-form-note">{industry.coverage_note}</p>}
        {industry.minute_source && <>
          <p className="lab-form-note">HF 历史快照 · <code>{industry.minute_source.repo_id}</code> · 完整日上限 {industry.minute_source.last_complete_day}</p>
          <code>来源固定版本 {industry.minute_source.revision}</code>
        </>}
        {industry.reason && <p className="lab-form-note">{industry.reason}</p>}
        {!industry.symbols.length && <p role="status">该行业股票池尚未准备，不能用示例或任意股票代替。</p>}
        {industry.minute_source && value.symbols.length > 0 && <div className="lab-form-note" aria-label="已选股票分钟覆盖">
          {value.symbols.map(symbol => {
            const item = industry.symbols.find(row => row.symbol === symbol)
            return <p key={symbol}><strong>{symbol}</strong> · {item?.start && item.end ? `${item.start} 至 ${item.end}` : '暂无已核验分钟范围'}{typeof item?.missing_sessions === 'number' ? ` · 缺口 ${item.missing_sessions} 日` : ''}{item?.minute_reason ? ` · ${item.minute_reason}` : ''}</p>
          })}
          <p>可用日期可能含内部缺口；覆盖预检按所选股票和区间逐日检查，不会自动缩短区间或填充缺根。</p>
        </div>}
        <button type="button" disabled={readOnly || !poolMembers.length || value.symbols.length >= 150} onClick={() => {
          if (!readOnly) onChange({ symbols: [...new Set([...value.symbols, ...poolMembers.map(item => item.symbol)])].slice(0, 150) })
        }}>加入行业股票池（{poolMembers.length}只）</button>
      </div>}
      <p className="lab-form-note">按当前 K 线收盘价撮合（current_bar），不是实盘或持续模拟。最低佣金 5 元，卖出印花税按历史日期计算；结果未经 ZKP 验证。</p>
    </>}
    {invalidPool && <p className="lab-form-note" role="alert">所选股票与所选日期的行业、沪深范围或分钟覆盖不匹配，请核对并手动移除；旧版动态股票池不能作为新 RQAlpha 输入。</p>}
    <div className="lab-stock-pool">
      {value.universe ? <p>{symbolsLabel(value)}</p> : <>
        <div className="lab-settings-grid">
          <label>搜索或输入股票代码<input type="search" value={query} placeholder="例如 600519.SS" onChange={event => { setQuery(event.target.value); setSelected(''); setMatches([]); setSearchError('') }} /></label>
          <label>行情目录<select value={selected} onChange={event => setSelected(event.target.value)}>
            <option value="">选择 A 股</option>
            {choices.map(asset => <option key={asset.symbol} value={asset.symbol}>{asset.symbol} · {asset.name ?? asset.symbol}</option>)}
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
      {minute && <p className="lab-form-note">按完整交易日回测（至少两个交易日）；开始时间不晚于09:30，结束时间不早于15:00。不会自动修改已填时间。</p>}
      <label>开始时间（北京时间）<input type="datetime-local" value={localDate(value.start)} onChange={event => onChange({ start: marketDate(event.target.value) })} /></label>
      <label>结束时间（北京时间）<input type="datetime-local" value={localDate(value.end)} onChange={event => onChange({ end: marketDate(event.target.value) })} /></label>
      <label>行情周期<select value={value.interval} onChange={event => { if (!readOnly) onChange({ interval: event.target.value as LabMultiSettings['interval'] }) }}>
        <option value="1d">日线</option>{minutePeriods.map(period => <option key={period} value={period} disabled={rqalpha ? !minuteReady(period) : true}>{parseInt(period)} 分钟{minuteReady(period) ? '' : '（数据未就绪）'}</option>)}
      </select></label>
      {rqalpha && <p className="lab-form-note">{industry?.reason || capabilities?.minute_reason || '分钟周期须在行业成员、真实数据和原生执行均核验通过后开放；不能从15分钟或日线补造1分钟。'}</p>}
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
      <button type="button" disabled={readOnly || coverageBusy || invalidPool || industryUnavailable || minuteBlocked || !value.universe && value.symbols.length < 1} onClick={onCoverage}>{coverageBusy ? '检查中…' : '检查行情覆盖'}</button>
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
