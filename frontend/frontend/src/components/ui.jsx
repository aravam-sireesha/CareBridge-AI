import React, { useEffect, useState } from 'react'
import { IconX, IconCheck } from './icons.jsx'

export function Spinner({ className = 'h-4 w-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M21 12a9 9 0 00-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function Button({ variant = 'primary', loading = false, disabled = false, children, className = '', ...props }) {
  return (
    <button className={`btn-${variant} ${className}`} {...props} disabled={loading || disabled}>
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function Field({ label, hint, error, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="mb-1.5 block text-[13px] font-semibold text-ink">{label}</span>}
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
      {error && <span className="mt-1 block text-xs font-medium text-red-600">{error}</span>}
    </label>
  )
}

export function Modal({ open, onClose, title, subtitle, children, wide = false }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/50 p-4 backdrop-blur-sm sm:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div role="dialog" aria-modal="true" aria-label={title} className={`animate-pop max-h-[92vh] w-full overflow-y-auto rounded-2xl bg-white shadow-lift ${wide ? 'max-w-2xl' : 'max-w-lg'}`}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <h2 className="font-display text-lg font-semibold text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-ink-muted transition hover:bg-bg hover:text-ink" aria-label="Close"><IconX /></button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="mb-5 flex gap-1 overflow-x-auto rounded-xl bg-teal-50/70 p-1" role="tablist">
      {tabs.map((t) => {
        const key = typeof t === 'string' ? t : t.key
        const label = typeof t === 'string' ? t : t.label
        const Icon = typeof t === 'string' ? null : t.icon
        const active = value === key
        return (
          <button key={key} role="tab" aria-selected={active} onClick={() => onChange(key)}
            className={`flex shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${active ? 'bg-white text-teal-700 shadow-card' : 'text-ink-muted hover:text-teal-700'}`}>
            {Icon && <Icon className="h-4 w-4" />}{label}
          </button>
        )
      })}
    </div>
  )
}

export function EmptyState({ icon: Icon, title, text, action }) {
  return (
    <div className="card flex flex-col items-center border-dashed px-6 py-12 text-center">
      {Icon && (
        <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-teal-50 to-sky-50 text-teal-600">
          <Icon className="h-7 w-7" />
        </div>
      )}
      <p className="font-display text-base font-semibold text-ink">{title}</p>
      {text && <p className="mt-1 max-w-sm text-sm text-ink-muted">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="card flex flex-col items-center border-red-100 bg-red-50/50 px-6 py-10 text-center">
      <p className="font-display text-base font-semibold text-red-700">Something went wrong</p>
      <p className="mt-1 max-w-md text-sm text-red-700/80">{message}</p>
      {onRetry && <Button variant="ghost" className="mt-4" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function Skeleton({ className = '' }) {
  return <div className={`skeleton ${className}`} />
}

export function CardSkeleton({ rows = 3 }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="card p-4">
          <Skeleton className="mb-3 h-3.5 w-1/3" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  )
}

export function TableSkeleton({ rows = 5, cols = 4 }) {
  return (
    <div className="card overflow-hidden">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4 border-b border-line px-4 py-4 last:border-0">
          {Array.from({ length: cols }).map((_, c) => <Skeleton key={c} className="h-3.5 flex-1" />)}
        </div>
      ))}
    </div>
  )
}

export function Pill({ children, tone = 'teal', className = '' }) {
  const tones = {
    teal: 'bg-teal-50 text-teal-700', sky: 'bg-sky-50 text-sky-700', amber: 'bg-amber-50 text-amber-700',
    green: 'bg-green-50 text-green-700', red: 'bg-red-50 text-red-700', violet: 'bg-violet-50 text-violet-700',
    rose: 'bg-rose-50 text-rose-600', gray: 'bg-ink/5 text-ink-muted'
  }
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tones[tone]} ${className}`}>{children}</span>
}

/** Gradient page banner with a decorative backdrop; used at the top of every screen. */
export function PageHeader({ title, subtitle, actions, icon: Icon, tone = 'teal' }) {
  const bg = {
    teal: 'from-teal-700 via-teal-600 to-sky-600', violet: 'from-violet-600 via-sky-600 to-teal-600',
    amber: 'from-amber-600 via-teal-600 to-sky-600', rose: 'from-rose-500 via-violet-500 to-sky-600'
  }[tone]
  return (
    <div className={`relative mb-6 overflow-hidden rounded-3xl bg-gradient-to-r ${bg} px-6 py-6 text-white shadow-lift sm:px-8`}>
      <div className="dot-grid absolute inset-0 opacity-40" />
      <div className="absolute -right-10 -top-16 h-56 w-56 rounded-full bg-white/10" />
      <div className="absolute -bottom-20 right-24 h-44 w-44 rounded-full bg-amber-100/15" />
      <div className="relative flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          {Icon && <div className="hidden h-12 w-12 place-items-center rounded-2xl bg-white/15 backdrop-blur sm:grid"><Icon className="h-6 w-6" /></div>}
          <div>
            <h1 className="font-display text-xl font-semibold sm:text-2xl">{title}</h1>
            {subtitle && <p className="mt-1 max-w-2xl text-sm text-white/85">{subtitle}</p>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}

export function StatCard({ label, value, hint, icon: Icon, tone = 'teal', to }) {
  const tones = {
    teal: ['from-teal-500 to-teal-700', 'text-teal-700'], sky: ['from-sky-400 to-sky-600', 'text-sky-700'],
    amber: ['from-amber-400 to-amber-600', 'text-amber-700'], violet: ['from-violet-400 to-violet-600', 'text-violet-700'],
    rose: ['from-rose-400 to-rose-600', 'text-rose-600'], green: ['from-green-400 to-green-600', 'text-green-700'],
    red: ['from-red-400 to-red-600', 'text-red-700']
  }[tone]
  return (
    <div className="card card-hover relative overflow-hidden p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-ink-muted">{label}</p>
          <p className={`mt-2 font-display text-3xl font-bold ${tones[1]}`}>{value ?? '–'}</p>
          {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
        </div>
        {Icon && <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white shadow-card ${tones[0]}`}><Icon className="h-5 w-5" /></div>}
      </div>
      <div className={`absolute -bottom-6 -right-6 h-20 w-20 rounded-full bg-gradient-to-br opacity-10 ${tones[0]}`} />
    </div>
  )
}

