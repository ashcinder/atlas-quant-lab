import { useEffect, useId, useRef } from 'react'
import { CircleAlert, X } from 'lucide-react'
import './lab-experience.css'

interface Props {
  title: string
  description: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  destructive?: boolean
}

/** Transient confirmation only: private draft content never leaves component memory. */
export function LabConfirmDialog({ title, description, confirmLabel, onConfirm, onCancel, destructive = false }: Props) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const cancelAction = useRef(onCancel)

  useEffect(() => { cancelAction.current = onCancel }, [onCancel])
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    cancelRef.current?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelAction.current(); return }
      if (event.key !== 'Tab') return
      const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
      const first = buttons?.[0]
      const last = buttons?.[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    window.addEventListener('keydown', handleKey, true)
    return () => { window.removeEventListener('keydown', handleKey, true); previous?.focus() }
  }, [])

  return <div className="lab-confirm-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) onCancel() }}>
    <div className="lab-confirm-dialog" ref={dialogRef} role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
      <header><CircleAlert size={20} /><h2 id={titleId}>{title}</h2><button aria-label="关闭确认" onClick={onCancel}><X size={18} /></button></header>
      <p id={descriptionId}>{description}</p>
      <footer><button ref={cancelRef} onClick={onCancel}>取消，保留当前内容</button><button className={destructive ? 'is-destructive' : 'is-primary'} onClick={onConfirm}>{confirmLabel}</button></footer>
    </div>
  </div>
}
