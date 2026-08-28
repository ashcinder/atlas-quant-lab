import { AlertTriangle, Check, Clock3, Database, FlaskConical, ReceiptText } from 'lucide-react'

interface Props {
  dataSource?: string
  tradeCount?: number
  hasResult: boolean
  warningCount?: number
  isStale?: boolean
  lastBarTime?: number
}

function formatBarTime(time?: number) {
  if (!time) return '等待K线'
  return `最新K线 ${new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(time * 1000))}`
}

export function IntegrityRail({ dataSource, tradeCount = 0, hasResult, warningCount = 0, isStale = false, lastBarTime }: Props) {
  const isDemo = dataSource?.startsWith('demo') ?? false
  const sourceLabel = isDemo
    ? '演示数据（非真实行情）'
    : isStale
      ? '真实缓存 · 刷新失败'
      : dataSource
        ? `真实行情 · ${dataSource.replace(/:.+$/, '')}`
        : '等待数据'
  const items = [
    { icon: Check, label: '下一根K线成交', state: 'ok' },
    { icon: ReceiptText, label: '费用与滑点已计入', state: 'ok' },
    { icon: Database, label: sourceLabel, state: isDemo || isStale ? 'warn' : dataSource ? 'ok' : 'idle' },
    { icon: Clock3, label: formatBarTime(lastBarTime), state: lastBarTime ? (isStale ? 'warn' : 'ok') : 'idle' },
    { icon: FlaskConical, label: hasResult ? `${tradeCount} 笔成交` : '等待回测', state: hasResult && tradeCount < 30 ? 'warn' : hasResult ? 'ok' : 'idle' },
  ]
  return (
    <div className="integrity-rail">
      <span className="rail-title">回测可信度</span>
      {items.map(({ icon: Icon, label, state }) => (
        <span className={`rail-item ${state}`} key={label}><Icon size={13} />{label}</span>
      ))}
      {warningCount > 0 ? <span className="rail-item warn"><AlertTriangle size={13} />{warningCount} 项提示</span> : null}
    </div>
  )
}
