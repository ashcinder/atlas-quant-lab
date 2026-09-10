import { lazy, Suspense, useEffect, useState, useRef } from 'react'
import { ChartCandlestick, Wallet, LogOut, LoaderCircle, X, ChevronUp } from 'lucide-react'
import LoginScreen from './journal/components/LoginScreen'
import { setStorageUser } from './storage'

const QuantWorkspace = lazy(() => import('./App'))
const TradingWorkspace = lazy(() => import('./components/TradingWorkspace'))
const JournalWorkspace = lazy(() => import('./journal/components/investment-app'))
type Session = { authenticated: boolean; registrationEnabled: boolean; email: string | null; userId?: string }
const workspaceFromHash = () => window.location.hash.startsWith('#/trading') ? 'trading' : window.location.hash.startsWith('#/journal') ? 'journal' : 'quant'
const titleFromHash = () => {
  if (window.location.hash.startsWith('#/trading')) return '交易账户 · Atlas'
  if (window.location.hash.startsWith('#/journal')) {
    const tab = window.location.hash.split('/')[2]?.split('?')[0] ?? 'overview'
    return `${({ overview: '资产总览', accounts: '我的账户', records: '投资记录', plans: '定投计划', analysis: '收益分析', trading: '自动交易账本' } as Record<string, string>)[tab] ?? '资产账本'} · Atlas`
  }
  const route = window.location.hash.slice(1).split('?')[0]
  return `${({ single: '行情与回测', portfolio: '投资组合', research: '策略实验室', quantjudge: '策略市场' } as Record<string, string>)[route] ?? '行情与回测'} · Atlas`
}

export default function AtlasShell() {
  const switcher = useRef<HTMLDetailsElement>(null)
  const sessionRequest = useRef(0)
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => { if (switcher.current && !switcher.current.contains(event.target as Node)) switcher.current.open = false }
    const closeEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && switcher.current?.open) { switcher.current.open = false; switcher.current.querySelector('summary')?.focus() } }
    const closeNavigation = () => { if (switcher.current) switcher.current.open = false }
    document.addEventListener('pointerdown', closeOutside); document.addEventListener('keydown', closeEscape); window.addEventListener('hashchange', closeNavigation)
    return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('keydown', closeEscape); window.removeEventListener('hashchange', closeNavigation) }
  }, [])
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [workspace, setWorkspace] = useState(workspaceFromHash)
  const [quantHref, setQuantHref] = useState(() =>
    workspaceFromHash() === 'quant' ? window.location.hash || '#single' : '#single',
  )
  const [visited, setVisited] = useState<Record<'quant' | 'trading' | 'journal', boolean>>(() => {
    const initial = workspaceFromHash()
    return { quant: initial === 'quant', trading: initial === 'trading', journal: initial === 'journal' }
  })
  useEffect(() => {
    const timer = window.setTimeout(() => { document.title = titleFromHash() }, 0)
    return () => window.clearTimeout(timer)
  }, [workspace])
  async function refreshSession() {
    const requestId = ++sessionRequest.current
    const response = await fetch('/api/session', { credentials: 'same-origin', cache: 'no-store' })
    if (!response.ok) throw new Error('无法连接 Atlas，请检查后端服务后重试。')
    const next = await response.json() as Session
    if (requestId !== sessionRequest.current) return
    setStorageUser(next.authenticated ? next.userId ?? next.email ?? '' : '')
    setSession(next)
    setError('')
  }
  useEffect(() => {
    const initial = window.setTimeout(() => void refreshSession().catch((cause: Error) => setError(cause.message)), 0)
    const expire = () => {
      sessionRequest.current += 1
      setStorageUser('')
      setSession((current) => current ? { ...current, authenticated: false } : null)
      setError('登录已过期，请重新登录。')
    }
    const visible = () => {
      if (document.visibilityState === 'visible') void refreshSession().catch(() => undefined)
    }
    const hash = () => {
      const next = workspaceFromHash()
      if (next === 'quant') setQuantHref(window.location.hash || '#single')
      setWorkspace(next)
      setVisited((current) => current[next] ? current : { ...current, [next]: true })
    }
    window.addEventListener('atlas-session-expired', expire)
    window.addEventListener('hashchange', hash)
    document.addEventListener('visibilitychange', visible)
    const timer = window.setInterval(visible, 60_000)
    return () => {
      sessionRequest.current += 1
      window.clearTimeout(initial)
      window.removeEventListener('atlas-session-expired', expire)
      window.removeEventListener('hashchange', hash)
      document.removeEventListener('visibilitychange', visible)
      window.clearInterval(timer)
    }
  }, [])
  async function authenticate(mode: 'login' | 'register', email: string, password: string) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`/api/${mode}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }), credentials: 'same-origin',
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error ?? result.detail ?? '登录失败，请重试。')
      await refreshSession()
    } finally { setBusy(false) }
  }
  async function logout() {
    sessionRequest.current += 1
    setBusy(true)
    try {
      const response = await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) throw new Error('退出失败，请重试。')
      sessionRequest.current += 1
      setStorageUser('')
      setSession((current) => current ? { ...current, authenticated: false } : null)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '退出失败') }
    finally { setBusy(false) }
  }
  if (!session) return <main className="atlas-connecting"><ChartCandlestick size={30} /><h1>Atlas Quant Lab</h1><p role="status">{error || '正在连接你的工作台…'}</p>{error && <button onClick={() => void refreshSession().catch((cause: Error) => setError(cause.message))}>重新连接</button>}</main>
  if (!session.authenticated) return <div className="journal-root atlas-auth"><LoginScreen busy={busy} error={error} registrationEnabled={session.registrationEnabled} onAuthenticate={authenticate} /></div>
  return <div className="atlas-shell" key={session.userId ?? session.email}>
    <header className="atlas-header">
      <details ref={switcher} className="workspace-switcher"><summary><Wallet size={17} /><span>切换工作区</span><ChevronUp size={14} /></summary>
      <button className="workspace-switcher-close" onClick={() => { if (switcher.current) switcher.current.open = false }} aria-label="收起工作区切换"><X size={16} />收起</button>
      <nav className="atlas-workspaces" aria-label="主导航">
        <a href={quantHref} aria-current={workspace === 'quant' ? 'page' : undefined}><ChartCandlestick size={17} />策略工作台</a>
        <a href="#/trading" aria-current={workspace === 'trading' ? 'page' : undefined}><ChartCandlestick size={17} />交易账户</a>
        <a href="#/journal/overview" aria-current={workspace === 'journal' ? 'page' : undefined}><Wallet size={17} />资产账本</a>
      </nav>
      <div className="atlas-session"><span title={session.email ?? ''}>{session.email}</span><button onClick={() => void logout()} disabled={busy} aria-label="退出 Atlas"><LogOut size={16} /><span>退出</span></button></div>
      </details>
    </header>
    {error && <div className="atlas-global-error" role="alert">{error}</div>}
    <Suspense fallback={<div className="atlas-connecting" role="status"><LoaderCircle className="spin" size={24} /><p>正在加载工作区…</p></div>}>
      {visited.quant ? <div className="quant-workspace" hidden={workspace !== 'quant'}><QuantWorkspace /></div> : null}
      {visited.trading ? <div hidden={workspace !== 'trading'}><TradingWorkspace /></div> : null}
      {visited.journal ? <div className="journal-root" hidden={workspace !== 'journal'}><JournalWorkspace /><div id="journal-portals" /></div> : null}
    </Suspense>
  </div>
}
