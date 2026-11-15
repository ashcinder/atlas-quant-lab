import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { CircleAlert, X } from 'lucide-react'
import './lab-experience.css'
import { cycleDialogTab, useDialogKeyboard } from './dialogKeyboard'

interface Props {
  title: string
  description: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  destructive?: boolean
  extraAction?: ReactNode
  confirmDisabled?: boolean
}

/** Transient confirmation only: private draft content never leaves component memory. */
export function LabConfirmDialog({ title, description, confirmLabel, onConfirm, onCancel, destructive = false, extraAction, confirmDisabled }: Props) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const cancelAction = useRef(onCancel)

  useDialogKeyboard(true, dialogRef, onCancel, cancelRef)

  useEffect(() => { cancelAction.current = onCancel }, [onCancel])
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!dialogRef.current || dialogRef.current.closest('[hidden], [inert]')) return
      const focusedDialog = document.activeElement?.closest('[role="dialog"], [role="alertdialog"]')
      if (focusedDialog && focusedDialog !== dialogRef.current) return
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelAction.current(); return }
      cycleDialogTab(event, dialogRef.current)
    }
    window.addEventListener('keydown', handleKey, true)
    return () => { window.removeEventListener('keydown', handleKey, true) }
  }, [])

  return <div className="lab-confirm-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) onCancel() }}>
    <div className="lab-confirm-dialog" ref={dialogRef} role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
      <header><CircleAlert size={20} /><h2 id={titleId}>{title}</h2><button aria-label="关闭确认" onClick={onCancel}><X size={18} /></button></header>
      <p id={descriptionId}>{description}</p>
      <footer><button ref={cancelRef} onClick={onCancel}>取消，保留当前内容</button>{extraAction}<button className={destructive ? 'is-destructive' : 'is-primary'} onClick={onConfirm} disabled={confirmDisabled}>{confirmLabel}</button></footer>
    </div>
  </div>
}
