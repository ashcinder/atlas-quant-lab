import { useState } from 'react'
import { request } from '../request'

export default function DemoAccountSetup({ onConnected, initialVenue = 'binance', defaultOpen = false, onBusyChange }: { onConnected: () => Promise<void>; initialVenue?: string; defaultOpen?: boolean; onBusyChange?: (busy: boolean) => void }) {
  const [venue, setVenue] = useState(initialVenue)
  const [apiKey, setApiKey] = useState('')
  const [secret, setSecret] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  return <details className="trade-setup" open={defaultOpen}><summary>接入模拟交易账户 · 币安 / 欧易</summary>
    <p>在这里配置测试密钥，验证通过后即可选择该账户运行订阅策略。每个登录用户可分别保存一个币安和一个欧易模拟账户。</p>
    <p>尚未创建密钥：<a href="https://testnet.binance.vision/" target="_blank" rel="noreferrer">Binance Spot Testnet</a> · <a href="https://www.okx.com/docs-v5#overview-demo-trading-services" target="_blank" rel="noreferrer">欧易模拟交易 API 指引</a></p>
    <form className="trade-run-form trade-demo-form" onSubmit={async event => {
      event.preventDefault(); if (busy) return
      setBusy(true); onBusyChange?.(true); setError(''); setMessage('')
      try {
        await request(`/trading/demo-accounts/${venue}`, { method: 'PUT', body: JSON.stringify({ api_key: apiKey, secret, passphrase: venue === 'okx' ? passphrase : '', consent }) })
        setApiKey(''); setSecret(''); setPassphrase(''); setConsent(false)
        setMessage('模拟账户已验证并保存。请在运行环境选择“交易所测试”；配置过程未下单。')
        await onConnected()
      } catch (cause) { setError(cause instanceof Error ? cause.message : '账户配置失败，请重试') }
      finally { setBusy(false); onBusyChange?.(false) }
    }}>
      <fieldset disabled={busy}>
        <label>模拟交易所<select value={venue} onChange={event => { setVenue(event.target.value); setApiKey(''); setSecret(''); setPassphrase(''); setConsent(false); setMessage(''); setError('') }}><option value="binance">币安 Spot Testnet</option><option value="okx">欧易 Demo Trading</option></select></label>
        <label>模拟 API Key<input type="password" required maxLength={512} autoComplete="off" value={apiKey} onChange={event => setApiKey(event.target.value)} /></label>
        <label>模拟 API Secret<input type="password" required maxLength={512} autoComplete="off" value={secret} onChange={event => setSecret(event.target.value)} /></label>
        {venue === 'okx' && <label>模拟 Passphrase<input type="password" required maxLength={512} autoComplete="off" value={passphrase} onChange={event => setPassphrase(event.target.value)} /></label>}
        <label><input type="checkbox" required checked={consent} onChange={event => setConsent(event.target.checked)} />我确认使用模拟密钥，允许保存并用于现货模拟交易</label>
        <button className="trade-primary" disabled={busy || !consent}>{busy ? '正在验证模拟账户…' : '验证连接并保存'}</button>
      </fieldset>
    </form>
    <p>密钥按登录用户隔离并加密存储在服务端，不返回浏览器、不写入策略或区块链。此存储可由平台主机解密，尚非TEE机密托管；请只填写模拟密钥。</p>
    {error && <p className="trade-error" role="alert">{error}</p>}{message && <p className="trade-notice" role="status">{message}</p>}
  </details>
}
