import { ArrowDownToLine, ArrowRight, BarChart3 } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { formatMoney, formatNumber, formatPercent } from '../format'
import { labOwnerHeaders } from '../lab-strategy-types'
import { request } from '../request'
import './sector-backtest.css'

const EquityChart = lazy(() => import('./EquityChart').then(module => ({ default: module.EquityChart })))
const endpoint = '/lab-sector-backtests'

interface Sector {
  id: string
  name: string
  available: boolean
}

interface Trade {
  date: string
  time: string
  symbol: string
  trigger: string
  signal_date: string
  touch_time: string
  side: 'buy' | 'sell' | 'adjust'
  shares: number
  price: number | null
  fee: number
}

interface Replay {
  id?: string
  created_at?: string
  industry: string
  start: string
  end: string
  starting_cash: number
  pool_limit: number
  snapshot_symbols: string[]
  traded_symbols: string[]
  metrics: { net_return: number; equity: number; max_drawdown: number; buys: number; sells: number; open: number }
  equity: { date: string; equity: number }[]
  trades: Trade[]
}

type ReplaySummary = Pick<Replay, 'industry' | 'start' | 'end' | 'metrics'> & { id: string; created_at: string }

const sides = { buy: '买入', sell: '卖出', adjust: '除权调整' }
const explainError = (reason: unknown) => reason instanceof Error ? reason.message : '无法运行行业回测，请重试。'

