import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, ErrorState, PageHeader, Pill, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconBuilding, IconCheck, IconX } from '../components/icons.jsx'

const gradeTone = (g) => ({ Thriving: 'green', Healthy: 'teal', 'Needs attention': 'amber', 'At risk': 'red' }[g] || 'gray')
const priorityTone = { high: 'red', medium: 'amber', low: 'sky' }

export default function AdminOrganizations() {
  const toast = useToast()
  const orgs = useAsync(() => api.adminOrganizations(), [])
  const health = useAsync(() => api.assistantInsights().then((d) => d.health || []).catch(() => []), [])
  const [open, setOpen] = useState(null)
  const byId = Object.fromEntries((health.data || []).map((h) => [h.organization_id, h]))

  const toggle = async (o) => {
    try { await api.verifyOrganization(o.id, !o.verified); toast.success(o.verified ? 'Verification removed.' : 'Organization verified. Its needs are now visible to donors and volunteers.'); orgs.reload({ silent: true }); health.reload({ silent: true }) }
    catch (e) { toast.error(e.message) }
  }
  return (
    <Layout title="Organizations">
      <PageHeader icon={IconBuilding} title="Organizations" subtitle="Verify organizations and see a live health score with suggestions for healthy development." />
      {orgs.error ? <ErrorState message={orgs.error} onRetry={orgs.reload} /> : orgs.loading ? <TableSkeleton rows={4} cols={5} /> : (
        <div className="space-y-3">
          {(orgs.data || []).map((o) => {
            const h = byId[o.id]
            const expanded = open === o.id
            return (
              <div key={o.id} className="card overflow-hidden">
                <div className="flex flex-wrap items-center gap-4 p-4">
                  <div className="min-w-0 flex-1"><p className="font-display text-base font-semibold text-ink">{o.name}</p><p className="text-xs text-ink-muted">{o.contact || 'No contact'} · joined {formatDate(o.created_at)} · {o.open_needs} open of {o.needs} needs</p></div>
                  <StatusBadge status={o.verified ? 'verified' : 'unverified'} />
                  {h ? <div className="text-right"><p className="font-display text-2xl font-bold text-teal-700">{h.score}<span className="text-sm text-ink-muted">/100</span></p><Pill tone={gradeTone(h.grade)}>{h.grade}</Pill></div> : <span className="text-xs text-ink-muted">{health.loading ? 'Scoring…' : 'No score'}</span>}
                  <div className="flex gap-2">
                    {h && <Button variant="ghost" className="px-3 py-1.5 text-xs" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : o.id)}>{expanded ? 'Hide' : 'Suggestions'}</Button>}
                    <Button variant={o.verified ? 'danger' : 'primary'} className="px-3 py-1.5 text-xs" onClick={() => toggle(o)}>{o.verified ? <><IconX className="h-3.5 w-3.5" />Unverify</> : <><IconCheck className="h-3.5 w-3.5" />Verify</>}</Button>
                  </div>
                </div>
                {h && expanded && (
                  <div className="border-t border-line bg-teal-50/40 p-4">
                    <div className="mb-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">{Object.entries(h.subscores).map(([k, v]) => <div key={k} className="rounded-xl bg-white p-3 text-center ring-1 ring-line"><p className="font-display text-lg font-bold text-teal-700">{v}</p><p className="text-[11px] capitalize text-ink-muted">{k.replace('_', ' ')}</p></div>)}</div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted/80">How to help this organization develop</p>
                    <ul className="space-y-2">{h.recommendations.map((r, i) => <li key={i} className="flex gap-3 rounded-xl bg-white p-3 ring-1 ring-line"><Pill tone={priorityTone[r.priority]} className="h-fit capitalize">{r.priority}</Pill><div><p className="text-sm font-semibold text-ink">{r.title}</p><p className="text-xs text-ink-muted">{r.detail}</p></div></li>)}</ul>
                  </div>
                )}
              </div>
            )
          })}
          {!(orgs.data || []).length && <p className="card p-6 text-center text-sm text-ink-muted">No organizations have registered yet.</p>}
        </div>
      )}
    </Layout>
  )
}
