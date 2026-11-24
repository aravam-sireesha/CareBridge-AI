import React from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import { EmptyState, ErrorState, Skeleton } from './ui.jsx'
import { IconAlertTri } from './ai/icons.jsx'

const TONE = { high: 'border-l-red-500', medium: 'border-l-amber-500', low: 'border-l-sky-500' }

/** Alerts for administrators, each one a count calculated from stored records, with links that open the records.
 *  What the platform does not record is listed at the bottom instead of being guessed. */
export default function AdminAlerts() {
  const { data, loading, error, reload } = useAsync(() => api.adminAlerts(), [])
  const when = data?.generated_at ? new Date(`${data.generated_at}Z`).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : null
  return (
    <section className="card p-5" aria-label="Alerts">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-base font-semibold text-ink">Needs your attention</h2>
        {when && <span className="text-xs text-ink-muted">Calculated {when}</span>}
      </div>
      {error ? <ErrorState message={error} onRetry={reload} />
        : loading && !data ? <div role="status" aria-live="polite" className="space-y-3"><span className="sr-only">Loading alerts…</span>{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)}</div>
        : data.alerts.length === 0 ? <EmptyState title="Nothing needs attention" text={`No needs have waited ${data.stale_days}+ days, no organizations are waiting, and no unusual donations are unreviewed.`} />
        : (
          <ul className="space-y-3">
            {data.alerts.map((a) => (
              <li key={a.key} className={`rounded-lg border border-line border-l-4 ${TONE[a.severity] || 'border-l-sky-500'} p-3`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0"><p className="flex items-center gap-2 text-sm font-semibold text-ink"><IconAlertTri className="h-4 w-4 shrink-0 text-ink-muted" />{a.title}</p><p className="mt-0.5 text-xs text-ink-muted">{a.detail}</p></div>
                  <Link to={a.link} className="shrink-0 text-xs font-semibold text-teal-700 hover:underline">Open list</Link>
                </div>
                {a.items?.length > 0 && <ul className="mt-2 space-y-1 border-t border-line pt-2">{a.items.map((it, i) => <li key={i} className="text-xs"><Link to={it.link} className="text-ink hover:text-teal-700 hover:underline">{it.label}</Link></li>)}</ul>}
              </li>
            ))}
          </ul>
        )}
      {data?.not_tracked?.length > 0 && (
        <details className="mt-3 text-xs text-ink-muted"><summary className="cursor-pointer font-semibold">Not tracked by the platform</summary>
          <ul className="mt-1.5 space-y-1">{data.not_tracked.map((n) => <li key={n.key}><strong className="text-ink">{n.title}:</strong> {n.reason}</li>)}</ul></details>
      )}
    </section>
  )
}
