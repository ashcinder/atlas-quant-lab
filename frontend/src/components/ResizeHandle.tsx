import { useRef, type KeyboardEvent, type PointerEvent, type RefObject } from 'react'

type ResizeSide = 'left' | 'right' | 'bottom'

interface Props {
  rootRef: RefObject<HTMLDivElement | null>
  side: ResizeSide
  cssVariable: string
  value: number
  minimum: number
  maximum: number
  defaultValue: number
  label: string
  onCommit: (value: number) => void
  oppositeCssVariable?: string
  centerMinimum?: number
}

interface DragState {
  pointerId: number
  startPointer: number
  startValue: number
  latestValue: number
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, Math.round(value)))
}

export function ResizeHandle(props: Props) {
  const handleRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const vertical = props.side !== 'bottom'

  const effectiveMaximum = () => {
    const root = props.rootRef.current
    if (props.side === 'bottom') {
      const available = (handleRef.current?.parentElement?.clientHeight ?? 0) - (props.centerMinimum ?? 260) - 5
      return Math.max(props.minimum, Math.min(props.maximum, available))
    }
    if (!root || !props.oppositeCssVariable) return props.maximum
    const opposite = Number.parseFloat(getComputedStyle(root).getPropertyValue(props.oppositeCssVariable)) || 0
    const available = root.clientWidth - opposite - (props.centerMinimum ?? 460) - 10
    return Math.max(props.minimum, Math.min(props.maximum, available))
  }

  const apply = (value: number) => {
    const next = clamp(value, props.minimum, effectiveMaximum())
    props.rootRef.current?.style.setProperty(props.cssVariable, `${next}px`)
    const handle = handleRef.current
    if (handle) {
      handle.dataset.value = `${next}px`
      handle.setAttribute('aria-valuenow', String(next))
    }
    return next
  }

  const finish = (event?: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    if (event && event.currentTarget.hasPointerCapture(drag.pointerId)) {
      event.currentTarget.releasePointerCapture(drag.pointerId)
    }
    dragRef.current = null
    handleRef.current?.classList.remove('is-dragging')
    document.body.classList.remove('is-resizing-layout')
    props.onCommit(drag.latestValue)
  }

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    const root = props.rootRef.current
    if (!root) return
    event.preventDefault()
    const current = Number.parseFloat(
      getComputedStyle(root).getPropertyValue(props.cssVariable),
    ) || props.value
    const pointer = vertical ? event.clientX : event.clientY
    dragRef.current = {
      pointerId: event.pointerId,
      startPointer: pointer,
      startValue: current,
      latestValue: current,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.currentTarget.classList.add('is-dragging')
    document.body.classList.add('is-resizing-layout')
  }

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const pointer = vertical ? event.clientX : event.clientY
    const direction = props.side === 'left' ? 1 : -1
    drag.latestValue = apply(drag.startValue + (pointer - drag.startPointer) * direction)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let delta = 0
    if (props.side === 'left') {
      if (event.key === 'ArrowLeft') delta = -8
      if (event.key === 'ArrowRight') delta = 8
    } else if (props.side === 'right') {
      if (event.key === 'ArrowLeft') delta = 8
      if (event.key === 'ArrowRight') delta = -8
    } else {
      if (event.key === 'ArrowUp') delta = 8
      if (event.key === 'ArrowDown') delta = -8
    }
    if (event.key === 'Home') delta = props.minimum - props.value
    if (event.key === 'End') delta = props.maximum - props.value
    if (delta === 0) return
    event.preventDefault()
    const next = apply(props.value + delta)
    props.onCommit(next)
  }

  const reset = () => {
    const next = apply(props.defaultValue)
    props.onCommit(next)
  }

  return (
    <div
      ref={handleRef}
      className={`resize-handle resize-${props.side}`}
      role="separator"
      tabIndex={0}
      aria-label={props.label}
      aria-orientation={vertical ? 'vertical' : 'horizontal'}
      aria-valuemin={props.minimum}
      aria-valuemax={props.maximum}
      aria-valuenow={props.value}
      data-value={`${props.value}px`}
      title={`${props.label}；双击恢复默认`}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
    />
  )
}
