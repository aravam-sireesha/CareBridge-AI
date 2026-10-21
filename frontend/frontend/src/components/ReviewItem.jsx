import React from 'react'
import { LevelPill, Reasons, ScoreBar } from './AdminParts.jsx'
import { Button, Pill } from './ui.jsx'
import { IconCheck, IconX } from './icons.jsx'

export const TYPE_LABELS = {
  fraud_flag: 'Suspicious donation', need_alert: 'Predicted need', organization: 'Organization verification',
  allocation: 'Resource allocation', match: 'Donor / volunteer match', donor_suggestion: 'Donor suggestion', volunteer_suggestion: 'Volunteer suggestion'
}
const TYPE_TONE = { fraud_flag: 'red', need_alert: 'amber', organization: 'sky', allocation: 'green', match: 'violet', donor_suggestion: 'rose', volunteer_suggestion: 'sky' }
const DECISION = {
  verify: ['Verify organization', 'primary'], confirmed_fraud: ['Confirm fraud', 'danger'], false_positive: ['False alarm', 'ghost'],
  action_taken: ['Take action', 'primary'], dismissed: ['Dismiss', 'ghost'], confirmed: ['Confirm', 'primary'], rejected: ['Reject', 'danger'],
  approved: ['Approve', 'primary'], contacted: ['Mark contacted', 'ghost']
}

/** One decision the AI hands to an administrator: what it is, why it was raised, and the buttons to decide. */
export default function ReviewItem({ item, busy, onDecide }) {
  const severity = { high: 'critical', medium: 'medium', low: 'low' }[item.severity]
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Pill tone={TYPE_TONE[item.type]} className="mb-1.5">{TYPE_LABELS[item.type]}</Pill>
          <p className="text-sm font-semibold text-ink">{item.title}</p>
          <p className="mt-0.5 text-xs text-ink-muted">{item.subtitle}</p>
        </div>
        {item.severity === 'high' && <LevelPill level={severity} />}
      </div>
      {item.score != null && <div className="mt-3 max-w-xs"><ScoreBar label="AI score" value={item.score} tone="rose" /></div>}
      <Reasons items={item.reasons.slice(0, 4)} />
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        {item.decisions.map((d) => {
          const [label, variant] = DECISION[d] || [d, 'ghost']
          return <Button key={d} variant={variant} disabled={busy} className="px-3 py-1.5 text-xs" onClick={() => onDecide(item, d)}>{['primary'].includes(variant) ? <IconCheck className="h-3.5 w-3.5" /> : variant === 'danger' ? <IconX className="h-3.5 w-3.5" /> : null}{label}</Button>
        })}
      </div>
    </div>
  )
}
