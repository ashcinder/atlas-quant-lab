import { useEffect, useState } from 'react'
import { request } from '../request'
import './trading.css'

type Venue = 'binance' | 'okx'
type Capabilities = { authorized: boolean; user_id: string; venues: { venue: Venue; mode: string; configured: boolean; can_trade: boolean }[] }
type Trade = { id: string; order: { venue: Venue; symbol: string; side: string; quantity: string; price: string }; mode: string; expires: number; state: string; result: { exchange_status?: string; filled_quantity?: string; message?: string } }
const names = { binance: '币安 Binance', okx: '欧易 OKX' }
const states: Record<string, string> = { cancel_rejected: '撤单被拒绝，请查询', rejected: '交易所已拒单', cancel_unknown: '撤单结果未知，请查询', cancel_submitting: '撤单处理中／待核实', preview: '待确认', submitting: '提交中／待核实', submitted: '交易所已受理', unknown: '结果未知，请核实', reconciled: '已查询', cancel_requested: '撤单已请求，请查询' }
const post = <T,>(path: string, body = {}) => request<T>(`/trading${path}`, { method: 'POST', body: JSON.stringify(body) })

export default function TradingWorkspace() {
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [venue, setVenue] = useState<Venue>('binance')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('buy')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [preview, setPreview] = useState<Trade | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [orders, setOrders] = useState<Trade[]>([])
  const [balances, setBalances] = useState<{ asset: string; available: string; locked: string }[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const selected = caps?.venues.find((item) => item.venue === venue)
  const phrase = preview?.mode === 'live' ? '确认实盘下单' : '确认模拟下单'
  async function load() {
    const next = await request<Capabilities>('/trading/capabilities')
    setCaps(next)
    if (next.authorized) setOrders(await request<Trade[]>('/trading/orders'))
    setLoaded(true)
  }
  useEffect(() => {
    let active = true
    request<Capabilities>('/trading/capabilities').then(async (next) => {
      if (!active) return
      setCaps(next)
      if (next.authorized) {
        const rows = await request<Trade[]>('/trading/orders')
        if (active) setOrders(rows)
      }
      if (active) setLoaded(true)
    }).catch((cause: Error) => { if (active) setError(cause.message) })
    document.title = '交易账户 · Atlas'
    return () => { active = false }
  }, [])
  async function action(work: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError('')
    try { await work() } catch (cause) { setError(cause instanceof Error ? cause.message : '请求失败') }
    finally { setBusy(false) }
  }
  function invalidate() { setPreview(null); setConfirmation('') }
  return <main className="trading-workspace">
    <header className="trade-heading"><div><h1>交易账户</h1><p>连接账户，核对订单，再由你确认提交。</p></div><button disabled={busy} onClick={() => void action(load)}>刷新连接状态</button></header>
    {error && <p className="trade-error" role="alert">{error}</p>}
    {notice && <p className="trade-error" role="alert">{notice}</p>}
    {!caps && !error && <p role="status">正在读取接入状态…</p>}
    {caps && !caps.authorized && <section className="trade-setup"><h2>先绑定你的交易账户</h2><p>完成账户绑定后，即可查询余额并预览订单。</p><details><summary>查看本机接入配置</summary><p>当前用户 ID：<code>{caps.user_id}</code></p><p>将此 ID 配置为服务端 ATLAS_TRADING_OWNER_ID。密钥仅写入服务端环境，不要放在聊天、浏览器或策略代码里。完整步骤见项目 docs/TRADING.md。</p></details></section>}
    <div className="trade-columns"><section className="trade-ticket"><h2>现货限价单</h2>
      <form onSubmit={(event) => { event.preventDefault(); void action(async () => {
        const next = await post<Trade>('/orders/preview', { venue, symbol, side, quantity, price })
        setPreview(next); setConfirmation(''); await load()
      }) }}>
        <fieldset disabled={busy || !!preview}>
          <label>交易所<select value={venue} onChange={(event) => { setVenue(event.target.value as Venue); setBalances(null); invalidate() }}><option value="binance">币安 Binance</option><option value="okx">欧易 OKX</option></select></label>
          <p className={selected?.mode === 'live' ? 'trade-live' : 'trade-environment'}>{selected?.mode === 'live' ? '实盘 · 将使用真实资金' : '测试环境 · 不使用真实资金'} · {selected?.configured ? '已配置 · 待验证' : '账户未配置'}</p>
          <label>交易对<input required value={symbol} placeholder="例如 BTC-USDT" pattern="[A-Z0-9]{2,15}-USDT" onChange={(event) => { setSymbol(event.target.value.toUpperCase()); invalidate() }} /></label>
          <label>方向<select value={side} onChange={(event) => { setSide(event.target.value); invalidate() }}><option value="buy">买入</option><option value="sell">卖出</option></select></label>
          <div className="trade-fields"><label>数量（基础币）<input required inputMode="decimal" value={quantity} onChange={(event) => { setQuantity(event.target.value); invalidate() }} /></label><label>限价（USDT）<input required inputMode="decimal" value={price} onChange={(event) => { setPrice(event.target.value); invalidate() }} /></label></div>
          <details className="trade-help"><summary>交易规则</summary><p>仅支持 USDT 现货限价单，持续有效至成交或撤销。交易所会检查余额、最小数量和价格精度。</p></details>
          <button className="trade-primary" disabled={!selected?.can_trade} type="submit">预览订单</button>
        </fieldset>
      </form>
      {preview && <section className="trade-review" aria-label="确认订单"><h3>{preview.mode === 'live' ? '核对实盘订单' : '核对模拟订单'}</h3><p>{names[preview.order.venue]} · {preview.order.symbol} · {preview.order.side === 'buy' ? '买入' : '卖出'}</p><p>数量 {preview.order.quantity} · 限价 {preview.order.price} USDT</p><p>预览两分钟内有效。请输入“{phrase}”后提交。</p><label>确认文字<input value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></label><div className="trade-actions"><button disabled={busy} onClick={invalidate}>返回修改</button><button className="trade-primary" disabled={busy || confirmation !== phrase} onClick={() => void action(async () => {
        const result = await post<Trade>(`/orders/${preview.id}/confirm`, { confirmation })
        setNotice(['unknown', 'submitting', 'cancel_unknown', 'cancel_submitting'].includes(result.state)
          ? `订单 ${result.id} 结果未确认。请在下方查询状态或到交易所核实，不要重复下单。`
          : result.state === 'rejected' ? result.result.message ?? '交易所已拒单，请检查参数。' : '')
        invalidate(); await load()
      })}>确认提交订单</button></div></section>}
      {!selected?.can_trade && caps?.authorized && <p>下单尚未启用。请按接入说明配置测试账户及交易开关。</p>}
    </section><aside className="trade-account"><h2>账户余额</h2><p>{names[venue]} · {selected?.mode === 'live' ? '实盘' : '测试环境'}</p><button disabled={busy || !selected?.configured} onClick={() => void action(async () => {
      setBalances(null)
      const response = await request<{ balances: NonNullable<typeof balances> }>(`/trading/${venue}/account`)
      setBalances(response.balances)
    })}>连接并查询余额</button>
      {balances === null ? <p>余额尚未查询。</p> : <><p role="status">账户查询成功</p><div className="trade-table"><table><thead><tr><th>资产</th><th>可用</th><th>冻结</th></tr></thead><tbody>{balances.map((row) => <tr key={row.asset}><td>{row.asset}</td><td>{row.available}</td><td>{row.locked}</td></tr>)}</tbody></table>{!balances.length && <p>账户暂无余额记录。</p>}</div></>}
      <section className="trade-broker"><h2>A 股券商</h2><strong>miniQMT · 等待客户端接入</strong><p>尚未连接，暂不可下单。</p><details className="trade-help"><summary>查看券商接入条件</summary><p>以国联证券官方 QMT 接口为适配参考，需开通程序化交易权限，并在 Windows 上运行客户端。本项目已提供只读探测脚本。</p><a href="https://www.glsc.com.cn/qmt/document.html" target="_blank" rel="noreferrer">查看券商官方接入资料</a></details></section>
    </aside></div>
    <section className="trade-orders"><h2>最近订单</h2><p>受理不等于成交。结果未知时先查询，请勿重复下单。</p><div className="trade-table"><table><thead><tr><th>交易对／环境</th><th>委托</th><th>状态／成交数量</th><th>操作</th></tr></thead><tbody>{orders.map((row) => <tr key={row.id}><td>{row.order.symbol}<small>{names[row.order.venue]} · {row.mode === 'live' ? '实盘' : '模拟'}</small><details><summary>订单编号</summary><code>{row.id}</code></details></td><td>{row.order.side === 'buy' ? '买入' : '卖出'} {row.order.quantity}<small>@ {row.order.price} USDT</small></td><td>{states[row.state] ?? row.state}<small>{row.result.exchange_status ?? row.result.message ?? '尚未发送'}{row.result.filled_quantity && ` · 已成交 ${row.result.filled_quantity}`}</small></td><td>{!['preview', 'rejected'].includes(row.state) && <div className="trade-actions"><button disabled={busy} onClick={() => void action(async () => { await post(`/orders/${row.id}/refresh`); await load() })}>查询状态</button><button disabled={busy || row.state === 'submitting' || ['filled', 'canceled', 'cancelled', 'expired', 'expired_in_match', 'rejected', 'mmp_canceled'].includes(row.result.exchange_status?.toLowerCase() ?? '')} onClick={() => {
      if (window.confirm(`确认撤销 ${row.order.symbol} 的${row.mode === 'live' ? '实盘' : '模拟'}订单 ${row.id}？`)) void action(async () => { await post(`/orders/${row.id}/cancel`, { confirmation: '确认撤单' }); await load() })
    }}>撤单</button></div>}</td></tr>)}</tbody></table></div>{loaded && !orders.length && <p>暂无订单。预览不会向交易所提交交易。</p>}</section>
    {busy && <p role="status">正在处理请求，请稍候…</p>}
  </main>
}
