import React, { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { IconCheck, IconX, IconAlert, IconSpark } from '../components/icons.jsx'

const ToastContext = createContext(null)
let counter = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const dismiss = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), [])
  const push = useCallback((message, tone) => {
    const id = ++counter
    setToasts((t) => [...t.slice(-3), { id, message, tone }])
    setTimeout(() => dismiss(id), tone === 'error' ? 6500 : 4000)
  }, [dismiss])

  const toast = useMemo(() => ({
    success: (m) => push(m, 'success'), error: (m) => push(m, 'error'), info: (m) => push(m, 'info')
  }), [push])

  const styles = {
    success: ['border-green-200 bg-white', 'bg-green-500', IconCheck],
    error: ['border-red-200 bg-white', 'bg-red-500', IconAlert],
    info: ['border-sky-200 bg-white', 'bg-sky-500', IconSpark]
  }

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((t) => {
          const [box, dot, Icon] = styles[t.tone]
          return (
            <div key={t.id} role="status" className={`pointer-events-auto animate-pop flex items-start gap-3 rounded-xl border p-3.5 shadow-lift ${box}`}>
              <span className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-white ${dot}`}><Icon className="h-3.5 w-3.5" /></span>
              <p className="flex-1 text-sm text-ink">{t.message}</p>
              <button onClick={() => dismiss(t.id)} className="text-ink-muted hover:text-ink" aria-label="Dismiss"><IconX className="h-4 w-4" /></button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx
}
