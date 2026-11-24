import React from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import StatusBadge from './StatusBadge.jsx'
import { Button, CardSkeleton, Section, formatDate } from './ui.jsx'

const CARDS = [
  ['users_total', 'Registered users', '/admin/users'], ['pending_verifications', 'Pending verifications', '/admin/verification?status=pending'],
  ['active_organizations', 'Active organizations', '/admin/organizations'], ['active_donors', 'Active donors', '/admin/people?tab=donors'],
  ['active_volunteers', 'Active volunteers', '/admin/people?tab=volunteers'], ['active_needs', 'Active needs', '/admin/needs'],
  ['donations_in_progress', 'Donations in progress', '/donations'], ['donations_completed', 'Completed donations', '/donations'],
  ['anomalies_outstanding', 'Anomaly alerts to review', '/admin/anomalies']
]

/** Platform-wide counts straight from the database. If they cannot be loaded we say so; we never show placeholder numbers. */
export default function AdminKpis() {
  const kpis = useAsync(() => api.adminKpis(), [])
  const k = kpis.data
  if (kpis.error) return <div role="status" className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-white p-4 text-sm text-ink-muted"><span>Platform figures are unavailable right now.</span><Button variant="ghost" onClick={kpis.reload}>Try again</Button></div>
  if (!k) return <div className="mb-6"><CardSkeleton rows={2} /></div>
  return (
    <section aria-label="Platform summary" className="mb-8">
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {CARDS.map(([key, label, to]) => (
          <Link key={key} to={to} className="card block p-4 transition hover:shadow-lift focus-visible:ring-2">
            <dd className="font-display text-2xl font-bold text-teal-700">{Number(k[key] ?? 0).toLocaleString('en-IN')}</dd>
            <dt className="mt-0.5 text-xs font-semibold text-ink-muted">{label}</dt>
          </Link>
        ))}
      </dl>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Section title="Verification queue" action={<Link to="/admin/verification" className="text-sm font-semibold text-sky-600 hover:underline">Open</Link>}>
          <div className="card divide-y divide-line">
            {k.verification_queue.length === 0 && <p className="p-5 text-sm text-ink-muted">No organizations are waiting for review.</p>}
            {k.verification_queue.map((o) => (
              <div key={o.id} className="flex items-center justify-between gap-3 px-4 py-3"><div><p className="text-sm font-semibold text-ink">{o.name}</p><p className="text-xs text-ink-muted">Submitted {formatDate(o.submitted_at)}</p></div><StatusBadge status={o.status} /></div>
            ))}
          </div>
        </Section>
        <Section title="Recent platform activity" action={<Link to="/admin/audit" className="text-sm font-semibold text-sky-600 hover:underline">Audit trail</Link>}>
          <div className="card divide-y divide-line">
            {k.recent_activity.length === 0 && <p className="p-5 text-sm text-ink-muted">No activity yet.</p>}
            {k.recent_activity.map((a, i) => <div key={i} className="px-4 py-3"><p className="text-sm font-semibold text-ink">{a.action.replace(/[._]/g, ' ')}</p><p className="text-xs text-ink-muted">{a.by || 'Not signed in'} · {new Date(a.at).toLocaleString()}</p></div>)}
          </div>
        </Section>
      </div>
    </section>
  )
}
