import { useRef, useState } from 'react'
import { CloudProofControl } from './CloudProofControl'
import { labOwnerHeaders, type LabStrategy } from '../lab-strategy-types'
import { request } from '../request'
import type { StrategyRelease } from '../types'

export function SavedStrategyProof({ record, ownerId }: { record: LabStrategy; ownerId: string }) {
  const [release, setRelease] = useState<StrategyRelease | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  async function prepare() {
    if (pending.current) return
    pending.current = true; setBusy(true); setError('')
    try {
      const headers = labOwnerHeaders(ownerId)
      const checked = await request<{ proof_compatible?: boolean }>('/strategy-code/validate', {
        method: 'POST', headers, body: JSON.stringify({ code: record.source, language: 'python', profile: 'bounded' }),
      })
      if (!checked.proof_compatible) throw new Error('这份策略无法编译成 zkVM 指令。请使用受限的 target_bps(index, close, sma) Python 入口。')
      setRelease(await request<StrategyRelease>('/strategy-releases', {
        method: 'POST', headers,
        body: JSON.stringify({ name: record.name, source_kind: 'python', strategy_id: 'python_bounded',
          python_source: record.source, markets: ['CRYPTO', 'US', 'CN'], published: false }),
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法准备 ZKP。')
    } finally { setBusy(false); pending.current = false }
  }
  return <div className="market-strategy-proof">
    {release ? <CloudProofControl releaseId={release.id} /> : <button type="button" disabled={busy} onClick={() => void prepare()}>
      {busy ? '正在检查证明兼容性…' : '为策略生成 ZKP'}
    </button>}
    <small>证明使用 zkVM 的登记日线和执行参数，单独验证结果。</small>
    {error ? <p role="alert">{error}</p> : null}
  </div>
}
