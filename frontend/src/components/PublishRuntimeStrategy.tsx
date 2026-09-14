import { useRef, useState } from 'react'
import { request } from '../request'
import type { CustomStrategySpec, StrategyRelease, StrategySubscription } from '../types'

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
    {error ? <span role="alert">{error}</span> : null}
  </span>
}
