const themes = { white: '纯白', mist: '雾蓝', navy: '深蓝', graphite: '石墨', forest: '墨绿' }
const accents = { blue: '#9bb9ff', teal: '#79d5c2', gold: '#e8c47d' }

export { accents, themes }

export function applyAppearance() {
  try {
    const saved = JSON.parse(localStorage.getItem('atlas:appearance:v1') ?? '{}')
    document.documentElement.dataset.theme = saved.theme in themes ? saved.theme : 'navy'
    const light = saved.theme === 'white' || saved.theme === 'mist'
    const lightAccents = { blue: '#315fd3', teal: '#08796b', gold: '#916900' }
    document.documentElement.style.setProperty('--accent', (light ? lightAccents : accents)[saved.accent as keyof typeof accents] ?? (light ? lightAccents.blue : accents.blue))
    window.dispatchEvent(new Event('atlas-appearance-change'))
  } catch { /* Keep defaults when storage is unavailable. */ }
}
