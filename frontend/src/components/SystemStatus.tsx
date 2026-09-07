import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowUpRight, Check, CircleAlert, LockKeyhole, RefreshCw, X } from 'lucide-react'
import { api } from '../api'
import type { QuantChainStatus, ZkProfile } from '../types'

interface Snapshot {
  health: Awaited<ReturnType<typeof api.getHealth>> | null
  chain: QuantChainStatus | null
  profiles: ZkProfile[] | null
  checkedAt: string
  errors: string[]
}

function StatusRow({ title, detail, state, label }: {
  title: string; detail: string; state: 'ready' | 'limited' | 'off'; label: string
}) {
  return <div className="system-status-row"><span className={`status-symbol ${state}`}>{state === 'ready' ? <Check size={17} /> : state === 'limited' ? <CircleAlert size={17} /> : <LockKeyhole size={17} />}</span><div><strong>{title}</strong><p>{detail}</p></div><span className={`status-label ${state}`}>{label}</span></div>
}

export function SystemStatus({ onClose }: { onClose: () => void }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const dialogRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    Promise.allSettled([api.getHealth(controller.signal), api.getQuantChainStatus(controller.signal), api.listZkProfiles(controller.signal)]).then(([health, chain, profiles]) => {
      if (!active) return
      setSnapshot({
        health: health.status === 'fulfilled' ? health.value : null,
        chain: chain.status === 'fulfilled' ? chain.value : null,
        profiles: profiles.status === 'fulfilled' ? profiles.value : null,
        checkedAt: new Date().toLocaleTimeString('zh-CN'),
        errors: [health, chain, profiles].flatMap((result, index) => result.status === 'rejected' ? [`${['后端服务', '链连接', '证明配置'][index]}检查失败，请确认服务和版本配置。`] : []),
      })
      setLoading(false)
    })
    return () => { active = false; controller.abort() }
  }, [refresh])

  useEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    dialog?.querySelector<HTMLElement>('button')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab' || !dialog) return
      const items = [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]')]
      const first = items[0], last = items.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); returnFocus?.focus() }
  }, [onClose])

  const online = snapshot?.health?.status === 'ok'
  const zkReady = snapshot?.profiles?.some((profile) => profile.status === 'active' && profile.verifier_ready) ?? false
  const chainReady = snapshot?.chain?.connected && snapshot.chain.compatible
  return <div className="system-status-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section ref={dialogRef} className="system-status-dialog" role="dialog" aria-modal="true" aria-labelledby="system-status-title">
      <header><div><span className="eyebrow">WORKSPACE HEALTH</span><h2 id="system-status-title">系统状态与能力</h2><p>看清当前可用的功能，以及还没有接入的服务。</p></div><button aria-label="关闭系统状态" onClick={onClose}><X size={20} /></button></header>
      <div className="system-status-summary" role="status"><Activity size={18} /><div><strong>{loading ? '正在检查服务…' : online ? `后端服务在线 · v${snapshot?.health?.version}` : '无法连接后端服务'}</strong><span>{loading ? '仅读取状态，不会提交交易或证明。' : `检查于 ${snapshot?.checkedAt} · 在线不代表所有依赖均已就绪`}</span></div><button disabled={loading} onClick={() => { setLoading(true); setRefresh((value) => value + 1) }}><RefreshCw size={14} className={loading ? 'spin' : ''} />重新检查</button></div>
      {!loading ? <div className="system-status-capabilities">
        <StatusRow title="行情与规则回测" label={online ? '服务在线' : '不可用'} state={online ? 'ready' : 'limited'} detail="受控规则、历史行情和组合研究。行情源可用性需在实际请求时确认。" />
        <StatusRow title="SMA 零知识证明" label={zkReady ? '验证器就绪' : '未就绪'} state={zkReady ? 'ready' : 'limited'} detail="固定单资产 SMA profile；不覆盖任意 Python 策略、AI 推理或 TEE。就绪不等于某份报告已通过验证。" />
        <StatusRow title="Supervisor 链连接" label={chainReady ? '已连接' : '未就绪'} state={chainReady ? 'ready' : 'limited'} detail={chainReady ? `链 ID ${snapshot?.chain?.chain_id} · 最新区块 ${snapshot?.chain?.block_number}。连接不代表报告已经上链。` : snapshot?.chain?.connected ? '已连接节点，但链 ID 与预期配置不一致。' : '本次未确认兼容的链连接；可以继续本地研究。'} />
        <StatusRow title="通用 Python / AI / TEE 执行" label="未接入" state="off" detail="可编辑、校验与保存工作流和策略包；尚不支持完整隔离执行及可信推理。" />
        <StatusRow title="实盘账户与真实支付" label="未启用" state="off" detail="当前是研究工作空间。订阅为本地沙盒，不会扣款；不会向交易所下单。" />
      </div> : null}
      {snapshot?.errors.length && !loading ? <div className="system-status-errors">{snapshot.errors.map((error) => <p key={error}>{error}</p>)}</div> : null}
      <footer><p><LockKeyhole size={14} />当前按个人私有工作空间设计，不应直接暴露到公网。</p><a href="/api/docs" target="_blank" rel="noreferrer">开发者 API 文档 <ArrowUpRight size={14} /></a></footer>
    </section>
  </div>
}
