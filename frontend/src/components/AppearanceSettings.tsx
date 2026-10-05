import { useState } from 'react'
import { accents, applyAppearance, themes } from './appearance'

export function AppearanceSettings() {
  const [value, setValue] = useState(() => {
    try { const saved = JSON.parse(localStorage.getItem('atlas:appearance:v1') ?? '{}'); return { theme: saved.theme in themes ? saved.theme : 'navy', accent: saved.accent in accents ? saved.accent : 'blue' } }
    catch { return { theme: 'navy', accent: 'blue' } }
  })
  const [error, setError] = useState('')
  const update = (patch: Partial<typeof value>) => { const next = { ...value, ...patch }; setValue(next); try { localStorage.setItem('atlas:appearance:v1', JSON.stringify(next)); applyAppearance(); setError('') } catch { setError('浏览器无法保存外观设置') } }
  return <section><h3>外观</h3><label>主题<select value={value.theme} onChange={e => update({theme: e.target.value})}>{Object.entries(themes).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>强调色<select value={value.accent} onChange={e => update({accent: e.target.value})}><option value="blue">蓝色</option><option value="teal">青绿</option><option value="gold">金色</option></select></label>{error ? <p role="status">{error}</p> : null}</section>
}
