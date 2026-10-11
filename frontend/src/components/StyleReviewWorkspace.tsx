import { useEffect, useState } from 'react'
import './style-review.css'

type Input = {
  fund_code: string; fund_name: string; theme: string; rule_version: string; rule_basis: string;
  denominator_basis: string; as_of: string; effective_on: string; previous_effective_on: string;
  library_version: string; previous_version: string; change_reason: string; threshold: string;
  denominator: string; complete: boolean; demo: boolean; source: string;
  holdings_csv: string; library_csv: string; previous_library_csv: string;
}
type Result = {
  status: string; current_pct: number; upper_pct: number; previous_pct: number;
  library_effect_pp: number; coverage_pct: number; added: string[]; removed: string[];
  missing_basis: string[]; basis_changed: string[]; limitations: string[];
  rows: { code: string; name: string; value: string; in_old: boolean; in_new: boolean; basis: string; contribution_pp: number }[];
}
type ReviewNote = { text: string; outcome: string; actor: string; at: string }
type Report = { payload: { id: string; received_at: string; input: Input; result: Result }; sha256: string; hash_scheme: string; notes?: ReviewNote[] }
type Summary = { id: string; fund_name: string; fund_code: string; as_of: string; version: string; status: string; received_at: string; demo: boolean }
const empty: Input = {
  fund_code: '', fund_name: '', theme: '', rule_version: 'R1', rule_basis: '',
  denominator_basis: '同一估值时点、同一基准币种的非现金资产；持仓表包含全部非现金资产',
  as_of: '', effective_on: '', previous_effective_on: '', library_version: 'V2', previous_version: 'V1',
  change_reason: '', threshold: '80', denominator: '', complete: false, demo: false, source: '',
  holdings_csv: 'code,name,value\n', library_csv: 'code,name,basis\n', previous_library_csv: 'code,name,basis\n',
}
const styleReviewExample: Input = {
  ...empty, fund_code: 'DEMO-CONSUMER', fund_name: '消费主题示例（合成数据）', theme: '消费',
  as_of: '2026-10-08', effective_on: '2026-10-08', previous_effective_on: '2026-10-01',
  rule_basis: '演示约定：至少80%的非现金资产属于消费主题。仅用于演示，不是实际基金合同。',
  change_reason: '将公司B加入名单，入库依据待补充；演示固定持仓下的名单影响。',
  denominator: '1000000', complete: true, demo: true, source: '人工构造的合成数据，无真实基金对应',
  holdings_csv: 'code,name,value\nDEMO-A,消费公司A,750000\nDEMO-B,公司B,100000\nDEMO-C,其他公司C,150000',
  previous_library_csv: 'code,name,basis\nDEMO-A,消费公司A,演示消费分类标准',
  library_csv: 'code,name,basis\nDEMO-A,消费公司A,演示消费分类标准\nDEMO-B,公司B,',
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/style-review${path}`, {
    credentials: 'same-origin', ...(body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }),
  })
  if (response.status === 401) window.dispatchEvent(new Event('atlas-session-expired'))
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail :
    Array.isArray(data.detail) ? data.detail.map((e: { msg: string }) => e.msg).join('；') : data.error || '请求失败')
  return data as T
}
function download(filename: string, text: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const pct = (value: number) => `${value.toFixed(2)}%`
const pp = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)} 个百分点`

export default function StyleReviewWorkspace() {
  const [input, setInput] = useState<Input>(empty)
  const [tab, setTab] = useState('核验工作台')
  const [history, setHistory] = useState<Summary[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [note, setNote] = useState('')
  const [outcome, setOutcome] = useState('待补材料')
  const [filter, setFilter] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [verification, setVerification] = useState<{ hash_matches: boolean; calculation_matches: boolean; engine_matches: boolean; notice: string } | null>(null)
  useEffect(() => { let active = true
    api<Summary[]>('/reports').then(v => { if (active) setHistory(v) }).catch(e => { if (active) setError(String(e.message)) })
    return () => { active = false }
  }, [])
  function change<K extends keyof Input>(key: K, value: Input[K]) { setInput(v => ({ ...v, [key]: value })) }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : '操作失败') }
    finally { setBusy(false) }
  }
  async function readFile(file: File | undefined, target: 'holdings_csv' | 'library_csv' | 'previous_library_csv') {
    if (!file) return
    await run(async () => {
      if (file.size > 500000) throw new Error('CSV文件不能超过500KB')
      change(target, await file.text())
      setNotice('已读入编辑区。请核对内容，点击“核验并保存快照”后才提交。')
    })
  }
  const data = report?.payload.input
  const result = report?.payload.result
  const field = (key: keyof Input, label: string, type = 'text') => <label>{label}<input required type={type} step={type === 'number' ? 'any' : undefined}
    value={String(input[key])} onChange={e => change(key, e.target.value)} /></label>
  return <main className="style-review">
    <header className="sr-heading"><div><span className="sr-eyebrow">STYLE REVIEW · 核验与复核</span><h1>风格监管</h1>
      <p>把比例、名单变化和复核依据放在同一处。</p></div>
      <button disabled={busy} onClick={() => { setInput({ ...styleReviewExample }); setTab('规则与数据'); setNotice('已载入合成示例，尚未保存。'); setError('') }}>载入75% → 85%示例</button></header>
    <p className="sr-boundary">辅助核验，不作违规认定。输入为用户提供的数据；机构授权接入、监管报送和链上证明尚未接入。</p>
    <nav className="sr-tabs" aria-label="风格监管页面">{['核验工作台', '规则与数据', '变化分析', '历史与复核', '复核包验证'].map(t =>
      <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>)}</nav>
    {error && <p role="alert" className="sr-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {tab === '规则与数据' && <form onSubmit={e => { e.preventDefault(); void run(async () => {
      const saved = await api<Report>('/reports', input); setReport({ ...saved, notes: [] }); setTab('核验工作台')
      setHistory(await api<Summary[]>('/reports')); setNotice('报告及输入快照已保存；再次提交将新增报告，不覆盖历史。')
    }) }}>
      <section className="sr-card"><h2>1. 产品规则</h2><div className="sr-fields">
        {field('fund_code', '基金代码 / 内部唯一编号')}{field('fund_name', '基金名称')}{field('theme', '投资主题')}
        {field('rule_version', '规则版本')}{field('threshold', '合同约定最低比例（%）', 'number')}
        <label>合同条款 / 依据位置<textarea required value={input.rule_basis} onChange={e => change('rule_basis', e.target.value)} /></label>
      </div><p>80%仅为表单默认值，请按有效合同确认；同一基金已保存的规则版本不可改写。</p></section>
      <section className="sr-card"><h2>2. 持仓与数据口径</h2><div className="sr-fields">
        {field('as_of', '持仓日期', 'date')}{field('denominator', '非现金资产总额（统一币种）', 'number')}
        {field('denominator_basis', '分母及币种口径')}{field('source', '数据来源 / 文件或报告位置')}
      </div><label className="sr-check"><input type="checkbox" checked={input.complete} onChange={e => change('complete', e.target.checked)} />声明已列出全部非现金资产（合计必须与分母一致）</label>
      <label className="sr-check"><input type="checkbox" checked={input.demo} onChange={e => change('demo', e.target.checked)} />这是一份演示或合成数据</label>
      <label>持仓CSV（code,name,value；value为非负市值）<textarea className="sr-csv" required value={input.holdings_csv} onChange={e => change('holdings_csv', e.target.value)} /></label>
      <label>导入持仓CSV<input disabled={busy} type="file" accept=".csv" onChange={e => { void readFile(e.target.files?.[0], 'holdings_csv'); e.target.value = '' }} /></label>
      <p>所有金额须先换算至同一币种；第一版仅支持非负资产市值，不适用于空头或衍生品敞口核验。未知持仓保留不确定区间。</p></section>
      <section className="sr-card"><h2>3. 对比风格库</h2><div className="sr-fields">
        {field('previous_version', '旧版编号')}{field('previous_effective_on', '旧版生效日', 'date')}
        {field('library_version', '新版编号')}{field('effective_on', '新版生效日', 'date')}
      </div><label>本次变更原因<textarea required value={input.change_reason} onChange={e => change('change_reason', e.target.value)} /></label>
      <div className="sr-columns">{(['previous_library_csv', 'library_csv'] as const).map((key, index) => <div key={key}>
        <label>{index ? '新版' : '旧版'}风格库CSV（code,name,basis）<textarea className="sr-csv" required value={input[key]} onChange={e => change(key, e.target.value)} /></label>
        <label>导入{index ? '新版' : '旧版'}名单<input disabled={busy} type="file" accept=".csv" onChange={e => { void readFile(e.target.files?.[0], key); e.target.value = '' }} /></label>
      </div>)}</div><p>basis填写可复核的入库依据；缺失依据会被单独标记。在库不等于入库资格已确认。</p></section>
      <div className="sr-actions"><button className="sr-primary" disabled={busy}>{busy ? '正在保存…' : '核验并保存快照'}</button>
        <button type="button" onClick={() => download('持仓模板.csv', '\ufeffcode,name,value\n示例证券,示例名称,100\n', 'text/csv;charset=utf-8')}>下载持仓模板</button>
        <button type="button" onClick={() => download('风格库模板.csv', '\ufeffcode,name,basis\n示例证券,示例名称,合同条款与分类依据\n', 'text/csv;charset=utf-8')}>下载名单模板</button></div>
    </form>}
    {(tab === '核验工作台' || tab === '变化分析') && (!report || !result || !data ? <section className="sr-empty"><h2>从一份可复核的报告开始</h2><p>导入规则、持仓与新旧风格库，或载入合成示例体验名单变化分析。</p><button onClick={() => setTab('规则与数据')}>录入核验数据</button><button onClick={() => setTab('历史与复核')}>打开历史报告</button></section> : <>
      <section className="sr-card"><h2>{data.fund_name} {data.demo && <small>合成演示</small>}</h2><p>{data.as_of} · {data.rule_version} · {data.previous_version} → {data.library_version} · {result.status}</p>
        <div className="sr-metrics"><article><span>按新版名单的主题占比{!data.complete && '下界'}</span><strong>{pct(result.current_pct)}</strong></article>
          <article><span>配置的最低比例</span><strong>{data.threshold}%</strong></article>
          <article><span>数据覆盖率</span><strong>{pct(result.coverage_pct)}</strong></article>
          <article><span>缺少依据的入库证券</span><strong>{result.missing_basis.length} 只</strong></article></div>
        {!data.complete && <p>不完整持仓：按提交名单，主题占比可能在 {pct(result.current_pct)} 至 {pct(result.upper_pct)} 之间；未披露资产的实际归属未知。</p>}
        <p>来源：{data.source}（未独立验证）</p><details><summary>查看合同与口径依据</summary><p>{data.rule_basis}</p><p>{data.denominator_basis}</p></details>
      </section>
      {tab === '变化分析' && <section className="sr-card"><h2>固定持仓，只替换名单</h2>
        <div className="sr-comparison"><article><span>旧版 {data.previous_version}</span><strong>{pct(result.previous_pct)}</strong></article><span>→</span><article><span>新版 {data.library_version}</span><strong>{pct(result.current_pct)}</strong></article></div>
        <p className="sr-callout">名单更新对已提供持仓的主题占比影响：<b>{pp(result.library_effect_pp)}</b>。这不是交易收益，也不代表实际调仓。</p>
        <p>新增：{result.added.join('、') || '无'}；移出：{result.removed.join('、') || '无'}；依据变更：{result.basis_changed.join('、') || '无'}</p>
        <p>变更说明：{data.change_reason}</p><p>交易与市场影响：未评估。需要连续持仓、逐笔交易及价格/资金流数据，不能仅凭两个比例推断原因。</p></section>}
      <section className="sr-card"><h2>{tab === '变化分析' ? '名单影响逐项分解' : '持仓与依据对照'}</h2>
        <label className="sr-check"><input type="checkbox" checked={onlyIssues} onChange={e => setOnlyIssues(e.target.checked)} />仅查看库外或缺少依据的持仓</label>
        <div className="sr-table-wrap"><table><thead><tr><th>证券</th><th>市值</th><th>旧版</th><th>新版</th><th>名单影响</th><th>依据 / 待办</th></tr></thead><tbody>
          {result.rows.filter(r => !onlyIssues || !r.in_new || !r.basis).map(r => <tr key={r.code}><td>{r.name}<small>{r.code}</small></td><td>{Number(r.value).toLocaleString()}</td><td>{r.in_old ? '在库' : '库外'}</td><td>{r.in_new ? '在库' : '库外'}</td><td>{pp(r.contribution_pp)}</td><td>{r.in_new ? r.basis || '待补入库依据' : '库外持仓，请结合合同复核'}</td></tr>)}
        </tbody></table></div></section><div className="sr-actions"><button onClick={() => setTab('变化分析')}>查看变化分析</button><button onClick={() => setTab('历史与复核')}>追加复核记录</button><button onClick={() => download(`style-review-${report.payload.id}.json`, JSON.stringify(report, null, 2))}>导出复核包（含持仓明细）</button></div>
    </>)}
    {tab === '历史与复核' && <div className="sr-columns"><section className="sr-card"><h2>历史报告 · 最近200份</h2><label>筛选基金<input value={filter} onChange={e => setFilter(e.target.value)} placeholder="名称或代码" /></label>
      <p>点击加载当时快照；名单、规则和持仓均不会被后续编辑覆盖。</p>
      {history.filter(h => `${h.fund_name} ${h.fund_code}`.includes(filter)).map(h => <button className="sr-history" disabled={busy} key={h.id} onClick={() => void run(async () => { setReport(await api<Report>(`/reports/${h.id}`)); setNote('') })}>
        <strong>{h.fund_name}{h.demo ? ' · 演示' : ''}</strong><span>{h.as_of} · {h.version} · {h.status}</span><small>平台接收：{h.received_at}</small></button>)}
      {!history.length && <p>还没有保存的报告。</p>}</section>
      <section className="sr-card"><h2>复核记录</h2>{report ? <><p>{report.payload.input.fund_name} · {report.payload.input.as_of} · {report.payload.input.library_version}</p>
        <p>生效：{report.payload.input.effective_on}；接收：{report.payload.received_at}</p><p className="sr-hash">报告摘要：{report.sha256}</p>
        <div className="sr-actions"><button onClick={() => setTab('核验工作台')}>打开此报告</button><button onClick={() => { setInput({ ...report.payload.input, previous_version: report.payload.input.library_version, previous_effective_on: report.payload.input.effective_on, previous_library_csv: report.payload.input.library_csv, library_version: '', change_reason: '' }); setTab('规则与数据') }}>复制为新版本草稿</button>
        <button onClick={() => download(`style-review-${report.payload.id}.json`, JSON.stringify(report, null, 2))}>导出复核包（含持仓明细）</button></div>
        {(report.notes || []).map((n, i) => <article className="sr-note" key={i}><strong>{n.outcome}</strong><p>{n.text}</p><small>{n.at} · 记录账号 {n.actor}</small></article>)}
        <form onSubmit={e => { e.preventDefault(); void run(async () => {
          await api(`/reports/${report.payload.id}/notes`, { text: note, outcome }); setReport(await api<Report>(`/reports/${report.payload.id}`)); setNote(''); setNotice('复核记录已追加，原始核验结果保持不变。')
        }) }}><label>处理状态<select value={outcome} onChange={e => setOutcome(e.target.value)}>{['待补材料', '已记录说明', '建议调整', '复核完成'].map(v => <option key={v}>{v}</option>)}</select></label>
        <label>依据、解释及待办<textarea required maxLength={4000} value={note} onChange={e => setNote(e.target.value)} /></label><button disabled={busy || !note.trim()}>追加记录</button></form>
        <p>当前为账号内复核。记录人不是经认证的机构角色；“复核完成”不改变原计算或代表监管认可。</p></> : <p>先选择一份历史报告。</p>}</section></div>}
    {tab === '复核包验证' && <section className="sr-card"><h2>导入复核包，重新计算</h2><p>接收方可在自己的账号中验证报告摘要与计算结果，不自动保存导入的持仓。不支持旧引擎时需保留原环境复核。</p>
      <label>选择JSON复核包<input disabled={busy} type="file" accept=".json" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; setVerification(null); if (file) void run(async () => {
        if (file.size > 3000000) throw new Error('复核包不能超过3MB')
        setVerification(await api('/verify', JSON.parse(await file.text())))
      }) }} /></label>
      {verification && <div role="status"><p>摘要一致：{verification.hash_matches ? '是' : '否'}</p><p>重算一致：{verification.calculation_matches ? '是' : '否'}</p><p>引擎版本一致：{verification.engine_matches ? '是' : '否'}</p><p>{verification.notice}</p></div>}
      <p>此验证检查内部一致性，不认证机构、来源或签发时间；同时篡改输入、结果和摘要可能通过。跨机构正式使用还需身份签名及授权机制。</p></section>}
  </main>
}
