import React from 'react'
import StatusBadge from './StatusBadge.jsx'
import { Button, Pill } from './ui.jsx'
import { IconCheck, IconPhone, IconX } from './icons.jsx'

export const pct = (v) => `${Math.round((Number(v) || 0) * 100)}%`

/** Thin labelled bar for 0-1 scores. */
export function ScoreBar({ label, value, tone = 'teal' }) {
  const color = { teal: 'bg-teal-500', sky: 'bg-sky-500', amber: 'bg-amber-500', rose: 'bg-rose-500' }[tone]
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] font-semibold text-ink-muted"><span>{label}</span><span className="text-ink">{pct(value)}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink/5" role="progressbar" aria-label={label} aria-valuenow={Math.round((value || 0) * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: pct(value) }} />
      </div>
    </div>
  )
}

export const levelTone = (level) => ({ critical: 'red', high: 'rose', medium: 'amber', low: 'green' }[level] || 'gray')

export function Reasons({ items = [] }) {
  if (!items.length) return null
  return <ul className="mt-2 space-y-1">{items.map((r, i) => <li key={i} className="flex gap-2 text-xs leading-relaxed text-ink-muted"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />{r}</li>)}</ul>
}

/** One ML donor suggestion with the decision buttons. */
export function SuggestionCard({ s, onDecide, busy, showNeed = true }) {
  const decided = s.status !== 'suggested'
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink"><span className="grid h-6 w-6 place-items-center rounded-md bg-sky-100 text-[11px] font-bold text-sky-700">#{s.rank_in_need}</span>{s.donor_name || `Donor ${s.donor_id}`}</p>
          {showNeed && <p className="mt-1 text-xs text-ink-muted">for <strong className="text-ink">{s.need_category || `need ${s.need_id}`}</strong>{s.organization_name ? ` · ${s.organization_name}` : ''}{s.need_urgency ? ` · ${s.need_urgency} urgency` : ''}</p>}
          {s.donor_contact && <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-muted"><IconPhone className="h-3.5 w-3.5" />{s.donor_contact}{s.donor_preferences ? ` · supports ${s.donor_preferences}` : ''}</p>}
        </div>
        <StatusBadge status={s.status} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <ScoreBar label="Donor fit" value={s.fit_score} />
        <ScoreBar label="Need urgency" value={s.urgency_score} tone="amber" />
        <ScoreBar label="Priority" value={s.priority_score} tone="rose" />
      </div>
      <Reasons items={s.reasons} />
      {!decided && onDecide && (
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <Button variant="danger" disabled={busy} className="px-3 py-1.5 text-xs" onClick={() => onDecide(s, 'rejected')}><IconX className="h-3.5 w-3.5" />Reject</Button>
          <Button variant="ghost" disabled={busy} className="px-3 py-1.5 text-xs" onClick={() => onDecide(s, 'contacted')}><IconPhone className="h-3.5 w-3.5" />Mark contacted</Button>
          <Button disabled={busy} className="px-3 py-1.5 text-xs" onClick={() => onDecide(s, 'approved')}><IconCheck className="h-3.5 w-3.5" />Approve</Button>
        </div>
      )}
      <p className="mt-2 text-[10px] text-ink-muted/80">{s.model_version}</p>
    </div>
  )
}

export function LevelPill({ level }) {
  return <Pill tone={levelTone(level)} className="capitalize">{level}</Pill>
}
