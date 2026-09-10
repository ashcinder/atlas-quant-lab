import { useEffect, useState } from 'react'
import { request } from '../request'

interface Status { configured: boolean; provider: string | null; model: string | null; providers: Array<{id: string; label: string; model: string}> }
export function AISettings() {
  const [status, setStatus] = useState<Status | null>(null)
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('deepseek-chat')
  const [key, setKey] = useState('')
  const [consent, setConsent] = useState(false)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { let active = true; request<Status>('/ai-settings').then(data => { if (active) { setStatus(data); if (data.provider) setProvider(data.provider); if (data.model) setModel(data.model) } }).catch(() => { if (active) setMessage('无法读取 AI 设置，请确认后端已更新并重启。') }); return () => { active = false } }, [])
  async function perform(action: 'save' | 'test' | 'clear') {
    setBusy(true); setMessage('')
    try {
      if (action === 'save') {
        await request('/ai-settings', { method: 'PUT', body: JSON.stringify({ provider, model, api_key: key.trim(), consent }) })
        setKey(''); setMessage('已保存到当前登录会话，8 小时后或后端重启后失效。')
      } else if (action === 'test') {
        await request('/ai-settings/test', { method: 'POST' }); setMessage('连接成功，已验证模型返回。')
      } else { await request('/ai-settings', { method: 'DELETE' }); setKey(''); setMessage('已清除当前会话的云端密钥。') }
      setStatus(await request<Status>('/ai-settings'))
    } catch (error) { setMessage(error instanceof Error ? error.message : '操作失败') }
    finally { setBusy(false) }
  }
  return <section className="ai-settings"><h3>AI 服务</h3><p>供代码助手与单次回测审核使用。选择服务并填写你自己的 Key；不会写入浏览器存储、策略导出或 Git。</p>
    <label>服务商<select value={provider} onChange={e => { setProvider(e.target.value); setModel(status?.providers.find(item => item.id === e.target.value)?.model ?? ''); setKey('') }}>{(status?.providers ?? [{id:'deepseek',label:'DeepSeek',model:'deepseek-chat'}, {id:'qwen',label:'通义千问',model:'qwen-plus'}]).map(item => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
    <label>模型名称<input value={model} maxLength={100} onChange={e => setModel(e.target.value)} /></label>
    <label>API Key<input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={status?.configured ? '已配置，密钥不回显' : '粘贴新生成的 Key'} /></label>
    <label className="ai-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /><span>同意代码助手发送代码与问题、已开启的 AI 回测发送历史行情与交易信号给所选服务商；可能产生 API 费用，这不是私密 ZKP / TEE 推理。</span></label>
    <div className="ai-setting-actions"><button disabled={busy || !key.trim() || !model.trim() || !consent} onClick={() => void perform('save')}>保存配置</button><button disabled={busy || !status?.configured} onClick={() => void perform('test')}>测试连接（少量用量）</button><button disabled={busy || !status?.configured} onClick={() => void perform('clear')}>清除</button></div>
    <p role="status">{busy ? '处理中…' : message}</p>
  </section>
}
