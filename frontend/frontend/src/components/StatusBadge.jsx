import React from 'react'

const TONE = {
  pending_review: 'bg-sky-50 text-sky-700', flagged: 'bg-amber-50 text-amber-700',
  confirmed: 'bg-green-50 text-green-700', action_taken: 'bg-green-50 text-green-700', accepted: 'bg-green-50 text-green-700',
  rejected: 'bg-red-50 text-red-700', dismissed: 'bg-ink/5 text-ink-muted', false_positive: 'bg-ink/5 text-ink-muted',
  confirmed_fraud: 'bg-red-50 text-red-700', modified: 'bg-violet-50 text-violet-700',
  open: 'bg-sky-50 text-sky-700', pending: 'bg-amber-50 text-amber-700', fulfilled: 'bg-green-50 text-green-700', closed: 'bg-ink/5 text-ink-muted',
  critical: 'bg-red-50 text-red-700', high: 'bg-rose-50 text-rose-600', medium: 'bg-amber-50 text-amber-700', low: 'bg-green-50 text-green-700',
  proposed: 'bg-violet-50 text-violet-700', approved: 'bg-green-50 text-green-700', contacted: 'bg-sky-50 text-sky-700', delivered: 'bg-green-50 text-green-700', cancelled: 'bg-ink/5 text-ink-muted', suggested: 'bg-violet-50 text-violet-700',
  verified: 'bg-green-50 text-green-700', unverified: 'bg-amber-50 text-amber-700',
  under_review: 'bg-sky-50 text-sky-700', info_requested: 'bg-amber-50 text-amber-700', outstanding: 'bg-amber-50 text-amber-700',
  ready: 'bg-sky-50 text-sky-700', created: 'bg-green-50 text-green-700', skipped: 'bg-ink/5 text-ink-muted', inactive: 'bg-ink/5 text-ink-muted', active: 'bg-green-50 text-green-700',
  admin: 'bg-violet-50 text-violet-700', organization: 'bg-teal-50 text-teal-700', donor: 'bg-rose-50 text-rose-600', volunteer: 'bg-sky-50 text-sky-700'
}

export default function StatusBadge({ status }) {
  const key = String(status ?? '').toLowerCase()
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${TONE[key] || 'bg-ink/5 text-ink-muted'}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {key ? key.replace(/_/g, ' ') : 'unknown'}
    </span>
  )
}
