import type { Adjustment, BaseCurrency, DataSource, Interval } from './types'

const KEY = 'atlas-quant-preferences:v3'
const LEGACY_KEYS = ['atlas-quant-preferences:v2', 'atlas-quant-preferences:v1']
let storageUser = ''
export function setStorageUser(userId: string) { storageUser = userId }
export function userStorageKey(key: string) { return storageUser ? `${key}:${storageUser}` : key }

export type ResultsPanelMode = 'collapsed' | 'normal' | 'maximized'

export interface Preferences {
  symbol: string
  assetClass: string
  interval: Interval
  source: DataSource
  adjustment: Adjustment
  baseCurrency: BaseCurrency
  marketSidebarWidth: number
  strategyPanelWidth: number
  bottomPanelHeight: number
  resultsPanelMode: ResultsPanelMode
  showVolume: boolean
  showMacd: boolean
}

export const DEFAULT_PREFERENCES: Preferences = {
  symbol: 'BTC-USD',
  assetClass: 'crypto',
  interval: '1d',
  source: 'auto',
  adjustment: 'auto',
  baseCurrency: 'CNY',
  marketSidebarWidth: 178,
  strategyPanelWidth: 264,
  bottomPanelHeight: 270,
  resultsPanelMode: 'normal',
  showVolume: true,
  showMacd: true,
}

export function loadPreferences(): Preferences {
  try {
    const raw = window.localStorage.getItem(userStorageKey(KEY))
      ?? (!storageUser ? LEGACY_KEYS.map((key) => window.localStorage.getItem(key)).find(Boolean) : null)
    return raw ? { ...DEFAULT_PREFERENCES, ...JSON.parse(raw) } : DEFAULT_PREFERENCES
  } catch {
    return DEFAULT_PREFERENCES
  }
}

export function savePreferences(preferences: Preferences): void {
  try {
    window.localStorage.setItem(userStorageKey(KEY), JSON.stringify(preferences))
  } catch {
    // The app remains usable when local storage is disabled or full.
  }
}
