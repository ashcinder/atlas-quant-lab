import { useEffect, useState } from 'react'
import { request } from '../request'
import { walletAddress } from '../supervisorWallet'
import { PayOrderButton } from './PayOrderButton'
import { X, ChevronDown, ChevronUp, Cloud, ShieldCheck, AlertTriangle, LoaderCircle, ExternalLink, Clock, Info } from 'lucide-react'

type Job = {
  id: string
  order_id: string
  status: string
  proof_id?: string
  error?: string
  quote?: {
    amount_bkc: string
    bars: number
    program_nodes: number
    work_units: string
  }
}

const labels: Record<string, string> = {
  unverified: '无 ZKP 验证',
  awaiting_payment: '等待支付',
  queued: 'Proof 排队中',
  proving: 'Proof 生成中',
  verified: 'ZKP 已验证',
  failed: 'Proof 生成失败',
}

const statusConfig: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  unverified: { icon: <AlertTriangle size={13} />, color: 'var(--muted)', bg: 'transparent' },
  awaiting_payment: { icon: <LoaderCircle size={13} className="spin" />, color: 'var(--accent)', bg: 'transparent' },
  queued: { icon: <Cloud size={13} />, color: 'var(--accent)', bg: 'transparent' },
  proving: { icon: <LoaderCircle size={13} className="spin" />, color: 'var(--accent)', bg: 'transparent' },
  verified: { icon: <ShieldCheck size={13} />, color: 'var(--positive)', bg: 'rgba(18, 134, 108, 0.1)' },
  failed: { icon: <AlertTriangle size={13} />, color: 'var(--negative)', bg: 'rgba(215, 70, 91, 0.1)' },
}

