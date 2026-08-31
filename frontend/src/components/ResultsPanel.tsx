import { lazy, Suspense, useState } from 'react'
import { AlertTriangle, BarChart3, ChevronDown, ChevronUp, ListOrdered, Maximize2, Minimize2, ShieldAlert } from 'lucide-react'
import { formatDate, formatMoney, formatNumber, formatPercent } from '../format'
import type { ResultsPanelMode } from '../storage'
import type { BacktestResult, PortfolioResult } from '../types'

const EquityChart = lazy(() =>
  import('./EquityChart').then((module) => ({ default: module.EquityChart })),
)

interface Props {
  result: BacktestResult | PortfolioResult | null
  loading: boolean
  panelMode: ResultsPanelMode
  onPanelMode: (mode: ResultsPanelMode) => void
  controls?: boolean
}

const metricDefinitions = [
  ['total_return', '总收益', 'percent'],
  ['cagr', '年化收益', 'percent'],
  ['benchmark_return', '基准收益', 'percent'],
  ['max_drawdown', '最大回撤', 'percent'],
  ['sharpe', 'Sharpe', 'number'],
  ['sortino', 'Sortino', 'number'],
  ['annual_volatility', '年化波动', 'percent'],
  ['win_rate', '胜率', 'percent'],
] as const

export function ResultsPanel({ result, loading, panelMode, onPanelMode, controls = true }: Props) {
  const [tab, setTab] = useState<'summary' | 'trades' | 'risk' | 'warnings'>('summary')
  const metrics = result?.metrics ?? {}
  return (
    <section className={`results-panel panel-${panelMode}`} aria-label="回测结果">
      <div className="result-tabs" role="tablist" aria-label="回测结果分类">
        <button role="tab" aria-selected={tab === 'summary'} className={tab === 'summary' ? 'is-active' : ''} onClick={() => setTab('summary')}><BarChart3 size={14} />概览</button>
        <button role="tab" aria-selected={tab === 'trades'} className={tab === 'trades' ? 'is-active' : ''} onClick={() => setTab('trades')}><ListOrdered size={14} />交易记录 <em>{result?.trades.length ?? 0}</em></button>
        <button role="tab" aria-selected={tab === 'risk'} className={tab === 'risk' ? 'is-active' : ''} onClick={() => setTab('risk')}><ShieldAlert size={14} />风险分析</button>
        <button role="tab" aria-selected={tab === 'warnings'} className={tab === 'warnings' ? 'is-active' : ''} onClick={() => setTab('warnings')}><AlertTriangle size={14} />可信度 <em>{result?.warnings.length ?? 0}</em></button>
        {controls ? <span className="result-panel-actions">
          {panelMode === 'maximized' ? <button aria-label="还原回测面板" onClick={() => onPanelMode('normal')} title="还原回测面板"><Minimize2 size={13} /></button> : <button aria-label="最大化回测面板" onClick={() => onPanelMode('maximized')} title="最大化回测面板"><Maximize2 size={13} /></button>}
          {panelMode === 'collapsed' ? <button aria-label="展开回测面板" onClick={() => onPanelMode('normal')} title="展开回测面板"><ChevronUp size={14} /></button> : <button aria-label="收起回测面板" onClick={() => onPanelMode('collapsed')} title="收起回测面板"><ChevronDown size={14} /></button>}
        </span> : null}
      </div>
      <div className="result-content" role="tabpanel">
        {loading ? <div className="result-loading" role="status" aria-live="polite"><span className="pulse-line" /><span>正在标准化行情、生成信号并逐笔撮合…</span></div> : null}
        {!loading && !result ? <div className="result-empty"><BarChart3 size={18} /><span>运行回测后，这里会显示收益、风险与逐笔交易。</span></div> : null}
        {!loading && result && tab === 'summary' ? (
          <div className="summary-grid">
            <div className="metrics-grid">
              {metricDefinitions.map(([key, label, kind]) => {
                const value = metrics[key]
                const display = kind === 'percent' ? formatPercent(value) : formatNumber(value)
                return <div className="metric-cell" key={key}><span>{label}</span><strong className={key === 'total_return' && (value ?? 0) < 0 ? 'negative' : ''}>{display}</strong></div>
              })}
            </div>
            <Suspense fallback={<div className="equity-chart chart-loading">加载权益曲线…</div>}>
              <EquityChart points={result.equity} />
            </Suspense>
          </div>
        ) : null}
        {!loading && result && tab === 'trades' ? (
          <div className="table-scroll">
            <table><thead><tr><th>时间</th><th>方向</th><th>触发原因</th><th>成交价</th><th>数量</th><th>成交额</th><th>费用</th><th>已实现盈亏</th></tr></thead>
              <tbody>{result.trades.map((trade) => <tr key={trade.id}><td>{formatDate(trade.time)}</td><td><span className={`side-tag ${trade.side}`}>{trade.side === 'buy' ? '买入' : '卖出'}</span></td><td title={trade.reason}>{trade.reason}</td><td>{formatNumber(trade.price, 4)}</td><td>{formatNumber(trade.quantity, 6)}</td><td>{formatMoney(trade.notional, 'CNY')}</td><td>{formatMoney(trade.fee, 'CNY')}</td><td className={(trade.realized_pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{trade.realized_pnl == null ? '—' : formatMoney(trade.realized_pnl, 'CNY')}</td></tr>)}</tbody>
            </table>
          </div>
        ) : null}
        {!loading && result && tab === 'risk' ? (
          <div className="risk-grid">
            {Object.entries(metrics).filter(([key]) => ['var_95', 'cvar_95', 'calmar', 'information_ratio', 'beta', 'profit_factor', 'expectancy', 'turnover', 'average_exposure', 'return_t_stat', 'return_p_value', 'fees_paid'].includes(key)).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{key.includes('var') || key.includes('exposure') ? formatPercent(value) : formatNumber(value)}</strong></div>)}
            {'risk_contribution' in result ? <div className="risk-contribution"><span>风险贡献</span>{Object.entries(result.risk_contribution).map(([symbol, value]) => <p key={symbol}><b>{symbol}</b><i style={{ width: `${Math.max(0, value * 100)}%` }} /><em>{formatPercent(value)}</em></p>)}</div> : null}
          </div>
        ) : null}
        {!loading && result && tab === 'warnings' ? <div className="warning-list">{result.warnings.map((warning, index) => <div key={`${warning}-${index}`}><AlertTriangle size={15} /><span>{warning}</span></div>)}</div> : null}
      </div>
    </section>
  )
}
