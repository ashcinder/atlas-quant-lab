import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { APPEARANCE_STORAGE_KEY, applyAppearance, readAppearance } from './appearance'

beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.theme
  document.documentElement.style.removeProperty('--accent')
})

it('uses white and gold on first load and when preferences cannot be parsed', () => {
  applyAppearance()
  expect(document.documentElement.dataset.theme).toBe('white')
  expect(document.documentElement.style.getPropertyValue('--accent')).toBe('#916900')
  localStorage.setItem(APPEARANCE_STORAGE_KEY, '{')
  expect(readAppearance()).toEqual({ theme: 'white', accent: 'gold' })
})

it('preserves valid saved appearance preferences', () => {
  localStorage.setItem(APPEARANCE_STORAGE_KEY, '{"theme":"navy","accent":"teal"}')
  applyAppearance()
  expect(document.documentElement.dataset.theme).toBe('navy')
  expect(document.documentElement.style.getPropertyValue('--accent')).toBe('#79d5c2')
})