export function SectorBacktest({ ownerId }: { ownerId: string }) {
  const [opened, setOpened] = useState(false)
  const [sectors, setSectors] = useState<Sector[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState<ReplaySummary[]>([])
  const [historyError, setHistoryError] = useState('')
  const [historyBusy, setHistoryBusy] = useState(false)
  const [result, setResult] = useState<Replay | null>(null)
  const pending = useRef<AbortController | null>(null)
  const historyRequest = useRef<AbortController | null>(null)

  useEffect(() => () => { pending.current?.abort(); historyRequest.current?.abort() }, [])

  const loadHistory = async () => {
    if (historyRequest.current) return
    const controller = new AbortController()
    historyRequest.current = controller
    setHistoryBusy(true); setHistoryError('')
    try {
      const rows = await request<ReplaySummary[]>(`${endpoint}/history`, { headers: labOwnerHeaders(ownerId), signal: controller.signal })
      if (!controller.signal.aborted && Array.isArray(rows)) setHistory(rows)
    } catch (reason) {
      if (!controller.signal.aborted) setHistoryError(explainError(reason))
    } finally {
      if (historyRequest.current === controller) historyRequest.current = null
      if (!controller.signal.aborted) setHistoryBusy(false)
    }
  }

  const openHistory = async (row: ReplaySummary) => {
    if (pending.current) return
    const controller = new AbortController()
    pending.current = controller
    setLoading(true); setError('')
    try {
      const replay = await request<Replay>(`${endpoint}/history/${encodeURIComponent(row.id)}`, { headers: labOwnerHeaders(ownerId), signal: controller.signal })
      if (!controller.signal.aborted) { setSelected(replay.industry); setResult(replay) }
    } catch (reason) {
      if (!controller.signal.aborted) setError(explainError(reason))
    } finally {
      if (pending.current === controller) pending.current = null
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  const load = async () => {
    if (pending.current) return
    const controller = new AbortController()
    pending.current = controller
    setLoading(true)
    setError('')
    try {
      const options = await request<Sector[]>(endpoint, { headers: labOwnerHeaders(ownerId), signal: controller.signal })
      if (controller.signal.aborted) return
      setSectors(options)
      setSelected(options.find(item => item.available)?.id ?? options[0]?.id ?? '')
    } catch (reason) {
      if (!controller.signal.aborted) setError(explainError(reason))
    } finally {
      pending.current = null
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  const run = async () => {
    if (pending.current || !sectors.some(item => item.id === selected && item.available)) return
    const controller = new AbortController()
    pending.current = controller
    setRunning(true)
    setResult(null)
    setError('')
    try {
      const replay = await request<Replay>(endpoint, {
        method: 'POST', headers: labOwnerHeaders(ownerId), body: JSON.stringify({ industry: selected }),
        signal: controller.signal,
      })
      if (!controller.signal.aborted) { setResult(replay); void loadHistory() }
    } catch (reason) {
      if (!controller.signal.aborted) setError(explainError(reason))
    } finally {
      pending.current = null
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const points = useMemo(() => {
    if (!result) return []
    let peak = result.starting_cash
    return result.equity.map(point => {
      peak = Math.max(peak, point.equity)
      return { time: Date.parse(point.date) / 1000, equity: point.equity, drawdown: point.equity / peak - 1 }
    })
  }, [result])

  const download = () => {
    if (!result) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `atlas-${result.industry}-${result.end}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <section className="sector-backtest" aria-labelledby="sector-backtest-heading">
    <header>
      <div>
        <h2 id="sector-backtest-heading"><BarChart3 size={17} aria-hidden="true" />历史基准回放</h2>
        <p>四行业涨停联动 · 15 分钟行情 · 同行业共享模拟账户</p>
      </div>
      <div className="lab-command-actions">
        <button type="button" aria-expanded={opened} aria-controls="sector-backtest-controls" disabled={running} onClick={() => {
          if (!opened) {
            if (!sectors.length) void load()
            void loadHistory()
          }
          setOpened(!opened)
        }}>{opened ? '收起历史基准' : '打开历史基准'}{opened ? null : <ArrowRight size={15} aria-hidden="true" />}</button>
      </div>
    </header>
    <div id="sector-backtest-controls" hidden={!opened} className="sector-backtest-body">
      <div className="sector-backtest-setup">
        <div className="lab-settings-grid">
          <label>行业策略<select disabled={running || loading || sectors.length === 0} value={selected} onChange={event => {
            setSelected(event.target.value)
            setResult(null)
            setError('')
          }}>
            {sectors.map(item => <option key={item.id} value={item.id}>{item.name}{item.available ? '' : '（待安装）'}</option>)}
          </select></label>
        </div>
        <div className="lab-command-actions">
          <button type="button" className="lab-primary" disabled={running || loading || !sectors.some(item => item.id === selected && item.available)}
            onClick={() => void run()}>{running ? '正在回放…' : '运行行业基准'}</button>
          {!loading && !running && !sectors.some(item => item.available) ? <button type="button" onClick={() => void load()}>重新检查环境</button> : null}
        </div>
      </div>
      <p className="sector-backtest-note">每次回放一个行业。使用固定股票池和冻结行情，参数在同一历史区间选出。</p>
      {loading || running ? <p role="status">{loading ? '正在读取可用策略…' : '正在用历史行情逐月拟合并回放…'}</p> : null}
      {!loading && sectors.length > 0 && !sectors.find(item => item.id === selected)?.available
        ? <p role="status">该行业的回测环境待安装。请按项目运行说明配置策略包和 Python 依赖。</p> : null}
      {error ? <p className="lab-error" role="alert">{error}</p> : null}
      <details className="lab-history"><summary>历史基准回放记录（{history.length}）</summary>
        {historyBusy ? <p role="status">正在读取回放记录…</p> : historyError ? <div role="alert" className="lab-error">{historyError}<button type="button" onClick={() => void loadHistory()}>重试</button></div> : history.length ? <div className="lab-table-scroll"><table className="lab-table lab-history-table">
          <thead><tr><th scope="col">行业</th><th scope="col">运行时间</th><th scope="col">收益</th><th scope="col">操作</th></tr></thead>
          <tbody>{history.map(row => <tr key={row.id}>
            <th scope="row">{sectors.find(item => item.id === row.industry)?.name ?? row.industry}</th>
            <td>{new Date(row.created_at).toLocaleString('zh-CN')}</td><td>{formatPercent(row.metrics.net_return)}</td>
            <td><button type="button" disabled={running || loading} onClick={() => void openHistory(row)}>查看基准</button></td>
          </tr>)}</tbody>
        </table></div> : <p>完成的回放会出现在这里。</p>}
      </details>
      {result ? <section className="sector-backtest-result" aria-labelledby="sector-backtest-result-heading">
        <header>
          <div><h2 id="sector-backtest-result-heading">{sectors.find(item => item.id === result.industry)?.name ?? result.industry} · 基准回放结果</h2>
            <p>{result.start} 至 {result.end} · {result.equity.length} 个交易日 · BaoStock 冻结行情</p></div>
          <div className="lab-command-actions"><button type="button" onClick={download}><ArrowDownToLine size={15} aria-hidden="true" />下载回测明细</button></div>
        </header>
        <dl className="sector-backtest-metrics">
          <div><dt>扣费后收益</dt><dd>{formatPercent(result.metrics.net_return)}</dd></div>
          <div><dt>最大回撤</dt><dd>{(result.metrics.max_drawdown * 100).toFixed(2)}%</dd></div>
          <div><dt>期末权益</dt><dd>{formatMoney(result.metrics.equity)}</dd></div>
          <div><dt>已平仓／期末持仓</dt><dd>{result.metrics.sells}／{result.metrics.open}</dd></div>
        </dl>
        <p className="sector-backtest-note">初始资金 {formatMoney(result.starting_cash)} · 股票池上限 {result.pool_limit} 只 · 快照覆盖 {result.snapshot_symbols.length} 只候选 · {result.traded_symbols.length} 只实际成交</p>
        <Suspense fallback={<p role="status">正在加载权益曲线…</p>}><EquityChart points={points} /></Suspense>
        <details>
          <summary>逐笔记录（{result.trades.length} 行）</summary>
          <div className="lab-table-scroll sector-backtest-trades">
            <table className="lab-table">
              <thead><tr><th scope="col">成交时间</th><th scope="col">股票</th><th scope="col">方向</th><th scope="col">股数</th><th scope="col">成交价</th><th scope="col">费用</th><th scope="col">触板股／时间</th><th scope="col">预警日</th></tr></thead>
              <tbody>{result.trades.map((trade, i) => <tr key={i}>
                <td>{trade.date} {trade.time}</td><th scope="row">{trade.symbol}</th><td>{sides[trade.side]}</td>
                <td>{formatNumber(trade.shares, 4)}</td><td>{formatNumber(trade.price, 4)}</td><td>{formatNumber(trade.fee)}</td>
                <td>{trade.trigger}／{trade.touch_time}</td><td>{trade.signal_date}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </details>
      </section> : null}
    </div>
  </section>
}
