import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, Bot, Check, ChevronRight, CircleDollarSign, Copy, DatabaseZap,
  Fingerprint, FlaskConical, KeyRound, Link2, LockKeyhole, Plus, Search, ShieldCheck,
  Sparkles, UserRoundCheck, X, Zap,
} from 'lucide-react'
import { api } from '../api'
import type {
  QuantAgent, QuantCategory, QuantChainStatus, QuantJudgeOverview, QuantReport,
  QuantSubscription, QuantVerification,
} from '../types'

interface Props {
  onError: (message: string) => void
  onOpenLab: () => void
}

const categories: Array<{ value: '' | QuantCategory; label: string }> = [
  { value: '', label: '全部策略' },
  { value: 'stock_selection', label: '选股' },
  { value: 'timing', label: '择时' },
  { value: 'allocation', label: '配置' },
  { value: 'multi_factor', label: '多因子' },
  { value: 'arbitrage', label: '套利' },
]

const categoryLabel: Record<QuantCategory, string> = {
  stock_selection: '选股', timing: '择时', allocation: '仓位配置', multi_factor: '多因子', arbitrage: '套利',
}
const riskLabel = { low: '低风险', medium: '中风险', high: '高风险', extreme: '极高风险' }
const assetLabel: Record<string, string> = { crypto: '加密', equity: '股票', etf: 'ETF', bond: '债券', commodity: '商品' }

function pct(value = 0, digits = 1) {
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${(value * 100).toFixed(digits)}%`
}

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '—'
}

function Sparkline({ report }: { report: QuantReport | null }) {
  const path = useMemo(() => {
    const points = report?.public_curve ?? []
    if (points.length < 2) return ''
    const values = points.map((point) => point.return)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    return points.map((point, index) => {
      const x = (index / (points.length - 1)) * 170
      const y = 48 - ((point.return - min) / span) * 42
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
  }, [report])
  return <svg className="qj-sparkline" viewBox="0 0 170 52" preserveAspectRatio="none" aria-label="公开收益曲线"><path d={path} /></svg>
}

function ProofRail({ report, verification, chain }: { report: QuantReport | null; verification: QuantVerification | null; chain: QuantChainStatus | null }) {
  const signed = verification?.calculation_verified ?? Boolean(report?.attestation_signature)
  const zkVerified = verification?.external_proof_verified ?? report?.evidence_level === 'zk_verified'
  const anchored = verification?.chain.status === 'confirmed' || report?.chain_status === 'confirmed'
  return (
    <div className="qj-proof-rail">
      <div className="qj-proof-node is-ok">
        <span><Fingerprint size={15} /></span><div><strong>策略承诺</strong><small>源码与 Agent 参数不公开</small></div><Check size={14} />
      </div>
      <i />
      <div className={`qj-proof-node ${zkVerified || signed ? 'is-ok' : ''}`}>
        <span><ShieldCheck size={15} /></span><div><strong>{zkVerified ? 'zkVM 执行证明' : '平台业绩重算'}</strong><small>{zkVerified ? '固定 image · receipt 已验证' : 'Ed25519 平台回执，非 ZKP'}</small></div>{zkVerified || signed ? <Check size={14} /> : <em>待验</em>}
      </div>
      <i />
      <div className={`qj-proof-node ${anchored ? 'is-ok' : 'is-pending'}`}>
        <span><Link2 size={15} /></span><div><strong>链上锚定</strong><small>{anchored ? `Supervisor #${verification?.chain.block_number ?? report?.chain_block_number}` : chain?.compatible ? '等待开发者签名提交' : chain?.connected ? `链 ID ${chain.chain_id} 不匹配` : 'Supervisor 当前未连接'}</small></div>{anchored ? <Check size={14} /> : <em>待锚定</em>}
      </div>
    </div>
  )
}

