export const LAB_NAVIGATION = 'atlas-lab-navigation'

let historyIndex = 0
let hashGuard: ((event: HashChangeEvent) => boolean) | null = null
const guardedChanges = new WeakSet<HashChangeEvent>()

export function trackAtlasHistoryEntry() {
  const saved = window.history.state?.atlasIndex
  if (Number.isSafeInteger(saved)) historyIndex = saved
  else {
    historyIndex += 1
    window.history.replaceState({ ...window.history.state, atlasIndex: historyIndex }, '')
  }
  return historyIndex
}

export function pushAtlasHash(hash: string) {
  const atlasIndex = trackAtlasHistoryEntry() + 1
  window.history.pushState({ ...window.history.state, atlasIndex }, '', hash)
  historyIndex = atlasIndex
}

export function setLabHashGuard(guard: (event: HashChangeEvent) => boolean) {
  hashGuard = guard
  return () => { if (hashGuard === guard) hashGuard = null }
}

export function guardLabHashChange(event: HashChangeEvent) {
  if (guardedChanges.has(event)) return true
  if (!hashGuard?.(event)) return false
  guardedChanges.add(event)
  return true
}

export function requestLabNavigation(proceed: () => void) {
  const event = new CustomEvent(LAB_NAVIGATION, { cancelable: true, detail: proceed })
  if (window.dispatchEvent(event)) proceed()
}
