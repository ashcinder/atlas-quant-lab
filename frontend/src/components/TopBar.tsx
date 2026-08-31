import { useState } from 'react'
import { BarChart3, Bell, CandlestickChart, Clock3, FlaskConical, Gavel, History, Layers3, Play, Settings2 } from 'lucide-react'
import type { Adjustment, Asset, BaseCurrency, DataSource, Interval } from '../types'

interface Props {
  asset: Asset | null
  interval: Interval
  source: DataSource
  chartType: 'candles' | 'line'
  mode: 'single' | 'portfolio' | 'research' | 'quantjudge'
  loading: boolean
  baseCurrency: BaseCurrency
  adjustment: Adjustment
  onInterval: (interval: Interval) => void
  onSource: (source: DataSource) => void
  onChartType: (type: 'candles' | 'line') => void
  onMode: (mode: 'single' | 'portfolio' | 'research' | 'quantjudge') => void
  onHistory: () => void
  onRun: () => void
  onBaseCurrency: (currency: BaseCurrency) => void
  onAdjustment: (adjustment: Adjustment) => void
  onAlerts: () => void
  unreadAlerts: number
}

const intervals: Array<{ value: Interval; label: string }> = [
  { value: '15m', label: '15分' },
  { value: '1h', label: '1时' },
  { value: '4h', label: '4时' },
  { value: '1d', label: '日' },
  { value: '1wk', label: '周' },
]

export function TopBar(props: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  return (
    <header className="topbar">
      <div className="brand-block">
        <span className="brand-mark">A</span>
        <span><strong>Atlas</strong><small>Quant Lab</small></span>
      </div>
      <div className="symbol-block">
        <strong>{props.mode === 'portfolio' ? '多资产组合' : props.mode === 'research' ? '策略实验室' : props.mode === 'quantjudge' ? 'QuantJudge' : (props.asset?.symbol ?? '—')}</strong>
        <span>{props.mode === 'portfolio' ? '组合策略实验室' : props.mode === 'research' ? `${props.asset?.symbol ?? '当前标的'} · 开发 / 验证` : props.mode === 'quantjudge' ? '可验证 Agent 市场' : props.asset?.name}</span>
        <em>{props.mode === 'quantjudge' ? 'QJ' : props.mode === 'research' ? 'LAB' : props.mode === 'portfolio' ? props.baseCurrency : (props.asset?.currency ?? props.baseCurrency)}</em>
      </div>
      <nav className="mode-tabs" aria-label="工作模式">
        <button aria-current={props.mode === 'single' ? 'page' : undefined} className={props.mode === 'single' ? 'is-active' : ''} onClick={() => props.onMode('single')}>
          <CandlestickChart size={15} /> 单标的
        </button>
        <button aria-current={props.mode === 'portfolio' ? 'page' : undefined} className={props.mode === 'portfolio' ? 'is-active' : ''} onClick={() => props.onMode('portfolio')}>
          <Layers3 size={15} /> 多资产
        </button>
        <button aria-current={props.mode === 'research' ? 'page' : undefined} className={props.mode === 'research' ? 'is-active' : ''} onClick={() => props.onMode('research')}>
          <FlaskConical size={15} /> 策略实验室
        </button>
        <button aria-current={props.mode === 'quantjudge' ? 'page' : undefined} className={props.mode === 'quantjudge' ? 'is-active' : ''} onClick={() => props.onMode('quantjudge')}>
          <Gavel size={15} /> QuantJudge
        </button>
      </nav>
      <div className="toolbar-spacer" />
      {props.mode === 'single' ? (
        <>
          <div className="segmented compact" aria-label="K线周期">
            {intervals.map((item) => (
              <button key={item.value} aria-pressed={props.interval === item.value} className={props.interval === item.value ? 'is-active' : ''} onClick={() => props.onInterval(item.value)}>
                {item.label}
              </button>
            ))}
          </div>
          <div className="segmented compact" aria-label="图表类型">
            <button aria-label="K线图" aria-pressed={props.chartType === 'candles'} className={props.chartType === 'candles' ? 'is-active' : ''} onClick={() => props.onChartType('candles')} title="K线">
              <CandlestickChart size={15} />
            </button>
            <button aria-label="折线图" aria-pressed={props.chartType === 'line'} className={props.chartType === 'line' ? 'is-active' : ''} onClick={() => props.onChartType('line')} title="折线">
              <BarChart3 size={15} />
            </button>
          </div>
        </>
      ) : null}
      {props.mode !== 'quantjudge' ? <label className="source-select">
        <span>数据</span>
        <select value={props.source} onChange={(event) => props.onSource(event.target.value as DataSource)}>
          <option value="auto">自动真实数据</option>
          <option value="yahoo">广覆盖行情</option>
          <option value="binance">加密货币</option>
          <option value="demo">演示数据</option>
        </select>
      </label> : null}
      {props.mode !== 'quantjudge' ? <><button className="icon-button" aria-label="回测历史" onClick={props.onHistory} title="回测历史"><History size={16} /></button>
      <button className="icon-button alert-button" aria-label={`提醒中心${props.unreadAlerts > 0 ? `，${props.unreadAlerts} 条未读` : ''}`} onClick={props.onAlerts} title="提醒中心"><Bell size={16} />{props.unreadAlerts > 0 ? <em>{Math.min(99, props.unreadAlerts)}</em> : null}</button>
      <button className="icon-button" aria-label="本地设置" title="本地设置" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((open) => !open)}><Settings2 size={16} /></button></> : null}
      {props.mode !== 'research' && props.mode !== 'quantjudge' ? <button className="run-button" disabled={props.loading} onClick={props.onRun}>
        {props.loading ? <Clock3 size={15} className="spin" /> : <Play size={15} fill="currentColor" />}
        {props.loading ? '计算中' : '运行回测'}
      </button> : null}
      {settingsOpen && props.mode !== 'quantjudge' ? (
        <div className="settings-popover" role="dialog" aria-label="本地设置">
          <div><strong>本地研究设置</strong><small>自动保存在当前浏览器</small></div>
          <label><span>组合基准币种</span><select value={props.baseCurrency} onChange={(event) => props.onBaseCurrency(event.target.value as BaseCurrency)}><option value="CNY">CNY 人民币</option><option value="USD">USD 美元</option><option value="USDT">USDT</option></select></label>
          <label><span>复权方式</span><select value={props.adjustment} onChange={(event) => props.onAdjustment(event.target.value as Adjustment)}><option value="auto">自动（前复权）</option><option value="raw">不复权</option><option value="forward">前复权</option><option value="backward">后复权</option></select></label>
          <p>K线始终显示标的原始报价币种；组合回测换算使用历史汇率。演示数据只会在手动选择时启用。</p>
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">图表由 TradingView Lightweight Charts™ 提供</a>
        </div>
      ) : null}
    </header>
  )
}
