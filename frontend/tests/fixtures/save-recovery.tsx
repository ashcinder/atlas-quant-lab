/** Manual acceptance fixture: inject one gateway failure at the real save seam. */
import {useState} from 'react'
import {createRoot} from 'react-dom/client'
import {api} from '../../src/api'
import {ResultsPanel} from '../../src/components/ResultsPanel'
import {HistoryDrawer} from '../../src/components/HistoryDrawer'
import type {BacktestResult,RunSummary} from '../../src/types'
import '../../src/theme.css'
import '../../src/styles.css'

const originalFetch=window.fetch.bind(window)
let saveAttempts=0
window.fetch=async(input,init)=>{
 if(String(input).endsWith('/api/v1/compute/runs')&&init?.method==='POST'){
  saveAttempts++
  if(saveAttempts===1)return new Response(JSON.stringify({error:'验收注入：保存报告HTTP 502'}),{status:502,headers:{'Content-Type':'application/json'}})
 }
 return originalFetch(input,init)
}
const registered=await originalFetch('/api/register',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`save-recovery-${crypto.randomUUID()}@example.test`,password:crypto.randomUUID()})})
if(!registered.ok)throw new Error(`独立测试会话创建失败：${registered.status}`)

export function Fixture(){
 const [result,setResult]=useState<BacktestResult|null>(null),[runs,setRuns]=useState<RunSummary[]>([]),[history,setHistory]=useState(false),[status,setStatus]=useState('就绪'),[busy,setBusy]=useState(false)
 const run=async()=>{
  setBusy(true);setStatus('正在计算完整历史…')
  try{
   const completed=await api.runBacktest({symbol:'688981.SS',asset_class:'equity',interval:'5m',data_source:'huggingface',adjustment:'raw',strategy_id:'sma_cross',params:{fast:20,slow:60},execution_model:'unified'})
   if(completed.compute?.storage_status!=='local'||completed.equity.length!==70570)throw Error('保存故障未被正确保留')
   setResult(completed);setRuns(await api.listRuns());setStatus(`PASS：HTTP 502后保留全部 ${completed.equity.length} 根资金记录、${completed.trades.length} 笔成交`)
  }catch(e){setStatus('FAIL：'+String(e))}finally{setBusy(false)}
 }
 const sync=async(item:RunSummary)=>{
  const saved=await api.syncRun(item.id)
  const restored=await api.getRun<BacktestResult>(saved.run_id)
  if(restored.equity.length!==70570||saveAttempts!==2)throw Error('同步数量或执行次数不符')
  setResult(restored);setRuns(await api.listRuns());setHistory(false);setStatus(`PASS：服务恢复后同步并重读 ${restored.equity.length} 根资金记录、${restored.trades.length} 笔成交；策略只执行一次`)
 }
 return <main style={{maxWidth:1400,margin:'20px auto',padding:20}}><h1>中芯国际 · 5分钟完整历史 · 保存中断验收</h1><p>真实浏览器计算，首次保存注入一次HTTP 502；后续同步通过真实本地API。</p><button disabled={busy||Boolean(result)} onClick={()=>void run()}>开始完整回测验证</button><button onClick={()=>setHistory(true)}>打开回测历史</button><p role="status">{status}</p><ResultsPanel result={result} loading={busy} panelMode="normal" onPanelMode={()=>{}} /><HistoryDrawer open={history} runs={runs} onClose={()=>setHistory(false)} onOpen={async item=>{setResult(await api.getRun<BacktestResult>(item.id));setHistory(false)}} onDelete={()=>{}} onSync={sync} /></main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
