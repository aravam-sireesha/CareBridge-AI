import React, { useEffect, useRef } from 'react'
import { IconX } from './icons.jsx'

/** A side panel for record details. Focus moves into it, Esc and the backdrop close it, focus returns to what opened it. */
export default function Drawer({ open, title, onClose, children }) {
  const closeRef = useRef(null)
  const opener = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    opener.current = document.activeElement
    closeRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = prev; opener.current?.focus?.() }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close details" className="absolute inset-0 bg-slate-900/40" onClick={onClose} tabIndex={-1} />
      <aside role="dialog" aria-modal="true" aria-label={title} className="relative flex h-full w-full max-w-md flex-col border-l border-line bg-white shadow-xl">
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="truncate font-display text-base font-semibold text-ink">{title}</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-ink-muted hover:bg-bg hover:text-ink"><IconX className="h-5 w-5" /></button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </aside>
    </div>
  )
}
