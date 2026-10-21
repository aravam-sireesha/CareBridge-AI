import React, { useState } from 'react'
import { IconCheck, IconX } from './icons.jsx'
import { Spinner, EmptyState } from './ui.jsx'
import StatusBadge from './StatusBadge.jsx'
import { IconSpark } from './icons.jsx'

const UNDECIDED = ['suggested', 'flagged', 'open', 'pending_review', 'pending']

function ScoreRing({ score }) {
  const pct = Math.round((score || 0) * 100)
  const color = pct >= 66 ? '#CC554A' : pct >= 33 ? '#D98B1C' : '#1E877F'
  const r = 18, c = 2 * Math.PI * r
  return (
    <div className="relative grid h-12 w-12 shrink-0 place-items-center" title={`Score ${pct}%`}>
      <svg width="48" height="48" viewBox="0 0 44 44" className="-rotate-90">
        <circle cx="22" cy="22" r={r} fill="none" stroke="#EAF6F4" strokeWidth="5" />
        <circle cx="22" cy="22" r={r} fill="none" stroke={color} strokeWidth="5" strokeLinecap="round" strokeDasharray={`${(pct / 100) * c} ${c}`} />
      </svg>
      <span className="absolute text-[11px] font-bold text-ink">{pct}</span>
    </div>
  )
}

/** item: { id, title, subtitle, score, reasons[], status, meta[] } */
export function ReviewCard({ item, onApprove, onReject, approveLabel = 'Approve', rejectLabel = 'Reject', readOnly = false }) {
  const [busy, setBusy] = useState(null)
  const decided = item.status && !UNDECIDED.includes(String(item.status).toLowerCase())
  const run = async (kind, fn) => { setBusy(kind); try { await fn(item) } finally { setBusy(null) } }

  return (
    <div className="card card-hover animate-rise-in p-5">
      <div className="flex items-start gap-4">
        {typeof item.score === 'number' && <ScoreRing score={item.score} />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-display text-[15px] font-semibold text-ink">{item.title}</p>
            <StatusBadge status={item.status} />
          </div>
          {item.subtitle && <p className="mt-0.5 text-[13px] text-ink-muted">{item.subtitle}</p>}
        </div>
      </div>

      {item.reasons?.length > 0 && (
        <ul className="mt-4 space-y-1.5 rounded-xl bg-teal-50/60 p-3">
          {item.reasons.map((r, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px] text-ink">
              <IconSpark className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal-600" />{r}
            </li>
          ))}
        </ul>
      )}

      {!decided && !readOnly && (
        <div className="mt-4 flex justify-end gap-2">
          <button disabled={busy !== null} onClick={() => run('reject', onReject)} className="btn-danger px-3 py-2 text-xs">
            {busy === 'reject' ? <Spinner className="h-3.5 w-3.5" /> : <IconX className="h-3.5 w-3.5" />}{rejectLabel}
          </button>
          <button disabled={busy !== null} onClick={() => run('approve', onApprove)} className="btn-primary px-3 py-2 text-xs">
            {busy === 'approve' ? <Spinner className="h-3.5 w-3.5" /> : <IconCheck className="h-3.5 w-3.5" />}{approveLabel}
          </button>
        </div>
      )}
      {!decided && readOnly && <p className="mt-3 text-xs text-ink-muted">Waiting for an administrator to review this suggestion.</p>}
    </div>
  )
}

export function ReviewList({ items, emptyTitle = 'Nothing to review', emptyText, icon, ...cardProps }) {
  if (!items?.length) return <EmptyState icon={icon} title={emptyTitle} text={emptyText} />
  return <div className="grid gap-4 md:grid-cols-2">{items.map((item) => <ReviewCard key={item.id} item={item} {...cardProps} />)}</div>
}