export function Section({ title, action, children, className = '' }) {
  return (
    <section className={`mb-8 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-display text-base font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function PasswordStrength({ password }) {
  const checks = [password.length >= 12, /[a-z]/.test(password) && /[A-Z]/.test(password), /\d/.test(password), /[^A-Za-z0-9]/.test(password)]
  const score = checks.filter(Boolean).length
  const labels = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong']
  const colors = ['bg-red-400', 'bg-red-400', 'bg-amber-400', 'bg-green-400', 'bg-green-500']
  return (
    <div className="mt-2">
      <div className="flex gap-1">
        {[0, 1, 2, 3].map((i) => <span key={i} className={`h-1.5 flex-1 rounded-full transition-colors ${i < score ? colors[score] : 'bg-line'}`} />)}
      </div>
      <p className="mt-1.5 flex items-center gap-1 text-xs text-ink-muted">
        {password.length >= 12 ? <IconCheck className="h-3.5 w-3.5 text-green-600" /> : null}
        {password ? labels[score] : 'Use at least 12 characters'}
      </p>
    </div>
  )
}

export function formatDate(value) {
  if (!value) return '–'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '–' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatMoney(value) {
  if (value === null || value === undefined) return '–'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(value))
}

/** Confirmation dialog for consequential actions. Optionally collects a reason (required when `reasonRequired`). */
export function ConfirmDialog({ open, title, text, confirmLabel = 'Confirm', tone = 'primary', loading = false, reasonLabel, reasonRequired = false, onConfirm, onCancel }) {
  const [reason, setReason] = useState('')
  useEffect(() => { if (open) setReason('') }, [open])
  const blocked = loading || (reasonRequired && !reason.trim())
  return (
    <Modal open={open} onClose={loading ? undefined : onCancel} title={title}>
      {text && <p className="text-sm text-ink-muted">{text}</p>}
      {reasonLabel && (
        <Field label={reasonLabel} className="mt-4" hint={reasonRequired ? 'Required. This is saved in the audit trail.' : 'Optional. Saved in the audit trail.'}>
          <textarea className="field min-h-[88px]" maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel} disabled={loading}>Cancel</Button>
        <Button variant={tone} loading={loading} disabled={blocked} onClick={() => onConfirm(reason.trim())}>{confirmLabel}</Button>
      </div>
    </Modal>
  )
}

export function Pagination({ page, pages, total, onPage, label = 'items' }) {
  if (!total) return null
  return (
    <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted" aria-label="Pagination">
      <span>{total} {label} · page {page} of {pages}</span>
      <span className="flex gap-2">
        <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </span>
    </nav>
  )
}
