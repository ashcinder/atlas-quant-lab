import { useState } from 'react'
import { request } from '../request'
import type { StrategyRelease } from '../types'

export default function PrivateStrategyRegistration({ onCreated }: { onCreated: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  async function register(file?: File) {
    if (!file) return
    setBusy(true); setMessage('')
    try {
      if (file.size > 8192) throw new Error('只接受小于8KB的公开登记文件，不能上传策略源码。')
      const body = JSON.parse(await file.text()) as Record<string, unknown>
      const allowed = new Set(['name', 'strategy_id', 'source_kind', 'execution_mode', 'runner_public_key', 'code_commitment', 'markets', 'description', 'published'])
      if (Object.keys(body).some(key => !allowed.has(key)) || body.source_kind !== 'private_runner') throw new Error('请选择本地工具生成的release.public.json，不要上传源码或私钥。')
      const release = await request<StrategyRelease>('/strategy-releases', { method: 'POST', body: JSON.stringify(body) })
      await request('/strategy-subscriptions', { method: 'POST', body: JSON.stringify({ release_id: release.id }) })
      await onCreated(); setMessage('已登记并订阅；源码未上传。前往策略交易启动后，复制本地执行配置。')
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : '登记失败') }
    finally { setBusy(false) }
  }
  return <details className="runtime-anchor"><summary>登记不上传源码的私有策略</summary>
    <p>策略在你自己的电脑或服务器执行。平台保存公钥、版本承诺、签名信号及成交记录；源码与私钥留在本地。已有普通规则策略仍采用原保存方式。</p>
    <p>在本地运行工具生成公开登记文件，再选择该文件：</p><code>python scripts/private-strategy-runner.py init --strategy /你的目录/strategy.py --directory /你的私有目录</code>
    <label>公开登记文件<input type="file" accept="application/json,.json" disabled={busy} onChange={event => { void register(event.target.files?.[0]); event.target.value = '' }} /></label>
    {message && <p role="status">{message}</p>}
  </details>
}
