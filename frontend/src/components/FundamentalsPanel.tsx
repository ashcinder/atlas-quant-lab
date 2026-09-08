import {
  AlertTriangle,
  ChevronDown,
  CircleGauge,
  Database,
  Info,
  RefreshCw,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { formatFundamentalMetric } from '../fundamentalsFormat'
import type { Asset, FundamentalsResponse } from '../types'

interface Props {
  asset: Asset | null
  data: FundamentalsResponse | null
  loading: boolean
  error: string | null
  onLoad: (refresh?: boolean) => void
}

function statusCopy(data: FundamentalsResponse): string {
  if (data.is_stale) return '历史缓存'
  if (data.status === 'available') return '数据充足'
  if (data.status === 'partial') return '部分可用'
  if (data.status === 'not_applicable') return '不适用'
  return '暂不可用'
}

function formatTime(timestamp: number | null): string {
  if (!timestamp) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(timestamp * 1000)
}

export function FundamentalsPanel({ asset, data, loading, error, onLoad }: Props) {
  if (!asset) return <div className="fundamentals-empty">请先选择标的</div>
  const matchedData = data?.asset.symbol === asset.symbol
    && data.asset.asset_class === asset.asset_class ? data : null

  if (loading && !matchedData) {
    return (
      <div className="fundamentals-loading" aria-label="正在加载金融指标">
        <RefreshCw size={16} className="spin" />
        <strong>读取金融指标</strong>
        <span>正在聚合适用于该市场的真实快照…</span>
        {Array.from({ length: 6 }, (_, index) => <i key={index} />)}
      </div>
    )
  }

  if (error && !matchedData) {
    return (
      <div className="fundamentals-empty is-error" role="alert">
        <AlertTriangle size={18} />
        <strong>金融指标暂不可用</strong>
        <span>{error}</span>
        <button type="button" onClick={() => onLoad(true)}>重新获取</button>
      </div>
    )
  }

  if (!matchedData) {
    return (
      <div className="fundamentals-empty">
        <CircleGauge size={20} />
        <strong>{asset.symbol} 金融指标</strong>
        <span>按需加载，不影响 K 线首屏速度。</span>
        <button type="button" onClick={() => onLoad()}>加载指标</button>
      </div>
    )
  }

  data = matchedData
  return (
    <div className="fundamentals-content">
      <header className="fundamentals-summary">
        <div className="fundamentals-title-row">
          <div>
            <strong>{data.asset.symbol}</strong>
            <span>{data.asset.name}</span>
          </div>
          <button
            type="button"
            className="fundamentals-refresh"
            onClick={() => onLoad(true)}
            disabled={loading}
            title="刷新金融指标"
          >
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
          </button>
        </div>
        <div className="fundamentals-health">
          <span className={`fundamentals-status status-${data.status}${data.is_stale ? ' is-stale' : ''}`}>
            {statusCopy(data)}
          </span>
          <strong aria-label={`已返回 ${data.available_metric_count} / ${data.total_metric_count} 项指标`}>{data.available_metric_count}<small> / {data.total_metric_count}</small></strong>
          <em style={{ '--coverage': `${Math.round(data.coverage * 100)}%` } as CSSProperties}>覆盖率 {Math.round(data.coverage * 100)}%</em>
        </div>
        <div className="fundamentals-meta">
          <span><Database size={11} />{data.source}</span>
          <span>数据时间 {formatTime(data.as_of)}</span>
        </div>
      </header>

      <div className="fundamentals-notice">
        <Info size={13} />
        <span>当前快照仅用于查看与横向比较，不会自动进入历史回测。</span>
      </div>

      <div className="fundamentals-sections">
        {data.sections.map((section, index) => (
          <details className="fundamental-section" key={section.id} open={index === 0}>
            <summary>
              <span>{section.label}</span>
              <em>{section.metrics.filter((metric) => metric.value !== null).length}/{section.metrics.length}</em>
              <ChevronDown size={13} />
            </summary>
            <div>
              {section.metrics.map((metric) => (
                <div
                  className={`fundamental-row${metric.value === null ? ' is-missing' : ''}`}
                  key={metric.key}
                  title={metric.description}
                >
                  <span>
                    {metric.label}
                    {metric.derived ? <i>派生</i> : null}
                    <small>{metric.period}</small>
                  </span>
                  <strong>{formatFundamentalMetric(metric)}</strong>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>

      <footer className="fundamentals-footnote">
        {data.warnings.map((warning) => <p key={warning}>{warning}</p>)}
        <span>抓取于 {formatTime(data.fetched_at)}{data.cache_hit ? ' · 缓存命中' : ''}</span>
      </footer>
    </div>
  )
}
