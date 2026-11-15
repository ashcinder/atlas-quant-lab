import { useEffect, useId, useRef, useState } from 'react'
import { ArrowRight, CandlestickChart, Check, ChevronDown, Cpu, Download, FileCheck2, LoaderCircle, ShieldCheck, Upload } from 'lucide-react'
import './browser-proof-panel.css'
import { DEFAULT_PROFILE, INITIAL_EQUITY, datasetHash, marketInput, MAX_BUNDLE_BYTES, parseProof, PROOF_BAR_COUNTS, proofOutput } from '../browser-proof/protocol'
import type { BrowserProof, MarketInput, ProofJob, ProofProfile } from '../browser-proof/protocol'
import type { MarketQuery } from '../compute/market'

function execute(job: ProofJob, signal: AbortSignal): Promise<BrowserProof> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted()
    const worker = new Worker(new URL('../browser-proof/worker.ts', import.meta.url), { type: 'module' })
    const close = () => {
      worker.terminate()
      signal.removeEventListener('abort', abort)
    }
    const abort = () => { close(); reject(signal.reason) }
    signal.addEventListener('abort', abort, { once: true })
    worker.onmessage = ({ data }: MessageEvent<{ bundle?: BrowserProof; error?: string }>) => {
      close()
      if (data.bundle) resolve(data.bundle)
      else reject(new Error(data.error || '浏览器证明运行失败。'))
    }
    worker.onerror = event => { close(); reject(new Error(event.message || '证明 Worker 启动失败。')) }
    worker.onmessageerror = () => { close(); reject(new Error('浏览器无法读取证明 Worker 的返回结果。')) }
    worker.postMessage(job)
  })
}

