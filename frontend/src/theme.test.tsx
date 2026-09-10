import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { applyTheme, readTheme, useTheme, type ThemePreference } from './theme'

let systemDark = false
let listeners: Set<() => void>
beforeEach(() => {
  localStorage.clear()
  systemDark = false
  listeners = new Set()
  vi.stubGlobal('matchMedia', () => ({ get matches() { return systemDark },
    addEventListener: (_name: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_name: string, fn: () => void) => listeners.delete(fn) }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function Control() {
  const [theme, setTheme] = useTheme()
  return <select aria-label="主题" value={theme} onChange={(event) => setTheme(event.target.value as ThemePreference)}><option value="system">系统</option><option value="light">浅色</option><option value="dark">深色</option></select>
}
it('updates all surfaces and chart subscribers using the root theme', () => {
  const updateChart = vi.fn()
  window.addEventListener('atlas-theme-change', updateChart)
  applyTheme('dark', false)
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(document.documentElement.classList.contains('dark')).toBe(true)
  applyTheme('light', true)
  expect(document.documentElement.classList.contains('dark')).toBe(false)
  expect(updateChart).toHaveBeenCalledTimes(2)
  window.removeEventListener('atlas-theme-change', updateChart)
})
it('follows system changes but preserves an explicit preference', () => {
  render(<Control />)
  expect(document.documentElement.dataset.theme).toBe('light')
  act(() => { systemDark = true; listeners.forEach((fn) => fn()) })
  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.change(screen.getByLabelText('主题'), { target: { value: 'light' } })
  act(() => listeners.forEach((fn) => fn()))
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(localStorage.getItem('atlas:theme')).toBe('light')
})
it('uses a safe default if storage is unavailable or invalid', () => {
  localStorage.setItem('atlas:theme', 'invalid')
  expect(readTheme()).toBe('system')
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
  expect(readTheme()).toBe('system')
})
it('removes its system listener on unmount and syncs another tab', () => {
  const { unmount } = render(<Control />)
  act(() => {
    localStorage.setItem('atlas:theme', 'dark')
    window.dispatchEvent(new StorageEvent('storage', { key: 'atlas:theme' }))
  })
  expect(document.documentElement.dataset.theme).toBe('dark')
  unmount()
  expect(listeners.size).toBe(0)
})
