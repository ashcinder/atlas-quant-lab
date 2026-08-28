import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_PREFERENCES, loadPreferences, savePreferences } from './storage'

describe('versioned local preferences', () => {
  const values = new Map<string, string>()
  beforeAll(() => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    })
  })
  beforeEach(() => window.localStorage.clear())

  it('returns safe defaults with empty storage', () => {
    expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES)
  })

  it('round-trips only the local UI preferences', () => {
    const preferences = { ...DEFAULT_PREFERENCES, symbol: 'AAPL', assetClass: 'equity' }
    savePreferences(preferences)
    expect(loadPreferences()).toEqual(preferences)
    expect(window.localStorage.getItem('atlas-quant-preferences:v3')).toBeTruthy()
  })

  it('migrates v1 preferences while adding layout defaults', () => {
    window.localStorage.setItem('atlas-quant-preferences:v1', JSON.stringify({
      symbol: 'ETH-USD',
      assetClass: 'crypto',
      interval: '4h',
      source: 'auto',
    }))
    expect(loadPreferences()).toMatchObject({
      symbol: 'ETH-USD',
      marketSidebarWidth: 178,
      strategyPanelWidth: 264,
      bottomPanelHeight: 270,
      resultsPanelMode: 'normal',
      showVolume: true,
      showMacd: true,
    })
  })
})
