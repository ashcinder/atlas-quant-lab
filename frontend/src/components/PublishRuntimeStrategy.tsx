import { CloudProofControl } from './CloudProofControl'
import { useEffect, useRef, useState } from 'react'
import { request } from '../request'
import type { CustomStrategySpec, StrategyRelease, StrategySubscription } from '../types'
import { ChevronDown, X, Globe, Shield } from 'lucide-react'

interface Draft {
  name: string
  source_kind: 'builtin' | 'custom' | 'python'
  strategy_id: string
  params?: Record<string, unknown>
  custom_strategy?: CustomStrategySpec
  python_source?: string
}

/** Publish the exact editor snapshot, then subscribe without losing partial success. */
export function PublishRuntimeStrategy({ draft, disabled = false }: { draft: Draft; disabled?: boolean }) {
  const snapshot = JSON.stringify({ ...draft, name: draft.name.trim(), markets: ['CRYPTO', 'US', 'CN'], published: false })
  const created = useRef<{ snapshot: string; release: StrategyRelease } | null>(null)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [subscribed, setSubscribed] = useState<{ snapshot: string; release: StrategyRelease; subscription: StrategySubscription } | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const publishDialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { if(menuOpen) publishDialog.current?.showModal(); else publishDialog.current?.close() }, [menuOpen])
  async function publish() {
    if (pending.current) return
    pending.current = true; setBusy(true); setError('')
    try {
      if (created.current?.snapshot !== snapshot) {
        const release = await request<StrategyRelease>('/strategy-releases', { method: 'POST', body: snapshot })
        created.current = { snapshot, release }
      }
      const release = created.current.release
      const subscription = await request<StrategySubscription>('/strategy-subscriptions', { method: 'POST', body: JSON.stringify({ release_id: release.id }) })
      setSubscribed({ snapshot, release, subscription })
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存运行版本失败，请重试') }
    finally { pending.current = false; setBusy(false) }
  }
  const ready = subscribed?.snapshot === snapshot ? subscribed : null
  return <span className="runtime-publish-action">
    {ready ? <a href={`#/trading?release=${ready.release.id}&subscription=${ready.subscription.id}`}>已订阅 v{ready.release.version} · 配置并运行</a>
      : <button type="button" disabled={disabled || busy || !draft.name.trim() || draft.name.trim().length > 80} onClick={() => void publish()}>{busy ? '保存并订阅中…' : '保存并订阅运行版本'}</button>}
    {ready && <div className="trine-publish-menu">
      <button className="trine-publish-menu-btn" onClick={() => setMenuOpen(!menuOpen)}>
        发布与 Proof <ChevronDown size={12} />
      </button>
      <dialog ref={publishDialog} className="trine-publish-dialog" aria-label="发布与 Proof" onCancel={()=>setMenuOpen(false)}><div className="trine-publish-dropdown">
        <div className="trine-dropdown-header">
          <span><Shield size={14} /> 发布与 Proof</span>
          <button aria-label="关闭发布窗口" className="trine-dropdown-close" onClick={() => setMenuOpen(false)}><X size={14} /></button>
        </div>
        <p>公开后可在策略市场查看，初始标记为无 ZKP 验证。</p>
        <button disabled={busy} onClick={async () => {
          setBusy(true)
          try {
            await request(`/strategy-releases/${ready.release.id}/publish`, { method: 'POST' })
            setError('已公开 · 无 ZKP 验证')
          } catch (e) { setError((e as Error).message) }
          finally { setBusy(false) }
        }}>
          <Globe size={13} /> 直接公开策略
        </button>
        <div className="trine-publish-divider" />
        <CloudProofControl releaseId={ready.release.id} sourceKind={draft.source_kind} />
      </div></dialog>
    </div>}
    {error ? <span role="alert">{error}</span> : null}
  </span>
}
