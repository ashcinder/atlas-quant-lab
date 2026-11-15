const themes = { white: '纯白', mist: '雾蓝', navy: '深蓝', graphite: '石墨', forest: '墨绿' }
const accents = { blue: '#9bb9ff', teal: '#79d5c2', gold: '#e8c47d' }
const lightAccents = { blue: '#315fd3', teal: '#08796b', gold: '#916900' }
const defaults = { theme: 'white', accent: 'gold' } as const

export const APPEARANCE_STORAGE_KEY = 'atlas:appearance:v1'
export { themes }
export type Appearance = { theme: keyof typeof themes; accent: keyof typeof accents }

export function readAppearance(): Appearance {
  try {
    const saved = JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? 'null')
    const theme = saved?.theme
    const accent = saved?.accent
    return {
      theme: typeof theme === 'string' && Object.hasOwn(themes, theme) ? theme as Appearance['theme'] : defaults.theme,
      accent: typeof accent === 'string' && Object.hasOwn(accents, accent) ? accent as Appearance['accent'] : defaults.accent,
    }
  } catch { return defaults }
}

export function applyAppearance() {
  const { theme, accent } = readAppearance()
  const light = theme === 'white' || theme === 'mist'
  document.documentElement.dataset.theme = theme
  document.documentElement.style.setProperty('--accent', (light ? lightAccents : accents)[accent])
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', light ? '#f5f7fa' : '#0b0f14')
  window.dispatchEvent(new Event('atlas-appearance-change'))
}
