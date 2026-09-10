import { Activity, lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ChartCandlestick, Wallet, LogOut, LoaderCircle } from 'lucide-react'
import LoginScreen from './journal/components/LoginScreen'
import { setStorageUser } from './storage'
import { useTheme, type ThemePreference } from './theme'

const QuantWorkspace = lazy(() => import('./App'))
const TradingWorkspace = lazy(() => import('./components/TradingWorkspace'))
const JournalWorkspace = lazy(() => import('./journal/components/investment-app'))
type Session = { authenticated: boolean; registrationEnabled: boolean; email: string | null; userId?: string }
const workspaceFromHash = () => window.location.hash.startsWith('#/trading') ? 'trading' : window.location.hash.startsWith('#/journal') ? 'journal' : 'quant'

export default function AtlasShell() {
  const [theme, setTheme] = useTheme()
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [workspace, setWorkspace] = useState(workspaceFromHash)
  useEffect(() => { if (workspace === 'journal') document.title = '资产账本 · Atlas' }, [workspace])
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
      setWorkspace(next)
      setVisited((current) => ({ ...current, [next]: true }))
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
      <a className="atlas-brand" href="#single"><ChartCandlestick size={23} /><strong>Atlas <span>Quant Lab</span></strong></a>
      <nav className="atlas-workspaces" aria-label="主导航">
        <a href="#single" aria-current={workspace === 'quant' ? 'page' : undefined}><ChartCandlestick size={17} />策略工作台</a>
        <a href="#/trading" aria-current={workspace === 'trading' ? 'page' : undefined}><ChartCandlestick size={17} />交易账户</a>
        <a href="#/journal/overview" aria-current={workspace === 'journal' ? 'page' : undefined}><Wallet size={17} />资产账本</a>
      </nav>
      <label className="atlas-theme"><span>主题</span><select aria-label="显示主题" value={theme} onChange={(event) => setTheme(event.target.value as ThemePreference)}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label>
      <div className="atlas-session"><span title={session.email ?? ''}>{session.email}</span><button onClick={() => void logout()} disabled={busy} aria-label="退出 Atlas"><LogOut size={16} /><span>退出</span></button></div>
    </header>
    {error && <div className="atlas-global-error" role="alert">{error}</div>}
    <Suspense fallback={<div className="atlas-connecting" role="status"><LoaderCircle className="spin" size={24} /><p>正在加载工作区…</p></div>}>
      {workspace === 'trading' ? <TradingWorkspace /> : workspace === 'quant' ? <div className="quant-workspace"><QuantWorkspace /></div> : <div className="journal-root"><JournalWorkspace /><div id="journal-portals" /></div>}
    </Suspense>
  </div>
}
