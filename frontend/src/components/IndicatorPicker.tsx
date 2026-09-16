import { useEffect, useRef, useState } from 'react'
import { indicatorCatalog, type IndicatorSettings } from '../chartIndicators'
export function IndicatorPicker({ toolbar, onToolbar, selected, settings, onToggle, onSettings, onClose, volume, macd, onVolume, onMacd }: {
  toolbar: Set<string>; onToolbar: (key: string) => void;
  selected: Set<string>; settings: IndicatorSettings; onToggle: (key: string) => void; onSettings: (value: IndicatorSettings) => void; onClose: () => void;
  volume: boolean; macd: boolean; onVolume: (value: boolean) => void; onMacd: (value: boolean) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [search, setSearch] = useState('')
  useEffect(() => { const node = dialog.current; node?.showModal(); return () => node?.close() }, [])
  return <dialog className="atlas-indicator-dialog" ref={dialog} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose() }} aria-labelledby="indicator-title">
    <header><div><h3 id="indicator-title">技术指标</h3><small>勾选指标控制图表显示；“显示在顶部”独立控制快捷按钮。</small></div><button onClick={onClose} aria-label="关闭指标选择">×</button></header>
    <input autoFocus aria-label="搜索技术指标" placeholder="搜索名称，例如 RSI、均线" value={search} onChange={e => setSearch(e.target.value)} />
    <div className="indicator-picker-list">
      {[{ key: 'volume', label: 'VOL · 成交量', enabled: volume, toggle: onVolume }, { key: 'macd', label: 'MACD (12, 26, 9)', enabled: macd, toggle: onMacd }].filter(x => x.label.toLowerCase().includes(search.toLowerCase())).map(x => <div className="indicator-picker-row" key={x.key}><label><input type="checkbox" checked={x.enabled} onChange={e => x.toggle(e.target.checked)} />{x.label}<small>副图</small></label><label className="indicator-pin"><input type="checkbox" checked={toolbar.has(x.key)} onChange={() => onToolbar(x.key)} />显示在顶部</label></div>)}
      {indicatorCatalog.filter(x => x.label.toLowerCase().includes(search.toLowerCase())).map(x => <div className="indicator-picker-row" key={x.key}>
        <label><input type="checkbox" checked={selected.has(x.key)} onChange={() => onToggle(x.key)} />{x.label}<small>{x.pane ? '副图' : '主图'}</small></label>
        <div><label className="indicator-pin"><input type="checkbox" checked={toolbar.has(x.key)} onChange={() => onToolbar(x.key)} />显示在顶部</label>{x.period > 0 && <label>周期<input aria-label={`${x.key} 周期`} type="number" min={2} max={500} value={settings[x.key].period} onChange={e => onSettings({ ...settings, [x.key]: { ...settings[x.key], period: Math.max(2, Math.min(500, Number(e.target.value) || x.period)) } })} /></label>}
        <input type="color" aria-label={`${x.key} 颜色`} value={settings[x.key].color} onChange={e => onSettings({ ...settings, [x.key]: { ...settings[x.key], color: e.target.value } })} /></div>
      </div>)}
    </div><p>参数按当前用户保存。指标只使用当前及此前 K 线；VWAP 按 UTC 日重置，适合日内周期。</p><button onClick={onClose}>完成</button>
  </dialog>
}
