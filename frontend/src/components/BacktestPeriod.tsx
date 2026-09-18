import { useRef, useState } from 'react'
import { CalendarRange, Check, X } from 'lucide-react'
import './research-controls.css'
const localDate = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
export function BacktestPeriod({ start, end, onApply, label = '回测', disabled = false }: { start: string; end: string; onApply: (start: string, end: string) => void; label?: string; disabled?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [draftStart, setStart] = useState(start), [draftEnd, setEnd] = useState(end), [error, setError] = useState('')
  const open = () => { setStart(start); setEnd(end); setError(''); dialog.current?.showModal() }
  const apply = () => {
    if ((draftStart && !Number.isFinite(Date.parse(draftStart))) || (draftEnd && !Number.isFinite(Date.parse(draftEnd))) || (draftStart && draftEnd && draftStart >= draftEnd)) { setError('开始时间必须早于结束时间'); return }
    onApply(draftStart, draftEnd); dialog.current?.close()
  }
  return <div className="period-control"><button type="button" className="period-open" onClick={open} disabled={disabled}><CalendarRange size={18}/><span><strong>{label}时间区间</strong><small>{start ? start.replace('T', ' ') : '最早可用行情'} → {end ? end.replace('T', ' ') : '最新行情'}</small></span><em>设置</em></button>
    <dialog ref={dialog} className="period-dialog" aria-label={`${label}时间设置`}><header><div><small>TIME RANGE</small><h3>设置{label}区间</h3></div><button type="button" onClick={() => dialog.current?.close()} aria-label="关闭时间设置"><X size={18}/></button></header>
      <p>按本地时区选择，提交时转换为 UTC。</p><div className="period-presets">{[7,30,90,180,365].map(days => <button type="button" key={days} onClick={() => { const endDate = new Date(); setStart(localDate(new Date(endDate.getTime()-days*86400000)));setEnd(localDate(endDate)) }}>{days===365?'近一年':`近 ${days} 天`}</button>)}<button type="button" onClick={() => { setStart('');setEnd('') }}>全部历史</button></div>
      <label>开始日期与时间<input aria-label={`${label}开始时间`} type="datetime-local" value={draftStart} onInput={e=>setStart(e.currentTarget.value)} onChange={e=>setStart(e.target.value)}/></label><label>结束日期与时间<input aria-label={`${label}结束时间`} type="datetime-local" value={draftEnd} onInput={e=>setEnd(e.currentTarget.value)} onChange={e=>setEnd(e.target.value)}/></label>
      <small>留空表示使用可用行情边界。确认只应用时间设置，不会立即运行回测。</small>{error && <p role="alert">{error}</p>}<footer><button type="button" onClick={()=>dialog.current?.close()}>取消</button><button type="button" className="period-confirm" onClick={apply}><Check size={16}/>确认区间</button></footer>
    </dialog></div>
}
