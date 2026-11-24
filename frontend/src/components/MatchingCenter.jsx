import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { Button, EmptyState, ErrorState, Field, Pill, Skeleton } from './ui.jsx'
import { IconHand, IconPin, IconSpark } from './icons.jsx'

const BAND = { strong: ['green', 'Strong fit'], good: ['teal', 'Good fit'], partial: ['amber', 'Partial fit'] }

function Person({ p, kind, needId, canPropose }) {
  const [tone, label] = BAND[p.fit] || BAND.partial
  return (
    <li className="rounded-xl border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0"><p className="truncate text-sm font-semibold text-ink">{p.name}</p><p className="text-xs text-ink-muted">{p.source}</p></div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Pill tone={tone}>{label}</Pill>
          {p.distance_label && <Pill tone="gray"><IconPin className="h-3 w-3" /> {p.distance_label}</Pill>}
        </div>
      </div>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink-muted">{p.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      {kind === 'donor' && canPropose && (
        <div className="mt-3"><Link className="btn-soft" to={`/deliveries?propose=1&need=${needId}&donor=${p.id}`}>Propose a delivery with {p.name}</Link></div>
      )}
    </li>
  )
}

function Column({ title, people, kind, empty, needId, canPropose }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold text-ink">{title} <span className="font-normal text-ink-muted">({people.length})</span></h3>
      {people.length ? <ul className="space-y-3">{people.map((p) => <Person key={p.id} p={p} kind={kind} needId={needId} canPropose={canPropose} />)}</ul>
        : <div className="rounded-xl border border-dashed border-line p-4"><p className="text-sm font-medium text-ink">No {kind === 'donor' ? 'donors' : 'volunteers'} to suggest</p>
          {empty.length ? <ul className="mt-2 space-y-2">{empty.map((u, i) => <li key={i} className="text-xs"><span className="text-ink-muted">{u.reason}</span> <span className="font-semibold text-teal-800">{u.suggestion}</span></li>)}</ul> : null}</div>}
    </section>
  )
}

/** Organization's matching workspace for one need. Suggestions only: nothing here assigns, commits or approves anyone. */
export default function MatchingCenter() {
  const toast = useToast()
  const needs = useAsync(() => api.listNeeds(), [])
  const open = useMemo(() => (needs.data || []).filter((n) => ['open', 'pending'].includes((n.status || '').toLowerCase())), [needs.data])
  const [needId, setNeedId] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (!needId && open.length) setNeedId(String(open[0].id)) }, [open, needId])

  const run = async () => {
    setBusy(true); setError('')
    try { setResult(await api.matchingCenter(needId)) } catch (e) { setError(e.message); toast.error(e.message) } finally { setBusy(false) }
  }
  useEffect(() => { setResult(null) }, [needId])

  if (needs.loading && !needs.data) return <div className="card mb-5 p-4"><Skeleton className="h-10 w-full" /></div>
  if (needs.error && !needs.data) return <ErrorState message={needs.error} onRetry={needs.reload} />
  const unmatched = result?.unmatched || []
  const forKind = (k) => unmatched.filter((u) => u.kind === k)
  return (
    <div className="mb-6 space-y-4">
      <div className="card flex flex-wrap items-end gap-3 p-4">
        <Field label="Find suggestions for need" className="min-w-[16rem] flex-1">
          <select className="field" value={needId} onChange={(e) => setNeedId(e.target.value)} disabled={!open.length}>
            {!open.length && <option>No open needs</option>}
            {open.map((n) => <option key={n.id} value={n.id}>{n.title || n.category} · {n.urgency} (#{n.id})</option>)}
          </select>
        </Field>
        <Button loading={busy} disabled={!needId} onClick={run}><IconSpark className="h-4 w-4" /> {result ? 'Refresh suggestions' : 'Find suggestions'}</Button>
      </div>
      {!open.length && <div className="card p-2"><EmptyState icon={IconHand} title="No open needs yet" text="Create a need first, then come back to find donors and volunteers for it." action={<Link to="/needs?new=1" className="btn-primary">Create a need</Link>} /></div>}
      {error && <ErrorState message={error} onRetry={run} />}
      {result && (
        <div className="card space-y-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ink-muted"><strong className="text-ink">{result.need.title || result.need.category}</strong> · still to arrange: <strong className="text-ink">{result.remaining_quantity}</strong></p>
            <Link className="text-sm font-semibold text-teal-700 hover:underline" to="/deliveries">See deliveries</Link>
          </div>
          <p className="rounded-xl bg-sky-50 p-3 text-xs text-sky-800" role="note">{result.note}</p>
          {unmatched.filter((u) => u.kind === 'general').map((u, i) => <p key={i} className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{u.reason} {u.suggestion}</p>)}
          <div className="grid gap-5 lg:grid-cols-2">
            <Column title="Donors" kind="donor" people={result.donors} empty={forKind('donor')} needId={result.need.id} canPropose={result.remaining_quantity > 0} />
            <Column title="Volunteers" kind="volunteer" people={result.volunteers} empty={forKind('volunteer')} needId={result.need.id} canPropose={false} />
          </div>
          <p className="text-xs text-ink-muted">A volunteer is offered a task only after a donor has committed, and becomes assigned only when they accept it.</p>
        </div>
      )}
    </div>
  )
}
