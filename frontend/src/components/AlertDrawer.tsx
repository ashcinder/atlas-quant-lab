import { useEffect, useRef, useState } from 'react'
import { Bell, BellRing, CheckCheck, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { api } from '../api'
import type { AlertKind, AlertNotification, AlertRule, AlertRuleInput, Asset, DataSource, Interval } from '../types'

interface Props {
  open: boolean
  asset: Asset | null
  interval: Interval
  source: DataSource
  onClose: () => void
  onUnread: (count: number) => void
  onError: (message: string) => void
}

const ALERT_KINDS: Array<{ value: AlertKind; label: string; threshold: boolean; defaultValue: (asset: Asset | null) => number }> = [
  { value: 'price_crosses_above', label: '价格上穿', threshold: true, defaultValue: () => 0 },
  { value: 'price_crosses_below', label: '价格下穿', threshold: true, defaultValue: () => 0 },
  { value: 'change_pct_above', label: '单根K线涨幅超过', threshold: true, defaultValue: () => 0.05 },
  { value: 'rsi_above', label: 'RSI14 上穿', threshold: true, defaultValue: () => 70 },
  { value: 'rsi_below', label: 'RSI14 下穿', threshold: true, defaultValue: () => 30 },
  { value: 'macd_crosses_above', label: 'MACD 金叉', threshold: false, defaultValue: () => 0 },
  { value: 'macd_crosses_below', label: 'MACD 死叉', threshold: false, defaultValue: () => 0 },
]

function dateTime(value: string | null) {
  if (!value) return '尚未触发'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}

export function AlertDrawer({ open, asset, interval, source, onClose, onUnread, onError }: Props) {
  const [alerts, setAlerts] = useState<AlertRule[]>([])
  const [notifications, setNotifications] = useState<AlertNotification[]>([])
  const [creating, setCreating] = useState(false)
  const [kind, setKind] = useState<AlertKind>('price_crosses_above')
  const [threshold, setThreshold] = useState(0)
  const [cooldown, setCooldown] = useState(60)
  const [name, setName] = useState('')
  const seenRef = useRef<Set<string>>(new Set())

  const load = async () => {
    try {
      const [rules, messages] = await Promise.all([api.listAlerts(), api.listNotifications()])
      setAlerts(rules); setNotifications(messages)
      onUnread(messages.filter((item) => !item.read).length)
      if ('Notification' in window && Notification.permission === 'granted') {
        messages.filter((item) => !item.read && !seenRef.current.has(item.id)).forEach((item) => {
          seenRef.current.add(item.id)
          new Notification(item.title, { body: item.message, tag: item.id })
        })
      }
    } catch (reason) { onError(reason instanceof Error ? reason.message : '无法读取提醒') }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const timer = window.setInterval(() => void load(), 30_000)
    return () => { window.clearTimeout(initial); window.clearInterval(timer) }
    // load only relies on API module and stable callbacks supplied by App.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!open) return
    const refresh = window.setTimeout(() => void load(), 0)
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', closeOnEscape)
    return () => { window.clearTimeout(refresh); window.removeEventListener('keydown', closeOnEscape) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, open])

  const create = async () => {
    if (!asset) return onError('请先选择标的')
    const selectedKind = ALERT_KINDS.find((item) => item.value === kind)
    const payload: AlertRuleInput = {
      name: name.trim() || `${asset.symbol} ${selectedKind?.label ?? '提醒'}`,
      symbol: asset.symbol, asset_class: asset.asset_class, interval, data_source: source,
      kind, threshold: selectedKind?.threshold ? threshold : null, cooldown_minutes: cooldown, enabled: true,
    }
    try {
      await api.createAlert(payload)
      setCreating(false); setName(''); await load()
    } catch (reason) { onError(reason instanceof Error ? reason.message : '创建提醒失败') }
  }
  const toggle = async (rule: AlertRule) => {
    const payload: AlertRuleInput = {
      name: rule.name,
      symbol: rule.symbol,
      asset_class: rule.asset_class,
      interval: rule.interval,
      data_source: rule.data_source,
      kind: rule.kind,
      threshold: rule.threshold,
      cooldown_minutes: rule.cooldown_minutes,
      enabled: !rule.enabled,
    }
    await api.updateAlert(rule.id, payload)
    await load()
  }
  const markRead = async () => { await api.markNotificationsRead(); await load() }
  const enableDesktop = async () => {
    if ('Notification' in window) await Notification.requestPermission()
  }

  return <div className={`drawer-backdrop ${open ? 'is-open' : ''}`} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <aside className="alert-drawer" role="dialog" aria-modal="true" aria-label="提醒中心" aria-hidden={!open}>
      <div className="drawer-heading"><span><BellRing size={15} />提醒中心</span><button className="icon-button" aria-label="关闭提醒中心" onClick={onClose}><X size={15} /></button></div>
      <div className="alert-actions"><button onClick={() => setCreating((value) => !value)}><Plus size={12} />新建提醒</button><button onClick={() => void api.evaluateAlerts().then(load)}><RefreshCw size={12} />立即检查</button><button onClick={enableDesktop}><Bell size={12} />系统通知</button></div>
      {creating ? <div className="alert-form"><label><span>提醒名称</span><input placeholder={`${asset?.symbol ?? '标的'} 价格提醒`} value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>条件</span><select value={kind} onChange={(event) => { const next = event.target.value as AlertKind; setKind(next); setThreshold(ALERT_KINDS.find((item) => item.value === next)?.defaultValue(asset) ?? 0) }}>{ALERT_KINDS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>{ALERT_KINDS.find((item) => item.value === kind)?.threshold ? <label><span>阈值{kind === 'change_pct_above' ? '（小数）' : ''}</span><input type="number" step="any" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label> : null}<label><span>冷却分钟</span><input type="number" min={1} value={cooldown} onChange={(event) => setCooldown(Number(event.target.value))} /></label><div><button onClick={() => setCreating(false)}>取消</button><button className="primary" onClick={create}>保存提醒</button></div></div> : null}
      <div className="alert-tabs"><strong>规则 <em>{alerts.length}</em></strong><button onClick={markRead}><CheckCheck size={12} />全部已读</button></div>
      <div className="alert-scroll">
        <section className="alert-rule-list">{alerts.map((rule) => <div className={`alert-rule ${rule.enabled ? '' : 'is-disabled'}`} key={rule.id}><button className="alert-switch" aria-label={rule.enabled ? '停用提醒' : '启用提醒'} aria-pressed={rule.enabled} onClick={() => void toggle(rule)}><i /></button><span><strong>{rule.name}</strong><small>{rule.symbol} · {rule.interval} · {ALERT_KINDS.find((item) => item.value === rule.kind)?.label}</small><em>上次触发 {dateTime(rule.last_triggered_at)}</em></span><button className="rule-delete" aria-label={`删除提醒 ${rule.name}`} onClick={async () => { await api.deleteAlert(rule.id); await load() }}><Trash2 size={12} /></button></div>)}</section>
        <section className="notification-list"><h3>触发记录</h3>{notifications.length ? notifications.map((item) => <div className={item.read ? '' : 'is-unread'} key={item.id}><i /><span><strong>{item.title}</strong><p>{item.message}</p><small>{dateTime(item.triggered_at)}</small></span></div>) : <p className="drawer-empty-small">尚无触发记录</p>}</section>
      </div>
    </aside>
  </div>
}
