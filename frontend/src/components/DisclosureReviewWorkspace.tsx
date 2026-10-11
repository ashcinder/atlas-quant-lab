import { useEffect, useState } from 'react'

const empty = {
  fund_code: '', fund_name: '', disclosure_date: '', records_date: '', disclosure_source: '', records_source: '',
  scope: '', currency: 'CNY', same_basis: false, complete_scope: false, demo: false,
  quantity_tolerance: '0', value_tolerance: '0',
  disclosure_csv: 'code,name,quantity,value\n', records_csv: 'code,name,quantity,value\n',
}
type Input = typeof empty
type Entry = { code: string; name: string; quantity: string; value: string }
type Report = { id: string; received_at: string; input: Input; result: {
  status: string; comparable: boolean; issue_count: number; row_count: number; notice: string;
  rows: { code: string; disclosure: Entry | null; records: Entry | null; quantity_delta: string | null; value_delta: string | null; issues: string[] }[];
} }
type Summary = { id: string; fund_name: string; as_of: string; status: string }
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/disclosure-review${path}`, { credentials: 'same-origin',
    ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (response.status === 401) window.dispatchEvent(new Event('atlas-session-expired'))
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '输入格式有误，请核对必填项、日期、容差和CSV内容')
  return value
}
function download(name: string, body: string, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([body], { type: mime }))
  const link = document.createElement('a'); link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export default function DisclosureReviewWorkspace() {
  const [input, setInput] = useState(empty)
  const [report, setReport] = useState<Report | null>(null)
  const [history, setHistory] = useState<Summary[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(false)
  useEffect(() => { let active = true
    api<Summary[]>('/reports').then(v => { if (active) setHistory(v) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])
  function change<K extends keyof Input>(key: K, value: Input[K]) { setInput(v => ({ ...v, [key]: value })) }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : '操作失败') } finally { setBusy(false) }
  }
  function example() {
    setInput({ ...empty, fund_code: 'DEMO-DISCLOSURE', fund_name: '披露核验示例（合成数据）',
      disclosure_date: '2026-10-08', records_date: '2026-10-08', disclosure_source: '合成季度报告第8页持仓表（人工提取）',
      records_source: '合成估值表，同期快照', scope: '示例全部股票持仓；数量单位为股，金额单位为元',
      same_basis: true, complete_scope: true, demo: true,
      disclosure_csv: 'code,name,quantity,value\nDEMO-A,公司A,100,1000\nDEMO-B,公司B,200,2500',
      records_csv: 'code,name,quantity,value\nDEMO-A,公司A,100,1000\nDEMO-B,公司B,210,2600\nDEMO-C,公司C,50,500',
    }); setError('')
  }
  const field = (key: keyof Input, label: string, type = 'text') => <label>{label}<input required type={type} step={type === 'number' ? 'any' : undefined} min={type === 'number' ? '0' : undefined} value={String(input[key])} onChange={e => change(key, e.target.value)} /></label>
  return <main className="style-review">
    <header className="sr-heading"><div><span className="sr-eyebrow">DISCLOSURE REVIEW</span><h2>信息披露一致性核验</h2><p>对比披露表格与同期底层记录，逐项定位数量、市值、名称及缺项差异。</p></div><button onClick={example} disabled={busy}>载入披露差异示例</button></header>
    <p className="sr-boundary">本版接受人工提取的CSV，不自动读取PDF。双方数据均由用户提供，差异是复核线索，不代表违规。请先统一币种、单位、证券代码及统计范围。</p>
    {error && <p role="alert">{error}</p>}
    <form className="sr-card" onSubmit={e => { e.preventDefault(); void run(async () => {
      const saved = await api<Report>('/reports', input); setReport(saved)
      setHistory(await api<Summary[]>('/reports'))
    }) }}>
      <h2>1. 确认对比范围与数据</h2>
      <div className="sr-fields">{field('fund_code', '基金代码')}{field('fund_name', '基金名称')}
        {field('disclosure_date', '披露数据对应日期（非发布日期）', 'date')}{field('records_date', '底层记录日期', 'date')}
        {field('disclosure_source', '披露来源与页码 / 表名')}{field('records_source', '底层记录来源与版本')}
        {field('scope', '统计范围与数量、金额单位')}{field('currency', '统一币种（三位大写代码）')}
        {field('quantity_tolerance', '数量绝对容差', 'number')}{field('value_tolerance', '市值绝对容差', 'number')}
      </div>
      <label className="sr-check"><input type="checkbox" checked={input.same_basis} onChange={e => change('same_basis', e.target.checked)} />已确认双方币种、单位、估值口径和证券代码一致</label>
      <label className="sr-check"><input type="checkbox" checked={input.complete_scope} onChange={e => change('complete_scope', e.target.checked)} />双方覆盖相同完整范围（部分持仓披露请先筛选底层表至对应范围）</label>
      <label className="sr-check"><input type="checkbox" checked={input.demo} onChange={e => change('demo', e.target.checked)} />合成演示数据</label>
      <button type="button" onClick={() => download('disclosure-template.csv', 'code,name,quantity,value\nDEMO-A,示例公司,100,1000\n', 'text/csv;charset=utf-8')}>下载CSV模板</button>
      <div className="sr-columns">{(['disclosure_csv', 'records_csv'] as const).map((key, i) => <div key={key}>
        <label>{i === 0 ? '披露表格CSV' : '底层记录CSV'}<textarea className="sr-csv" required value={input[key]} onChange={e => change(key, e.target.value)} /></label>
        <label>导入{i === 0 ? '披露' : '底层'}CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void run(async () => {
          if (file.size > 500000) throw new Error('每个文件最多500KB')
          change(key, await file.text())
        }); e.target.value = '' }} /></label>
      </div>)}</div>
      <button className="sr-primary" disabled={busy}>{busy ? '处理中…' : '对比并保存核验快照'}</button>
    </form>
    {report && <section className="sr-card" aria-label="披露核验结果">
      <h2>2. 已保存结果 · {report.input.fund_name}{report.input.demo ? ' · 合成演示' : ''}</h2>
      <p>{report.input.disclosure_date} / {report.input.records_date} · {report.result.status}</p>
      <p>共 {report.result.row_count} 项，待核对 {report.result.issue_count} 项。容差：数量 {report.input.quantity_tolerance}，市值 {report.input.value_tolerance}。</p>
      <p>范围：{report.input.scope} · 币种：{report.input.currency} · 完整范围：{report.input.complete_scope ? '已声明' : '未确认'}</p>
      <p>披露依据：{report.input.disclosure_source}<br />底层依据：{report.input.records_source}</p>
      <p className="sr-boundary">{report.result.notice} 下方始终显示已保存快照，修改上方输入后需重新核验。</p>
      <label className="sr-check"><input type="checkbox" checked={onlyIssues} onChange={e => setOnlyIssues(e.target.checked)} />仅显示待核对项</label>
      <div className="sr-table-wrap"><table><thead><tr>{['证券代码', '披露名称 / 底层名称', '披露数量 / 底层数量', '数量差额', '披露市值 / 底层市值', '市值差额', '核验线索'].map(v => <th key={v}>{v}</th>)}</tr></thead><tbody>
        {report.result.rows.filter(row => !onlyIssues || row.issues.length > 0).map(row => <tr key={row.code}><td>{row.code}</td><td>{row.disclosure?.name ?? '缺项'} / {row.records?.name ?? '缺项'}</td><td>{row.disclosure?.quantity ?? '—'} / {row.records?.quantity ?? '—'}</td><td>{row.quantity_delta ?? '不计算'}</td><td>{row.disclosure?.value ?? '—'} / {row.records?.value ?? '—'}</td><td>{row.value_delta ?? '不计算'}</td><td>{row.issues.join('；') || '容差内一致'}</td></tr>)}
      </tbody></table></div>
      <button onClick={() => download(`disclosure-review-${report.id}.json`, JSON.stringify(report, null, 2))}>导出核验快照（含明细）</button>
    </section>}
    <section className="sr-card"><h2>3. 历史核验</h2><p>每次核验新增快照，历史结果不会被输入修改覆盖。仅显示当前账号最近200份报告。</p>
      {history.length === 0 ? <p>暂无历史核验。</p> : history.map(item => <p key={item.id}><button disabled={busy} onClick={() => void run(async () => setReport(await api<Report>(`/reports/${item.id}`)))}>{item.fund_name} · {item.as_of} · {item.status} · {item.id.slice(0, 8)}</button></p>)}
    </section>
  </main>
}