export function CloudProofControl({
  releaseId,
  owned = true,
  proofStatus = 'unverified',
  proofId,
  sourceKind = 'python',
}: {
  releaseId: string
  owned?: boolean
  proofStatus?: string
  proofId?: string
  sourceKind?: string
}) {
  const [open, setOpen] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [config, setConfig] = useState<{
    configured: boolean
    unavailable_reason?: string
    price_bkc: string
    recipient: string
  } | null>(null)
  const [symbol, setSymbol] = useState('BTC-USD')
  const [coverage,setCoverage]=useState<{bar_count:number;period_start:string;period_end:string}|null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [consent, setConsent] = useState(false)

  useEffect(() => {
    if (!owned || sourceKind !== 'python') return
    let active = true
    const load = () =>
      request<Job[]>(`/strategy-releases/${releaseId}/proof-jobs`)
        .then((j) => { if (active) setJob(j[0] || null) })
        .catch(() => {})
    void load()
    const timer = setInterval(load, 5000)
    request<typeof config>('/cloud-proofs/config')
      .then((c) => { if (active) setConfig(c) })
      .catch(() => {})
    return () => { active = false; clearInterval(timer) }
  }, [releaseId, owned, sourceKind])

  async function create() {
    setBusy(true)
    setError('')
    try {
      const address = walletAddress()
      if (!address) throw new Error('先在设置中配置 Supervisor 账户')
      const dataset = await request<{ market_data_hash: string;bar_count:number;period_start:string;period_end:string }>(
        `/quantjudge/zkp/database-history?symbol=${encodeURIComponent(symbol)}&interval=1d`,
        { method: 'POST' }
      )
      setCoverage(dataset)
      setJob(
        await request<Job>(`/strategy-releases/${releaseId}/proof-jobs`, {
          method: 'POST',
          body: JSON.stringify({ market_data_hash: dataset.market_data_hash, address, consent_cloud_source: consent }),
        })
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function enqueue() {
    try {
      setJob(await request<Job>(`/cloud-proofs/${job!.id}/start`, { method: 'POST' }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const status = job?.status || proofStatus
  const proof = job?.proof_id || proofId
  const cfg = statusConfig[status] || statusConfig.unverified

  return (
    <div className="trine-cloud-proof">
      {/* Status Badge */}
      <span
        className={`proof-state is-${status}`}
        style={{ color: cfg.color, backgroundColor: cfg.bg, borderColor: cfg.color }}
      >
        {cfg.icon}
        {labels[status] || status}
      </span>

      {/* Proof Link */}
      {proof && (
        <a href={`#/proof/${proof}`} className="proof-link">
          验证 Proof <ExternalLink size={11} />
        </a>
      )}

      {/* Toggle Button */}
      {owned && sourceKind === 'python' && (
        <button className="proof-toggle-btn" onClick={() => setOpen(!open)}>
          {open ? (
            <>收起 <ChevronUp size={14} /></>
          ) : (
            <>云端生成 Proof <ChevronDown size={14} /></>
          )}
        </button>
      )}

      {/* Expanded Form Panel */}
      {open && (
        <div className="trine-proof-form">
          {/* Header with close button */}
          <div className="trine-form-header">
            <div className="trine-form-title">
              <Cloud size={16} />
              <span>云端 ZKP 生成</span>
            </div>
            <button className="trine-form-close" onClick={() => setOpen(false)} title="关闭">
              <X size={16} />
            </button>
          </div>

          {/* Warning notice */}
          <div className="trine-notice">
            <Info size={14} />
            <p>RISC Zero zkVM 在服务器生成 ZKP。服务器可读取策略程序；本地证明代码继续保留。生成失败可使用原付款重试，不会自动退款。</p>
          </div>

          {/* Job status */}
          {job && (
            <div className="trine-job-status">
              <Clock size={13} />
              <span>任务：{job.id} · {labels[job.status]}</span>
            </div>
          )}

          {/* Form fields */}
          {(!job || job.status === 'verified') && (
            <>
              <div className="trine-form-row">
                <label className="trine-field">
                  <span>标的</span>
                  <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                    <option>BTC-USD</option>
                    <option>ETH-USD</option>
                    <option>SOL-USD</option>
                  </select>
                </label>
              </div>

              <small className="trine-field-hint">证明使用平台数据库中该标的全部已收盘日 K，报价时锁定数据快照，不截短区间。初始资金 10000，手续费 0.1%，滑点 0.05%。</small>
              {coverage&&<p>{coverage.period_start.slice(0,10)} — {coverage.period_end.slice(0,10)} · {coverage.bar_count} 根日 K</p>}

              <label className="trine-checkbox">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                <span>允许服务器读取此版本程序进行证明</span>
              </label>

              <button
                className="trine-submit-btn"
                disabled={busy || !config?.configured || !consent}
                onClick={() => void create()}
              >
                {busy ? (
                  <>准备中… <LoaderCircle size={14} className="spin" /></>
                ) : config?.configured ? (
                  <>计算报价 · {config.price_bkc} BKC 起</>
                ) : (
                  config?.unavailable_reason || '证明服务尚未就绪'
                )}
              </button>
            </>
          )}

          {/* Quote section */}
          {job?.quote && (
            <div className="trine-proof-quote">
              <div className="quote-header">
                <small>本次锁定报价 · 不含链上手续费</small>
              </div>
              <strong className="quote-amount">
                {job.quote.amount_bkc} <small>BKC</small>
              </strong>
              <span className="quote-details">
                {job.quote.bars} 根 K 线 · {job.quote.program_nodes} 个程序节点 · {job.quote.work_units} 计价单位
              </span>
              <small>按计算量估价，付款后不追加收费；失败沿用原订单重试。</small>
            </div>
          )}

          {/* Payment section */}
          {job?.status === 'awaiting_payment' && (
            <div className="trine-payment-actions">
              <PayOrderButton orderId={job.order_id} onConfirmed={() => void enqueue()} />
              <button className="trine-secondary-btn" onClick={() => void enqueue()}>
                已支付，恢复生成
              </button>
            </div>
          )}

          {/* Failed section */}
          {job?.status === 'failed' && (
            <div className="trine-error-section">
              <p role="alert" className="trine-error-msg">
                <AlertTriangle size={13} /> {job.error}
              </p>
              <button className="trine-secondary-btn" onClick={() => void enqueue()}>
                使用原付款重试
              </button>
            </div>
          )}

          {/* Error message */}
          {error && (
            <p role="alert" className="trine-error-msg">
              <AlertTriangle size={13} /> {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
