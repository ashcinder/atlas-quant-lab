import { useEffect, useState } from 'react'
import { request } from '../request'

interface Status { configured: boolean; exchange: string | null }
interface Balance { observed_at: string; exchange: string; assets: Array<{currency: string; total: string; free: string | null; used: string | null}> }

export function ExchangeAccountSettings() {
  const [exchange, setExchange] = useState('binance')
  const [key, setKey] = useState('')
  const [secret, setSecret] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [consent, setConsent] = useState(false)
  const [configured, setConfigured] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [balance, setBalance] = useState<Balance | null>(null)
  useEffect(() => {
    let active = true
    request<Status>('/exchange-account').then(s => { if (active) { setConfigured(s.configured); if (s.exchange) setExchange(s.exchange) } }).catch(() => { if (active) setMessage('账户连接服务尚未就绪，请重启后端。') })
    return () => { active = false }
  }, [])
  async function perform(action: 'save' | 'read' | 'clear') {
    setBusy(true); setMessage(''); setBalance(null)
    try {
      if (action === 'save') {
        await request('/exchange-account', {method:'PUT', body:JSON.stringify({exchange, api_key:key, secret, passphrase, consent})})
        setKey(''); setSecret(''); setPassphrase(''); setConfigured(true); setMessage('配置已暂存，尚未验证。点击读取余额验证连接。')
      } else if (action === 'read') {
        setBalance(await request<Balance>('/exchange-account/balance', {method:'POST'})); setMessage('账户读取成功；未提交任何交易。')
      } else {
        await request('/exchange-account', {method:'DELETE'}); setConfigured(false); setKey(''); setSecret(''); setPassphrase(''); setMessage('已断开并清除会话密钥。')
      }
    } catch (e) { setMessage(e instanceof Error ? e.message : '连接失败') }
    finally { setBusy(false) }
  }
  return <section><h3>交易所账户 · 只读连接</h3>
    <p>当前可验证余额，尚未开放订阅策略自动下单。仅使用只读 Key，不要启用提现权限。密钥只暂存在当前后端会话，8 小时或重启后失效。</p>
    <label>交易所<select disabled={busy || configured} value={exchange} onChange={e => {setExchange(e.target.value); setKey(''); setSecret(''); setPassphrase('')}}><option value="binance">Binance 现货</option><option value="okx">OKX 交易账户</option></select></label>
    <label>API Key<input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></label>
    <label>API Secret<input type="password" autoComplete="off" value={secret} onChange={e => setSecret(e.target.value)} /></label>
    {exchange === 'okx' && <label>Passphrase<input type="password" autoComplete="off" value={passphrase} onChange={e => setPassphrase(e.target.value)} /></label>}
    <label className="ai-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /><span>同意后端使用这些凭证向所选交易所读取账户资产；当前不下单、不转账。</span></label>
    <div className="ai-setting-actions"><button disabled={busy || !key || !secret || !consent || (exchange === 'okx' && !passphrase)} onClick={() => void perform('save')}>暂存连接</button><button disabled={busy || !configured} onClick={() => void perform('read')}>读取真实余额</button><button disabled={busy || !configured} onClick={() => void perform('clear')}>断开连接</button></div>
    <p role="status">{busy ? '处理中…' : message}</p>
    {balance && <div><p>{balance.exchange} · {new Date(balance.observed_at).toLocaleString()}（读取时间）</p>{balance.assets.length ? <table><thead><tr><th>资产</th><th>合计</th><th>可用</th></tr></thead><tbody>{balance.assets.map(a => <tr key={a.currency}><td>{a.currency}</td><td>{a.total}</td><td>{a.free ?? '未知'}</td></tr>)}</tbody></table> : <p>本次账户返回的非零资产为空；不代表其他子账户没有资金。</p>}</div>}
    <p>A 股：需要开通 MiniQMT 的券商账户及运行中的 MiniQMT 客户端。此处不能用股票账户密码代替券商接口。</p>
  </section>
}