function download(bundle: BrowserProof) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `atlas-browser-sma-${PROOF_BAR_COUNTS[bundle.profile]}-proof.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

type Phase = 'market' | 'prove' | 'verify'
const phaseText = {
  market: '正在准备已收盘 K 线…',
  prove: '正在本机生成并验证证明…',
  verify: '正在复验导入的证明…',
}
const profiles = Object.entries(PROOF_BAR_COUNTS) as [ProofProfile, number][]

const date = (time: number) => new Date(time * 1000).toISOString().replace('T', ' ').slice(0, 16)

async function frozenMarket(input: MarketQuery | { datasetId: string; end: number }, profile: ProofProfile, signal: AbortSignal) {
  const { browserProofCandles } = await import('../compute/client')
  const { bars, manifest } = await browserProofCandles(input, PROOF_BAR_COUNTS[profile], signal)
  const micros = (value: number) => Math.round(value * 1_000_000)
  const dataset = { dataset_id: manifest.dataset_id, source: manifest.source, symbol: manifest.asset.symbol,
    adjustment: manifest.adjustment, interval: manifest.interval, bars: bars.map(bar => ({
      time: bar.time, open_micros: micros(bar.open), high_micros: micros(bar.high), low_micros: micros(bar.low),
      close_micros: micros(bar.close), volume_micros: micros(bar.volume),
    })) }
  const hash = await datasetHash(dataset)
  signal.throwIfAborted()
  return marketInput(manifest.dataset_id, hash, dataset, profile)
}

export function BrowserProofPanel({ query, onSettings }: {
  query: MarketQuery | null
  onSettings: () => void
}) {
  const [profile, setProfile] = useState<ProofProfile>(DEFAULT_PROFILE)
  const [fast, setFast] = useState('3')
  const [slow, setSlow] = useState('8')
  const [market, setMarket] = useState<MarketInput | null>(null)
  const [verified, setVerified] = useState<{ bundle: BrowserProof; market: MarketInput } | null>(null)
  const [busy, setBusy] = useState<Phase | null>(null)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const headingId = useId()
  const countGroup = useId()
  useEffect(() => () => active.current?.abort(), [])

  async function run(phase: Phase, task: (signal: AbortSignal) => Promise<void>) {
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setError('')
    setBusy(phase)
    try { await task(controller.signal) }
    catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '操作失败。') }
    finally {
      if (active.current === controller) {
        active.current = null
        if (!controller.signal.aborted) setBusy(null)
      }
    }
  }

  function cancel() {
    active.current?.abort()
    active.current = null
    setBusy(null)
  }

  async function prepareMarket(signal: AbortSignal) {
    if (!query) throw new Error('请先在回测设置中选择标的。')
    if (query.data_source === 'demo') throw new Error('请在回测设置中切换到真实行情来源。')
    const input = await frozenMarket(query, profile, signal)
    setMarket(input)
    return input
  }

  function prepare() {
    void run('market', async signal => { await prepareMarket(signal) })
  }

  function prove() {
    const fastPeriod = Number(fast)
    const slowPeriod = Number(slow)
    if (!Number.isInteger(fastPeriod) || !Number.isInteger(slowPeriod) || fastPeriod < 2 || slowPeriod > 16 || fastPeriod >= slowPeriod) {
      setError('均线参数需满足 2 ≤ 快线 < 慢线 ≤ 16。')
      return
    }
    const prepared = market?.profile === profile ? market : null
    setVerified(null)
    void run(prepared ? 'prove' : 'market', async signal => {
      const input = prepared ?? await prepareMarket(signal)
      setBusy('prove')
      const bundle = await execute({ mode: 'prove', market: input, fast: fastPeriod, slow: slowPeriod }, signal)
      setVerified({ bundle, market: input })
    })
  }

  function verify(file: File) {
    setVerified(null)
    void run('verify', async signal => {
      if (file.size > MAX_BUNDLE_BYTES) throw new Error('证明文件过大。')
      const bundle = parseProof(JSON.parse(await file.text()))
      const input = await frozenMarket({ datasetId: bundle.dataset_id, end: bundle.window_end }, bundle.profile, signal)
      await execute({ mode: 'verify', market: input, bundle }, signal)
      setVerified({ bundle, market: input })
    })
  }

  const output = verified && proofOutput(verified.bundle)
  const stages = [
    { label: '准备行情', done: !!market || !!verified, running: busy === 'market' },
    { label: '生成或导入', done: !!verified, running: busy === 'prove' },
    { label: '验证回执', done: !!verified, running: busy === 'verify' },
  ]

  return <section className="browser-proof" aria-labelledby={headingId}>
    <header className="browser-proof-header">
      <span className="browser-proof-emblem"><ShieldCheck size={27} aria-hidden="true" /></span>
      <div className="browser-proof-title">
        <h2 id={headingId}>在浏览器生成 ZKP</h2>
        <p>为内置双均线模型证明期末权益。当前编辑器源码和三框架回测结果不属于此证明的范围。</p>
      </div>
    </header>

    <div className="browser-proof-body">
      <form className="browser-proof-form" noValidate onSubmit={event => { event.preventDefault(); prove() }}>
        <fieldset className="browser-proof-controls" disabled={!!busy}>
          <legend>证明 K 线数量</legend>
          <div className="browser-proof-counts">
            {profiles.map(([id, count]) => <label key={id}>
              <input type="radio" name={countGroup} value={id} checked={profile === id} onChange={() => {
                setProfile(id)
                setMarket(null)
                setVerified(null)
                setError('')
              }} />
              <span><strong>{count}</strong> 根</span>
            </label>)}
          </div>
          <div className="browser-proof-periods">
            <label>快线周期<input type="number" min="2" max="15" value={fast} onChange={event => { setFast(event.target.value); setVerified(null); setError('') }} /></label>
            <label>慢线周期<input type="number" min="3" max="16" value={slow} onChange={event => { setSlow(event.target.value); setVerified(null); setError('') }} /></label>
          </div>
          <p className="browser-proof-note">2 ≤ 快线 &lt; 慢线 ≤ 16</p>
        </fieldset>

        <div className="browser-proof-window">
          <div>
            <strong>行情区间</strong>
            <span>{market ? `${date(market.start)} 至 ${date(market.end)} UTC` : `最近 ${PROOF_BAR_COUNTS[profile]} 根已收盘 K 线`}</span>
            <span className="browser-proof-market-tag"><CandlestickChart size={14} aria-hidden="true" />{query ? `${query.symbol} · ${query.interval}` : '未选标的'}</span>
          </div>
          {query && query.data_source !== 'demo' ? <button className="browser-proof-text-button" type="button" disabled={!!busy} onClick={prepare}>{market ? '刷新行情' : '预览行情'}</button>
            : <button className="browser-proof-text-button" type="button" onClick={onSettings}>选择标的</button>}
        </div>

        <div className="browser-proof-actions">
          <button className="lab-primary browser-proof-generate" type="submit" disabled={!!busy || !query || query.data_source === 'demo'}>
            {busy ? <LoaderCircle size={18} className="spin" aria-hidden="true" /> : <ShieldCheck size={18} aria-hidden="true" />}
            {busy === 'market' ? '准备行情中' : busy === 'prove' ? '生成证明中' : busy === 'verify' ? '验证证明中' : '生成本地证明'}
            {!busy ? <ArrowRight size={17} aria-hidden="true" /> : null}
          </button>
          {busy ? <button className="browser-proof-secondary" type="button" onClick={cancel}>取消</button>
            : <button className="browser-proof-secondary" type="button" onClick={() => fileInput.current?.click()}>
              <Upload size={16} aria-hidden="true" />导入并验证
            </button>}
          <input ref={fileInput} hidden type="file" aria-label="导入本地证明并验证" accept=".json,application/json" disabled={!!busy} onChange={event => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) verify(file)
          }} />
        </div>
        {error ? <div className="browser-proof-recovery">
          <p className="browser-proof-error" role="alert">{error}</p>
          <button type="button" onClick={onSettings}>调整标的或行情源</button>
        </div> : null}
      </form>

      <aside className="browser-proof-receipt" aria-label="证明回执">
        <header><FileCheck2 size={17} aria-hidden="true" /><h3>证明回执</h3></header>
        <ol className="browser-proof-progress" aria-label="证明进度">
          {stages.map(stage => <li key={stage.label} data-state={stage.done ? 'done' : stage.running ? 'running' : 'pending'}>
            {stage.done ? <Check size={13} aria-hidden="true" /> : <i aria-hidden="true" />}{stage.label}
          </li>)}
        </ol>
        {busy ? <p className="browser-proof-status" role="status">{phaseText[busy]}</p> : null}
        {verified && output ? <div className="browser-proof-result">
          <p className="browser-proof-verified" role="status"><Check size={15} aria-hidden="true" />浏览器密码学验证通过</p>
          <dl>
            <div><dt>期末权益</dt><dd>{output.equity.toLocaleString(undefined, { maximumFractionDigits: 6 })}</dd></div>
            <div><dt>收益率</dt><dd>{((output.equity / INITIAL_EQUITY - 1) * 100).toFixed(4)}%</dd></div>
          </dl>
          <p className="browser-proof-note">{verified.market.symbol} · {verified.market.interval} · {PROOF_BAR_COUNTS[verified.bundle.profile]} 根 K 线</p>
          <p className="browser-proof-note">{date(verified.market.start)} 至 {date(verified.market.end)} UTC · {verified.market.source}</p>
          <details className="browser-proof-hash"><summary>市场数据哈希与快照</summary><code>{verified.market.hash}</code><br /><code>{verified.market.datasetId}</code></details>
          <button className="browser-proof-secondary" type="button" onClick={() => download(verified.bundle)}><Download size={16} aria-hidden="true" />下载证明</button>
        </div> : !busy ? <p className="browser-proof-status">生成或导入证明后，在这里查看验证结果。</p> : null}
      </aside>
    </div>

    <footer className="browser-proof-footer">
      <p><Cpu size={15} aria-hidden="true" />在本机生成和验证。快慢线与随机盐留在浏览器。</p>
      <details>
        <summary>证明范围与撮合参数 <ChevronDown size={14} aria-hidden="true" /></summary>
        <p>双均线信号在收盘后确认，下一根开盘成交。初始资金 {INITIAL_EQUITY.toLocaleString()}，目标仓位 95%，手续费 0.10%，滑点 0.05%。公开行情由平台登记，首次运行会下载公开证明参数。</p>
      </details>
    </footer>
  </section>
}
