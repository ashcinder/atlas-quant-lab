import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, ChevronDown, ChevronUp, Pause, Play, Square } from 'lucide-react'
import { formatMoney, formatNumber, formatPercent } from '../format'
import { labMultiRequest } from '../lab-multi-api'
import type { LabMultiSimulation, LabMultiTrade } from '../lab-strategy-types'
import type { StrategyRelease } from '../types'

const statusLabels: Record<LabMultiSimulation['status'], string> = { active: '运行中', waiting: '等待行情或恢复', paused: '已暂停', stopped: '已停止' }
const marketTime = (time: number) => new Date(time * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })

export function MultiSimulationFields({ release, cash, commission, slippage, onCash, onCommission, onSlippage }: {
  release: StrategyRelease
  cash: string
  commission: string
  slippage: string
  onCash: (value: string) => void
  onCommission: (value: string) => void
  onSlippage: (value: string) => void
}) {
  return <>
    <p className="trade-probe-note">A 股平台模拟 · 服务端持续运行 · 未经 ZKP 验证</p>
    <p className="trade-probe-note">运行周期 {release.interval === '15m' ? '15 分钟' : '日线'} · {release.symbols?.length ? release.symbols.join('、') : release.universe || '按版本的行业名单'}</p>
    <label>共享资金（元）<input required type="number" min="0.01" step="0.01" value={cash} onChange={event => onCash(event.target.value)} /></label>
    <label>手续费率<input required type="number" min="0" max="0.1" step="any" value={commission} onChange={event => onCommission(event.target.value)} /></label>
    <label>滑点率<input required type="number" min="0" max="0.1" step="any" value={slippage} onChange={event => onSlippage(event.target.value)} /></label>
  </>
}

export function LabMultiSimulationCard({ ownerId, run, focused, busy, onAction }: {
  ownerId: string
  run: LabMultiSimulation
  focused: boolean
  busy: boolean
  onAction: (run: LabMultiSimulation, action: 'pause' | 'resume' | 'stop') => void
}) {
  const [opened, setOpened] = useState(focused)
  const [trades, setTrades] = useState<LabMultiTrade[] | null>(null)
  const [tradeError, setTradeError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const card = useRef<HTMLElement>(null)
  const expanded = focused || opened
  const latest = run.latest
  const tradeVersion = latest?.time
  useEffect(() => {
    if (!focused) return
    const timer = window.setTimeout(() => card.current?.scrollIntoView?.({ block: 'center' }), 0)
    return () => window.clearTimeout(timer)
  }, [focused])
  useEffect(() => {
    if (!expanded) return
    const controller = new AbortController()
    labMultiRequest<LabMultiTrade[]>(ownerId, `runs/${encodeURIComponent(run.id)}/trades`, { signal: controller.signal }).then(rows => {
      if (!controller.signal.aborted) { setTrades(rows); setTradeError('') }
    }).catch(reason => {
      if (!controller.signal.aborted) setTradeError(reason instanceof Error ? reason.message : '无法读取成交明细')
    })
    return () => controller.abort()
  }, [attempt, expanded, ownerId, run.id, tradeVersion])

  const valuationText = !latest ? '尚无估值' : run.valuation_complete === false ? '最近一次完整估值' : '已记录估值'
  return <article id={run.id} ref={card} className={expanded ? 'is-expanded' : undefined}>
    <p className="run-valuation-status">{valuationText}{latest && ` · ${marketTime(latest.time)}`} · 平台模拟</p>
    <div className="trade-run-line">
      <span className="trade-run-symbol" aria-hidden="true">A 股</span>
      <div className="trade-run-identity"><h3>{run.name}</h3><p>A 股多标的 · {run.settings.interval === '15m' ? '15 分钟' : '日线'} · 共享人民币账户</p></div>
      <span className={`trade-run-status is-${run.status === 'waiting' ? 'error' : run.status}`}>{statusLabels[run.status]}</span>
      <div className="trade-run-valuation"><small>{latest ? '策略净值' : '初始资金'}</small><strong>{formatMoney(latest?.equity ?? run.settings.initial_capital)}</strong></div>
      <div className="trade-run-return"><small>收益率</small><strong>{latest && run.valuation_complete !== false ? formatPercent(latest.equity / run.settings.initial_capital - 1) : '待完整估值'}</strong></div>
      <button type="button" className="trade-detail-toggle" aria-expanded={expanded} aria-controls={`multi-${run.id}`} onClick={() => setOpened(!opened)} disabled={focused}>
        {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}<span>{expanded ? '收起详情' : '运行详情'}</span>
      </button>
    </div>
    {run.error && <p className="trade-run-alert" role="alert">{run.error}</p>}
    {expanded && <div id={`multi-${run.id}`}>
      <div className="trade-run-toolbar"><span>服务端持续运行 · 暂停或停止保留持仓</span>
        {(run.status === 'active' || run.status === 'waiting') && <button disabled={busy} type="button" onClick={() => onAction(run, 'pause')}><Pause size={14} />暂停</button>}
        {run.status === 'paused' && <button disabled={busy} type="button" onClick={() => onAction(run, 'resume')}><Play size={14} />恢复</button>}
        {run.status !== 'stopped' && <button disabled={busy} type="button" onClick={() => onAction(run, 'stop')}><Square size={14} />停止</button>}
        <a href={`#/journal/trading?run=${encodeURIComponent(run.id)}`}>成交与账本<ArrowUpRight size={14} /></a>
      </div>
      <div className="trade-detail-layout">
        <section><h5>当前持仓</h5><p>共享现金 {formatMoney(latest?.cash ?? run.settings.initial_capital)}</p>
          {latest?.positions.length ? <div className="trade-table"><table><thead><tr><th>股票</th><th>持仓／可卖</th><th>市值</th><th>仓位</th></tr></thead>
            <tbody>{latest.positions.map(position => <tr key={position.symbol}><th scope="row">{position.symbol}</th>
              <td>{formatNumber(position.quantity, 0)} / {formatNumber(position.sellable, 0)}</td><td>{formatMoney(position.market_value)}</td><td>{formatPercent(position.weight)}</td></tr>)}</tbody>
          </table></div> : <p>暂无持仓。</p>}
        </section>
        <section><h5>成交记录</h5>{tradeError ? <p role="alert">{tradeError} <button type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>
          : trades === null ? <p role="status">正在读取成交记录…</p>
          : trades.length ? <div className="trade-table"><table><thead><tr><th>时间</th><th>股票</th><th>方向／股数</th><th>价格／费用</th></tr></thead>
            <tbody>{trades.map((trade, index) => <tr key={`${trade.time}:${trade.symbol}:${index}`}>
              <td>{marketTime(trade.time)}</td><th scope="row">{trade.symbol}</th>
              <td>{trade.side === 'buy' ? '买入' : '卖出'} <small>{formatNumber(trade.quantity, 0)} 股</small></td>
              <td>{formatMoney(trade.price)} <small>费用 {formatMoney(trade.fee)}</small></td>
            </tr>)}</tbody>
          </table></div> : <p>暂无成交。</p>}
        </section>
      </div>
    </div>}
  </article>
}
