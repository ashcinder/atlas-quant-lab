import { useRef, useState } from 'react'
import { useDialogKeyboard } from './dialogKeyboard'
import { Clock3, History, RefreshCw, Trash2, X } from 'lucide-react'
import { formatDate, formatPercent } from '../format'
import type { RunSummary } from '../types'

interface Props {
  open: boolean
  runs: RunSummary[]
  onClose: () => void
  onOpen: (run: RunSummary) => void
  onDelete: (run: RunSummary) => void
  onSync?: (run:RunSummary) => Promise<void>
}

export function HistoryDrawer({ open, runs, onClose, onOpen, onDelete, onSync }: Props) {
  const dialogRef = useRef<HTMLElement>(null)
  const [syncing,setSyncing]=useState<string|null>(null)
  const sync=async(run:RunSummary)=>{setSyncing(run.id);try{await onSync?.(run)}finally{setSyncing(null)}}
  useDialogKeyboard(open, dialogRef, onClose)

  return (
    <div className={`drawer-backdrop ${open ? 'is-open' : ''}`} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <aside ref={dialogRef} className="history-drawer" role="dialog" aria-modal="true" aria-label="回测历史" aria-hidden={!open}>
        <div className="drawer-heading"><span><History size={17} />回测历史</span><button className="icon-button" aria-label="关闭回测历史" onClick={onClose}><X size={17} /></button></div>
        <p className="drawer-intro">打开记录不会重新计算。尚未同步的结果保存在当前浏览器，可在服务恢复后重试同步。</p>
        <div className="run-list">
          {runs.map((run) => <div className="run-row" key={run.id}><button aria-label={`打开 ${run.symbol} 回测记录`} onClick={() => onOpen(run)}><span><strong>{run.symbol}</strong><em>{run.compute?.storage_status==='local'?'仅此浏览器 · 尚未同步':run.mode === 'single' ? '单标的' : '组合'}</em></span><span><b>{run.strategy_id}</b><small><Clock3 size={11} />{formatDate(new Date(run.created_at).getTime() / 1000)}</small></span><span><strong className={(run.total_return ?? 0) >= 0 ? 'positive' : 'negative'}>{formatPercent(run.total_return)}</strong><small>回撤 {formatPercent(run.max_drawdown)}</small></span></button>{onSync&&run.compute?.storage_status==='local'?<button className="sync-run" aria-label={`重试同步 ${run.symbol} 回测记录`} disabled={syncing!==null} onClick={()=>void sync(run)}><RefreshCw size={14} className={syncing===run.id?'spin':''} />重试同步</button>:null}<button className="delete-run" aria-label={`删除 ${run.symbol} 回测记录`} onClick={() => onDelete(run)} title="删除记录"><Trash2 size={14} /></button></div>)}
          {runs.length === 0 ? <div className="drawer-empty"><History size={24} /><span>还没有保存的回测</span><small>运行一次策略后，记录会出现在这里。</small></div> : null}
        </div>
      </aside>
    </div>
  )
}
