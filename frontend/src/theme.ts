import { useEffect, useState } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'
const storageKey = 'atlas:theme'

export function readTheme(): ThemePreference {
  try {
    const saved = localStorage.getItem(storageKey)
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  } catch { return 'system' }
}

export function applyTheme(preference: ThemePreference, systemDark: boolean) {
  const resolved = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference
  document.documentElement.dataset.theme = resolved
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#0c131c' : '#f4f7fb')
  window.dispatchEvent(new Event('atlas-theme-change'))
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemePreference>(readTheme)
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => applyTheme(theme, media.matches)
    update()
    media.addEventListener('change', update)
    try { localStorage.setItem(storageKey, theme) } catch { /* Theme still works without storage. */ }
    return () => media.removeEventListener('change', update)
  }, [theme])
  useEffect(() => {
    const sync = (event: StorageEvent) => { if (event.key === storageKey) setTheme(readTheme()) }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])
  return [theme, setTheme] as const
}

// Canvas charts cannot consume CSS variables directly.
export function chartTheme() {
  const style = getComputedStyle(document.documentElement)
  const value = (name: string) => style.getPropertyValue(name).trim()
  return { background: value('--bg'), text: value('--muted'), border: value('--border'),
    foreground: value('--text'), accent: value('--accent') }
}
