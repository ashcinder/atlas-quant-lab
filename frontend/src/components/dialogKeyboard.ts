import { useEffect, useEffectEvent, type RefObject } from 'react'

const openDialogs: HTMLElement[] = []
const isVisible = (dialog: HTMLElement) => !dialog.closest('[hidden], [inert]') &&
  getComputedStyle(dialog).display !== 'none' && getComputedStyle(dialog).visibility !== 'hidden'
const foregroundDialog = () => openDialogs.filter(isVisible).at(-1)

const focusableSelector = [
  'button', 'a[href]', 'input:not([type="hidden"])', 'select', 'textarea', '[tabindex]',
].join(',')

function dialogStops(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter(element =>
    !element.matches(':disabled, [tabindex="-1"]') && !element.closest('[hidden], [inert]') &&
    element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible',
  )
}

export function cycleDialogTab(event: KeyboardEvent, dialog: HTMLElement) {
  if (event.defaultPrevented || event.key !== 'Tab' || !dialog.getClientRects().length) return
  const stops = dialogStops(dialog)
  if (!stops.length) { event.preventDefault(); dialog.focus(); return }
  const index = stops.indexOf(document.activeElement as HTMLElement)
  const next = index < 0 ? (event.shiftKey ? stops.length - 1 : 0) :
    (index + (event.shiftKey ? -1 : 1) + stops.length) % stops.length
  event.preventDefault()
  stops[next].focus()
}

/** Focus entry/return and Escape; modal overlays also contain Tab navigation. */
export function useDialogKeyboard(
  open: boolean, dialogRef: RefObject<HTMLElement | null>, onClose: () => void,
  firstRef?: RefObject<HTMLElement | null>, containFocus = true,
  returnRef?: RefObject<HTMLElement | null>,
) {
  const close = useEffectEvent(onClose)
  useEffect(() => {
    const dialog = dialogRef.current
    if (!open || !dialog) return
    const previous = returnRef?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
    openDialogs.push(dialog)
    const visible = () => isVisible(dialog)
    const focus = () => { if (visible()) (firstRef?.current ?? dialogStops(dialog)[0] ?? dialog).focus() }
    let wasVisible = visible()
    focus()
    const observer = new MutationObserver(() => {
      const isVisible = visible()
      const focusedDialog = document.activeElement?.closest('[role="dialog"], [role="alertdialog"]')
      if (isVisible && !wasVisible && foregroundDialog() === dialog && (!focusedDialog || focusedDialog === dialog || !focusedDialog.getClientRects().length)) focus()
      wasVisible = isVisible
    })
    for (let ancestor = dialog.parentElement; ancestor; ancestor = ancestor.parentElement) {
      observer.observe(ancestor, { attributes: true, attributeFilter: ['hidden', 'inert'] })
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !visible() || foregroundDialog() !== dialog) return
      const focusedDialog = document.activeElement?.closest('[role="dialog"], [role="alertdialog"]')
      if (focusedDialog && focusedDialog !== dialog) return
      if (event.key === 'Escape') { event.preventDefault(); close(); return }
      if (containFocus) cycleDialogTab(event, dialog)
    }
    const keepModalFocus = () => {
      if (!containFocus || !visible() || foregroundDialog() !== dialog || dialog.contains(document.activeElement)) return
      const focusedDialog = document.activeElement?.closest('[role="dialog"], [role="alertdialog"]')
      if (!focusedDialog || !focusedDialog.getClientRects().length) focus()
    }
    window.addEventListener('focusin', keepModalFocus)
    window.addEventListener('keydown', handleKey)
    return () => {
      openDialogs.splice(openDialogs.indexOf(dialog), 1)
      observer.disconnect()
      window.removeEventListener('focusin', keepModalFocus)
      window.removeEventListener('keydown', handleKey)
      previous?.focus()
    }
  }, [open, dialogRef, firstRef, containFocus, returnRef])
}