function Metric({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return <div className="qj-metric"><span>{label}</span><strong className={tone}>{value}</strong></div>
}

interface PublishState {
  name: string; developerAlias: string; agentType: 'ai_agent' | 'traditional'; category: QuantCategory
  description: string; assetClasses: string[]; riskLevel: 'low' | 'medium' | 'high' | 'extreme'; price: number; secret: string
  commitmentMode: 'browser' | 'zkp'; zkpCommitment: string
}

const initialPublish: PublishState = {
  name: '', developerAlias: '', agentType: 'ai_agent', category: 'multi_factor', description: '',
  assetClasses: ['equity'], riskLevel: 'medium', price: 199, secret: '', commitmentMode: 'browser', zkpCommitment: '',
}

async function privateCommitment(secret: string) {
  const saltBytes = crypto.getRandomValues(new Uint8Array(24))
  const salt = Array.from(saltBytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${salt}:${secret}`))
  const commitment = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  return { salt, commitment }
}

export function QuantJudgeWorkspace({ onError, onOpenLab }: Props) {
  const [overview, setOverview] = useState<QuantJudgeOverview | null>(null)
  const [chain, setChain] = useState<QuantChainStatus | null>(null)
  const [agents, setAgents] = useState<QuantAgent[]>([])
  const [selected, setSelected] = useState<QuantAgent | null>(null)
  const [verification, setVerification] = useState<QuantVerification | null>(null)
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState<'' | QuantCategory>('')
  const [reportType, setReportType] = useState('')
  const [query, setQuery] = useState('')
  const [publishOpen, setPublishOpen] = useState(false)
  const [publish, setPublish] = useState<PublishState>(initialPublish)
  const [credential, setCredential] = useState<{ token: string; salt: string | null } | null>(null)
  const [subscribeOpen, setSubscribeOpen] = useState(false)
  const [investorAlias, setInvestorAlias] = useState(() => localStorage.getItem('quantjudge-investor') ?? '')
  const [subscriptions, setSubscriptions] = useState<QuantSubscription[]>([])
  const [activeView, setActiveView] = useState<'market' | 'subscriptions'>('market')

  const load = useCallback(async (preserveSelection = true) => {
    setLoading(true)
    try {
      const [nextOverview, nextAgents, nextChain] = await Promise.all([
        api.getQuantJudgeOverview(),
        api.listQuantAgents({ category, reportType, query }),
        api.getQuantChainStatus(),
      ])
      setOverview(nextOverview); setAgents(nextAgents); setChain(nextChain)
      setSelected((current) => preserveSelection ? nextAgents.find((item) => item.id === current?.id) ?? nextAgents[0] ?? null : nextAgents[0] ?? null)
    } catch (reason) { onError(reason instanceof Error ? reason.message : '无法读取 QuantJudge') }
    finally { setLoading(false) }
  }, [category, onError, query, reportType])

  useEffect(() => { const timer = window.setTimeout(() => load(), 180); return () => window.clearTimeout(timer) }, [load])

  const chooseAgent = (agent: QuantAgent) => {
    setSelected(agent)
    setVerification(null)
    api.getQuantAgent(agent.id).then((detail) => {
      setSelected((current) => current?.id === detail.id ? detail : current)
    }).catch(() => undefined)
  }

  const verify = async () => {
    if (!selected?.latest_report) return
    try { setVerification(await api.verifyQuantReport(selected.latest_report.id)) }
    catch (reason) { onError(reason instanceof Error ? reason.message : '验证失败') }
  }

  const createAgent = async () => {
    if (publish.commitmentMode === 'browser' && (!publish.secret || publish.secret.length < 12)) { onError('私密承诺材料至少 12 个字符'); return }
    if (publish.commitmentMode === 'zkp' && !/^[0-9a-f]{64}$/.test(publish.zkpCommitment)) { onError('请粘贴本地 atlas-zkvm inspect 输出的 64 位 strategy_commitment'); return }
    try {
      const local = publish.commitmentMode === 'browser' ? await privateCommitment(publish.secret) : { salt: null, commitment: publish.zkpCommitment }
      const result = await api.createQuantAgent({
        name: publish.name, developer_alias: publish.developerAlias, agent_type: publish.agentType,
        category: publish.category, asset_classes: publish.assetClasses, description: publish.description,
        risk_level: publish.riskLevel, monthly_price: publish.price, price_currency: 'CNY', strategy_commitment: local.commitment,
      })
      setCredential({ token: result.developer_token, salt: local.salt })
      setPublish((current) => ({ ...current, secret: '' }))
      await load(false)
      setSelected(result.agent)
    } catch (reason) { onError(reason instanceof Error ? reason.message : '发布失败') }
  }

  const subscribe = async () => {
    if (!selected || investorAlias.trim().length < 2) { onError('请输入至少 2 个字符的投资人别名'); return }
    try {
      localStorage.setItem('quantjudge-investor', investorAlias.trim())
      await api.subscribeQuantAgent(selected.id, { investor_alias: investorAlias.trim(), billing_cycle: 'monthly' })
      setSubscriptions(await api.listQuantSubscriptions(investorAlias.trim()))
      setSubscribeOpen(false); setActiveView('subscriptions'); await load()
    } catch (reason) { onError(reason instanceof Error ? reason.message : '订阅失败') }
  }

  const openSubscriptions = async () => {
    setActiveView('subscriptions')
    if (investorAlias.trim().length >= 2) {
      try { setSubscriptions(await api.listQuantSubscriptions(investorAlias.trim())) } catch { setSubscriptions([]) }
    }
  }

  const report = selected?.latest_report ?? null
  const metrics = report?.metrics

  return (
    <main className="qj-workspace">
      <section className="qj-commandbar">
        <div className="qj-title"><span><Sparkles size={17} /></span><div><strong>QuantJudge</strong><small>策略 / AI Agent 可验证跑分市场</small></div></div>
        <div className="qj-kpis">
          <span><small>入驻策略</small><strong>{overview?.agents ?? '—'}</strong></span>
          <span><small>实盘报告</small><strong>{overview?.live_reports ?? '—'}</strong></span>
          <span><small>中位评分</small><strong>{overview?.median_score?.toFixed(1) ?? '—'}</strong></span>
        </div>
        <div className={`qj-chain-pill ${chain?.compatible ? 'is-online' : ''}`}><i /> Supervisor {chain?.compatible ? `#${chain.block_number}` : chain?.connected ? '链不匹配' : '离线'}</div>
        <button className="qj-lab-link" onClick={onOpenLab}><FlaskConical size={14} />进入策略实验室</button>
        <button className="qj-primary" onClick={() => { setPublishOpen(true); setCredential(null) }}><Plus size={15} />发布 Agent</button>
      </section>

      <section className="qj-tabs">
        <button className={activeView === 'market' ? 'is-active' : ''} onClick={() => setActiveView('market')}><Activity size={14} />策略广场</button>
        <button className={activeView === 'subscriptions' ? 'is-active' : ''} onClick={openSubscriptions}><UserRoundCheck size={14} />我的订阅</button>
        <div><LockKeyhole size={13} />默认隐藏源码、Agent 参数、提示词和原始决策</div>
      </section>

      {activeView === 'subscriptions' ? (
        <section className="qj-subscriptions-view">
          <header><div><strong>我的订阅</strong><small>本地投资人身份与策略授权记录</small></div><label>投资人别名<input value={investorAlias} onChange={(event) => setInvestorAlias(event.target.value)} /><button onClick={openSubscriptions}>查询</button></label></header>
          <div className="qj-subscription-list">
            {subscriptions.length ? subscriptions.map((item) => <article key={item.id}><span><ShieldCheck size={17} /></span><div><strong>{item.agent_name}</strong><small>{item.id} · {item.payment_mode === 'sandbox' ? '本地沙盒订阅' : '外部支付待验证'}</small></div><b>{item.amount.toFixed(0)} {item.currency}</b><em className={item.status === 'active' ? 'is-active' : ''}>{item.status === 'active' ? '已激活' : '待核验'}</em><time>到期 {new Date(item.expires_at).toLocaleDateString('zh-CN')}</time></article>) : <div className="qj-empty"><CircleDollarSign size={28} /><strong>还没有订阅记录</strong><span>从策略广场选择 Agent 并建立订阅。</span><button onClick={() => setActiveView('market')}>返回广场</button></div>}
          </div>
        </section>
      ) : (
        <div className="qj-grid">
          <section className="qj-market">
            <div className="qj-filters">
              <label className="qj-search"><Search size={14} /><input placeholder="搜索 Agent、开发者或策略说明" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
              <div className="qj-category-tabs">{categories.map((item) => <button key={item.value || 'all'} className={category === item.value ? 'is-active' : ''} onClick={() => setCategory(item.value)}>{item.label}</button>)}</div>
              <select value={reportType} onChange={(event) => setReportType(event.target.value)}><option value="">全部记录</option><option value="live">实盘</option><option value="backtest">回测</option></select>
            </div>
            <div className="qj-table-head"><span># / Agent</span><span>类型</span><span>公开收益走势</span><span>年化</span><span>回撤</span><span>Sharpe</span><span>Judge</span><span /> </div>
            <div className="qj-agent-list">
              {loading ? <div className="qj-empty"><Zap className="spin" size={24} /><span>读取可验证跑分…</span></div> : agents.map((agent) => {
                const itemReport = agent.latest_report
                return <button key={agent.id} className={`qj-agent-row ${selected?.id === agent.id ? 'is-selected' : ''}`} onClick={() => chooseAgent(agent)}>
                  <span className="qj-agent-name"><b>{agent.rank}</b><i>{agent.agent_type === 'ai_agent' ? <Bot size={16} /> : <Activity size={16} />}</i><span><strong>{agent.name}</strong><small>{agent.developer_alias} {agent.is_demo ? '· DEMO' : ''}</small></span></span>
                  <span><em>{categoryLabel[agent.category]}</em><small>{agent.asset_classes.map((item) => assetLabel[item] ?? item).join(' / ')}</small></span>
                  <Sparkline report={itemReport} />
                  <strong className={(itemReport?.metrics.annualized_return ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(itemReport?.metrics.annualized_return)}</strong>
                  <strong className="negative">{pct(itemReport?.metrics.max_drawdown)}</strong>
                  <strong>{itemReport?.metrics.sharpe?.toFixed(2) ?? '—'}</strong>
                  <span className="qj-score"><b>{itemReport?.score?.toFixed(1) ?? '—'}</b><i style={{ '--score': `${itemReport?.score ?? 0}%` } as React.CSSProperties} /></span>
                  <ChevronRight size={15} />
                </button>
              })}
              {!loading && !agents.length ? <div className="qj-empty"><Search size={26} /><strong>没有匹配的策略</strong><span>请调整筛选条件。</span></div> : null}
            </div>
          </section>

          <aside className="qj-detail">
            {selected ? <>
              <header><div className="qj-avatar">{selected.agent_type === 'ai_agent' ? <Bot size={20} /> : <Activity size={20} />}</div><div><span><em>{selected.latest_report?.report_type === 'live' ? 'LIVE' : 'BACKTEST'}</em>{selected.is_demo ? <i>DEMO</i> : null}</span><strong>{selected.name}</strong><small>by {selected.developer_alias} · {selected.subscriber_count} 订阅</small></div></header>
              <p>{selected.description}</p>
              <div className="qj-detail-tags"><span>{categoryLabel[selected.category]}</span><span className={`risk-${selected.risk_level}`}>{riskLabel[selected.risk_level]}</span>{selected.asset_classes.map((item) => <span key={item}>{assetLabel[item] ?? item}</span>)}</div>
              <div className="qj-detail-metrics">
                <Metric label="总收益" value={pct(metrics?.total_return)} tone={(metrics?.total_return ?? 0) >= 0 ? 'positive' : 'negative'} />
                <Metric label="年化收益" value={pct(metrics?.annualized_return)} tone={(metrics?.annualized_return ?? 0) >= 0 ? 'positive' : 'negative'} />
                <Metric label="最大回撤" value={pct(metrics?.max_drawdown)} tone="negative" />
                <Metric label="Sharpe" value={metrics?.sharpe?.toFixed(2) ?? '—'} />
              </div>
              <section className="qj-proof-box"><div className="qj-section-title"><span><ShieldCheck size={14} />可验证证据链</span><button onClick={verify}>{verification ? '重新验证' : '立即验证'}</button></div><ProofRail report={report} verification={verification} chain={chain} /></section>
              <section className="qj-ledger">
                <div><span>策略承诺</span><code>{shortHash(selected.strategy_commitment)}</code><button title="复制" onClick={() => navigator.clipboard.writeText(selected.strategy_commitment)}><Copy size={12} /></button></div>
                <div><span>决策 Merkle 根</span><code>{shortHash(report?.decision_merkle_root)}</code><em>{report?.decision_count ?? 0} 次决策</em></div>
                <div><span>证明回执</span><code>{shortHash(report?.receipt_hash)}</code><em>{report?.attestation_key_id}</em></div>
              </section>
              {verification ? <div className={`qj-verified-note ${verification.calculation_verified ? '' : 'is-error'}`}>{verification.calculation_verified ? <Check size={14} /> : <X size={14} />}<span><strong>{verification.calculation_verified ? (verification.external_proof_verified ? 'zkVM 证明与公开结果均已验证' : '平台回执验算通过') : '展示记录完整性异常'}</strong>{verification.calculation_verified ? `${verification.external_proof_verified ? '固定 image 的 RISC Zero receipt、公开 journal、报告绑定与 Ed25519 平台回执有效。' : '回执哈希、展示记录与 Ed25519 签名有效；该证据等级不是 ZKP。'}${verification.chain.status !== 'confirmed' ? '尚未获得 Supervisor 链上确认。' : '已获得链上确认。'}` : '请勿依赖当前展示数据；回执与数据库公开字段不一致。'}</span></div> : null}
              <div className="qj-subscribe"><div><small>月度订阅</small><strong>{selected.monthly_price.toFixed(0)} <em>{selected.price_currency}</em></strong></div><button onClick={() => setSubscribeOpen(true)}><CircleDollarSign size={15} />订阅策略</button></div>
              <small className="qj-disclaimer">跑分不构成投资建议。演示样本未上链；仅当证据节点显示“已确认”时，才代表 Supervisor 链回执校验成功。
              </small>
            </> : <div className="qj-empty"><DatabaseZap size={26} /><span>选择一个 Agent 查看证据。</span></div>}
          </aside>
        </div>
      )}

      {publishOpen ? <div className="qj-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setPublishOpen(false)}><section className="qj-modal">
        <header><div><Fingerprint size={18} /><span><strong>发布私密策略 / Agent</strong><small>浏览器本地生成承诺，私密内容不会发送到服务器</small></span></div><button onClick={() => setPublishOpen(false)}><X size={17} /></button></header>
        {credential ? <div className="qj-credential"><ShieldCheck size={30} /><strong>Agent 已发布</strong><p>开发者凭证只显示一次。后续提交证明与跑分都需要它；ZKP 的 salt 只保留在本地 witness。</p><label>开发者凭证<code>{credential.token}</code><button onClick={() => navigator.clipboard.writeText(credential.token)}><Copy size={13} />复制</button></label>{credential.salt ? <label>承诺盐值<code>{credential.salt}</code><button onClick={() => navigator.clipboard.writeText(credential.salt ?? '')}><Copy size={13} />复制</button></label> : null}<button className="qj-primary" onClick={() => setPublishOpen(false)}>我已安全保存</button></div> : <div className="qj-publish-form">
          <div className="qj-form-row"><label>Agent 名称<input value={publish.name} onChange={(event) => setPublish({ ...publish, name: event.target.value })} placeholder="例：Aurora Alpha" /></label><label>开发者别名<input value={publish.developerAlias} onChange={(event) => setPublish({ ...publish, developerAlias: event.target.value })} placeholder="不需真实姓名" /></label></div>
          <div className="qj-form-row"><label>形态<select value={publish.agentType} onChange={(event) => setPublish({ ...publish, agentType: event.target.value as PublishState['agentType'] })}><option value="ai_agent">AI Agent</option><option value="traditional">传统量化策略</option></select></label><label>核心能力<select value={publish.category} onChange={(event) => setPublish({ ...publish, category: event.target.value as QuantCategory })}>{categories.slice(1).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label></div>
          <label>公开说明<textarea value={publish.description} onChange={(event) => setPublish({ ...publish, description: event.target.value })} placeholder="只描述适用市场、风险和目标，不要填入源码、提示词或参数。" /></label>
          <div className="qj-form-row"><label>资产类别<select value={publish.assetClasses[0]} onChange={(event) => setPublish({ ...publish, assetClasses: [event.target.value] })}><option value="equity">股票</option><option value="crypto">加密货币</option><option value="etf">ETF / 多资产</option><option value="commodity">商品</option></select></label><label>风险等级<select value={publish.riskLevel} onChange={(event) => setPublish({ ...publish, riskLevel: event.target.value as PublishState['riskLevel'] })}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="extreme">极高</option></select></label><label>月费 CNY<input type="number" min="0" value={publish.price} onChange={(event) => setPublish({ ...publish, price: Number(event.target.value) })} /></label></div>
          <label>承诺来源<select value={publish.commitmentMode} onChange={(event) => setPublish({ ...publish, commitmentMode: event.target.value as PublishState['commitmentMode'] })}><option value="browser">浏览器承诺（平台签名报告）</option><option value="zkp">zkVM 策略承诺（ZKP 报告）</option></select></label>
          {publish.commitmentMode === 'browser' ? <label className="qj-secret-field"><span><KeyRound size={14} />私密承诺材料</span><textarea value={publish.secret} onChange={(event) => setPublish({ ...publish, secret: event.target.value })} placeholder="粘贴源码版本指纹、Agent 配置摘要或任意私密长文。它只在当前浏览器中计算 SHA-256 承诺。" /><small><LockKeyhole size={12} />不会离开本浏览器；服务器只收到 64 位承诺哈希。该模式本身不是 ZKP。</small></label> : <label className="qj-secret-field"><span><Fingerprint size={14} />strategy_commitment</span><textarea value={publish.zkpCommitment} onChange={(event) => setPublish({ ...publish, zkpCommitment: event.target.value.trim().toLowerCase() })} placeholder="先在本地运行 atlas-zkvm inspect --witness witness.json，再粘贴输出的 strategy_commitment。" /><small><LockKeyhole size={12} />必须与 proof journal 完全一致；参数与 salt 不上传。</small></label>}
          <footer><button onClick={() => setPublishOpen(false)}>取消</button><button className="qj-primary" onClick={createAgent} disabled={publish.name.length < 2 || publish.developerAlias.length < 2 || publish.description.length < 12}><Fingerprint size={14} />生成承诺并发布</button></footer>
        </div>}
      </section></div> : null}

      {subscribeOpen && selected ? <div className="qj-modal-backdrop"><section className="qj-modal qj-subscribe-modal"><header><div><CircleDollarSign size={18} /><span><strong>订阅 {selected.name}</strong><small>授权与支付记录分离</small></span></div><button onClick={() => setSubscribeOpen(false)}><X size={17} /></button></header><div><label>投资人别名<input autoFocus value={investorAlias} onChange={(event) => setInvestorAlias(event.target.value)} placeholder="用于查询本地订阅" /></label><div className="qj-order"><span>{selected.name} · 月度</span><strong>{selected.monthly_price.toFixed(0)} {selected.price_currency}</strong></div><p>当前未配置真实支付通道，本次建立的是明确标记的本地沙盒订阅，不会扣款。</p><button className="qj-primary" onClick={subscribe}>确认沙盒订阅</button></div></section></div> : null}
    </main>
  )
}
