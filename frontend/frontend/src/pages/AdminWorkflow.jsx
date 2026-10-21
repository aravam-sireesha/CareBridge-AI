import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import WorkflowBoard from '../components/WorkflowBoard.jsx'
import ReviewItem from '../components/ReviewItem.jsx'
import ForecastPanel from '../components/ForecastPanel.jsx'
import AdminKpis from '../components/AdminKpis.jsx'
import { OverviewBody } from './AdminOverview.jsx'
import { prettyAction } from './AdminAudit.jsx'
import { Button, CardSkeleton, ErrorState, PageHeader, Section } from '../components/ui.jsx'
import { IconShield, IconSpark } from '../components/icons.jsx'

export default function AdminWorkflow() {
  const toast = useToast()
  const wf = useAsync(() => api.adminWorkflow(), [])
  const queue = useAsync(() => api.adminReviewQueue(), [])
  const overview = useAsync(() => api.adminOverview(), [])
  const trail = useAsync(() => api.adminAudit('?limit=6').catch(() => null), [])
  const demand = useAsync(() => api.adminForecast().catch(() => null), [])
  const tfa = useAsync(() => api.twoFaStatus().catch(() => null), [])
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)

  const refresh = () => { wf.reload({ silent: true }); queue.reload({ silent: true }); overview.reload({ silent: true }); trail.reload({ silent: true }) }
  const scan = async () => {
    setRunning(true)
    try {
      const r = await api.adminRunScans()
      toast.success(`AI scans finished: ${r.predicted_needs} predicted need(s), ${r.new_fraud_flags} new fraud flag(s), ${r.donor_suggestions} donor suggestion(s), ${r.resource_proposals} resource proposal(s).`)
      refresh()
    } catch (e) { toast.error(e.message) } finally { setRunning(false) }
  }
  const decide = async (item, decision) => {
    setBusy(true)
    try { await api.adminDecide(item.type, item.id, decision); toast.success('Decision saved and added to the audit trail.'); refresh() }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const pending = queue.data?.items || []

  return (
    <Layout title="Administration">
      <PageHeader icon={IconShield} title="Administration" subtitle="CareBridge AI end-to-end workflow: data comes in, AI analyses it, you decide, support reaches children."
        actions={<Button variant="ghost" loading={running} onClick={scan} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconSpark className="h-4 w-4" /> Run all AI scans</Button>} />

      {tfa.data && !tfa.data.enabled && (
        <div role="status" className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm text-amber-800"><strong>Protect your administrator account.</strong> Two-step verification adds a code from your phone to every sign-in.</p>
          <Link to="/settings?tab=security" className="btn-soft shrink-0">Turn on two-step verification</Link>
        </div>
      )}

      <AdminKpis />

      {wf.error ? <ErrorState message={wf.error} onRetry={wf.reload} /> : wf.loading && !wf.data ? <CardSkeleton rows={3} /> : <WorkflowBoard stages={wf.data.stages} />}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Section title={`Waiting for your decision${queue.data ? ` (${queue.data.total})` : ''}`} action={<Link to="/admin/review" className="text-sm font-semibold text-sky-600 hover:underline">Open the full queue</Link>}>
          {pending.length === 0 ? <p className="card p-6 text-center text-sm text-ink-muted">Nothing is waiting. Press “Run all AI scans” to look for new items.</p>
            : <div className="space-y-3">{pending.slice(0, 4).map((i) => <ReviewItem key={i.key} item={i} busy={busy} onDecide={decide} />)}</div>}
        </Section>
        <Section title="Track & monitor" action={<Link to="/admin/audit" className="text-sm font-semibold text-sky-600 hover:underline">Audit trail</Link>}>
          <div className="card divide-y divide-line">
            {(trail.data?.items || []).length === 0 && <p className="p-5 text-sm text-ink-muted">No activity yet.</p>}
            {(trail.data?.items || []).map((r) => (
              <div key={r.id} className="px-4 py-3"><p className="text-sm font-semibold text-ink">{prettyAction(r.action)}</p><p className="text-xs text-ink-muted">{r.actor_email || 'Not signed in'} · {new Date(r.created_at.endsWith('Z') ? r.created_at : `${r.created_at}Z`).toLocaleString()}</p></div>))}
          </div>
        </Section>
      </div>

      <Section title="Predicted demand (next 30 days)" action={<Link to="/admin/recommend" className="text-sm font-semibold text-sky-600 hover:underline">AI suggestion hub</Link>}>
        <div className="mt-8"><ForecastPanel items={demand.data?.items || []} limit={4} /></div>
      </Section>

      <h2 className="mb-4 mt-10 font-display text-lg font-semibold text-teal-800">At a glance</h2>
      <OverviewBody data={overview.data} loading={overview.loading && !overview.data} error={overview.error} reload={overview.reload} />
    </Layout>
  )
}
